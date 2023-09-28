import logging
import os
import posixpath
from string import Template

import yaml

from snowflake import snowpark
from snowflake.ml._internal import file_utils
from snowflake.ml._internal.exceptions import (
    error_codes,
    exceptions as snowml_exceptions,
)
from snowflake.ml._internal.utils import identifier
from snowflake.ml.model._deploy_client.image_builds import (
    base_image_builder,
    client_image_builder,
)
from snowflake.ml.model._deploy_client.utils import (
    constants,
    image_registry_client,
    snowservice_client,
)

logger = logging.getLogger(__name__)


class ServerImageBuilder(base_image_builder.ImageBuilder):
    """
    Server-side image building and upload to model registry.
    """

    def __init__(
        self,
        *,
        context_dir: str,
        full_image_name: str,
        image_repo: str,
        session: snowpark.Session,
        artifact_stage_location: str,
        compute_pool: str,
    ) -> None:
        """Initialization

        Args:
            context_dir: Local docker context dir.
            full_image_name: Full image name consists of image name and image tag.
            image_repo: Path to image repository.
            session: Snowpark session
            artifact_stage_location: Spec file and future deployment related artifacts will be stored under
                {stage}/models/{model_id}
            compute_pool: The compute pool used to run docker image build workload.
        """
        self.context_dir = context_dir
        self.image_repo = image_repo
        self.full_image_name = full_image_name
        self.session = session
        self.artifact_stage_location = artifact_stage_location
        self.compute_pool = compute_pool
        self.client = snowservice_client.SnowServiceClient(session)

        assert artifact_stage_location.startswith(
            "@"
        ), f"stage path should start with @, actual: {artifact_stage_location}"

    def build_and_upload_image(self) -> None:
        """
        Builds and uploads an image to the model registry.
        """
        logger.info("Starting server-side image build")
        self._build_image_in_remote_job()

    def _build_image_in_remote_job(self) -> None:
        context_tarball_stage_location = f"{self.artifact_stage_location}/{constants.CONTEXT}.tar.gz"
        spec_stage_location = f"{self.artifact_stage_location}/{constants.IMAGE_BUILD_JOB_SPEC_TEMPLATE}.yaml"
        kaniko_shell_script_stage_location = f"{self.artifact_stage_location}/{constants.KANIKO_SHELL_SCRIPT_NAME}"

        self._compress_and_upload_docker_context_tarball(context_tarball_stage_location=context_tarball_stage_location)

        self._construct_and_upload_docker_entrypoint_script(
            context_tarball_stage_location=context_tarball_stage_location
        )

        # This is more of a workaround to support non-spcs-registry images.
        # TODO[shchen] remove such logic when first-party-image is supported on snowservice registry.
        # The regular Kaniko image doesn't include a shell; only the debug image comes with a shell. We need a shell
        # as we use an sh script to launch Kaniko
        kaniko_image = "/".join([self.image_repo.rstrip("/"), "kaniko-project/executor:v1.16.0-debug"])
        registry_client = image_registry_client.ImageRegistryClient(self.session)
        if registry_client.image_exists(kaniko_image):
            logger.debug(f"Kaniko image already existed at {kaniko_image}, skipping uploading")
        else:
            image_builder_client = client_image_builder.ClientImageBuilder(
                context_dir="",  # pass dummy empty string as it won't be used.
                full_image_name=kaniko_image,
                image_repo=self.image_repo,
                session=self.session,
            )
            image_builder_client.build_and_upload_image(image_to_pull="gcr.io/kaniko-project/executor:v1.16.0-debug")
        self._construct_and_upload_job_spec(
            base_image=kaniko_image,
            kaniko_shell_script_stage_location=kaniko_shell_script_stage_location,
        )
        self._launch_kaniko_job(spec_stage_location)

    def _construct_and_upload_docker_entrypoint_script(self, context_tarball_stage_location: str) -> None:
        """Construct a shell script that invokes logic to uncompress the docker context tarball, then invoke Kaniko
        executor to build images and push to image registry; the script will also ensure the docker credential(used to
        authenticate to image registry) stays up-to-date when session token refreshes.

        Args:
            context_tarball_stage_location: Path context directory stage location.
        """

        kaniko_shell_script_template = os.path.join(
            os.path.dirname(__file__), f"templates/{constants.KANIKO_SHELL_SCRIPT_TEMPLATE}"
        )
        kaniko_shell_file = os.path.join(self.context_dir, constants.KANIKO_SHELL_SCRIPT_NAME)

        with open(kaniko_shell_script_template, encoding="utf-8") as template_file, open(
            kaniko_shell_file, "w+", encoding="utf-8"
        ) as script_file:
            normed_artifact_stage_path = posixpath.normpath(identifier.remove_prefix(self.artifact_stage_location, "@"))
            params = {
                # Remove @ in the beginning, append "/" to denote root directory.
                "tar_from": "/" + posixpath.normpath(identifier.remove_prefix(context_tarball_stage_location, "@")),
                # Remove @ in the beginning, append "/" to denote root directory.
                "tar_to": "/" + normed_artifact_stage_path,
                "context_dir": f"dir:///{normed_artifact_stage_path}/{constants.CONTEXT}",
                "image_repo": self.image_repo,
                # All models will be sharing the same layer cache from the image_repo/cache directory.
                "cache_repo": f"{self.image_repo.rstrip('/')}/cache",
                "image_destination": self.full_image_name,
            }
            template = Template(template_file.read())
            script = template.safe_substitute(params)
            script_file.write(script)
            logger.debug(f"script content: \n\n {script}")
        self.session.file.put(
            local_file_name=kaniko_shell_file,
            stage_location=self.artifact_stage_location,
            auto_compress=False,
            overwrite=True,
        )

    def _compress_and_upload_docker_context_tarball(self, context_tarball_stage_location: str) -> None:
        try:
            with file_utils._create_tar_gz_stream(
                source_dir=self.context_dir, arcname=constants.CONTEXT
            ) as input_stream:
                self.session.file.put_stream(
                    input_stream=input_stream,
                    stage_location=context_tarball_stage_location,
                    auto_compress=False,
                    overwrite=True,
                )
        except Exception as e:
            raise snowml_exceptions.SnowflakeMLException(
                error_code=error_codes.INTERNAL_SNOWPARK_ERROR,
                original_exception=RuntimeError(
                    "Exception occurred when compressing docker context dir as tarball and upload to stage."
                ),
            ) from e

    def _construct_and_upload_job_spec(self, base_image: str, kaniko_shell_script_stage_location: str) -> None:
        assert kaniko_shell_script_stage_location.startswith(
            "@"
        ), f"stage path should start with @, actual: {kaniko_shell_script_stage_location}"
        spec_template_path = os.path.join(
            os.path.dirname(__file__), f"templates/{constants.IMAGE_BUILD_JOB_SPEC_TEMPLATE}"
        )
        spec_file_path = os.path.join(
            os.path.dirname(self.context_dir), f"{constants.IMAGE_BUILD_JOB_SPEC_TEMPLATE}.yaml"
        )

        with open(spec_template_path, encoding="utf-8") as template_file, open(
            spec_file_path, "w+", encoding="utf-8"
        ) as spec_file:
            assert self.artifact_stage_location.startswith("@")
            normed_artifact_stage_path = posixpath.normpath(identifier.remove_prefix(self.artifact_stage_location, "@"))
            (db, schema, stage, path) = identifier.parse_schema_level_object_identifier(normed_artifact_stage_path)
            content = Template(template_file.read()).substitute(
                {
                    "base_image": base_image,
                    "container_name": constants.KANIKO_CONTAINER_NAME,
                    "stage": identifier.get_schema_level_object_identifier(db, schema, stage),
                    # Remove @ in the beginning, append "/" to denote root directory.
                    "script_path": "/"
                    + posixpath.normpath(identifier.remove_prefix(kaniko_shell_script_stage_location, "@")),
                }
            )
            content_dict = yaml.safe_load(content)
            yaml.dump(content_dict, spec_file)
            spec_file.seek(0)
            logger.debug(f"Kaniko job spec file: \n\n {spec_file.read()}")

        self.session.file.put(
            local_file_name=spec_file_path,
            stage_location=self.artifact_stage_location,
            auto_compress=False,
            overwrite=True,
        )

    def _launch_kaniko_job(self, spec_stage_location: str) -> None:
        logger.debug("Submitting job for building docker image with kaniko")
        job_id = self.client.create_job(compute_pool=self.compute_pool, spec_stage_location=spec_stage_location)
        logger.debug(f"Kaniko job id is {job_id}")
        # Given image build can take a while, we set a generous timeout to be 1 hour.
        self.client.block_until_resource_is_ready(
            resource_name=job_id,
            resource_type=constants.ResourceType.JOB,
            container_name=constants.KANIKO_CONTAINER_NAME,
            max_retries=240,
            retry_interval_secs=15,
        )
