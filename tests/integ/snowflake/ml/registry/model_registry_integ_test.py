#
# Copyright (c) 2012-2022 Snowflake Computing Inc. All rights reserved.
#

import uuid
from typing import Dict

import numpy as np
import pandas as pd
import pytest
from absl.testing import absltest
from sklearn import metrics

from snowflake import connector
from snowflake.ml._internal.utils import identifier
from snowflake.ml.registry import _ml_artifact, model_registry
from snowflake.ml.training_dataset import training_dataset
from snowflake.ml.utils import connection_params
from snowflake.snowpark import Session
from tests.integ.snowflake.ml.test_utils import (
    db_manager,
    model_factory,
    test_env_utils,
)


class TestModelRegistryInteg(absltest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        """Creates Snowpark and Snowflake environments for testing."""
        cls._session = Session.builder.configs(connection_params.SnowflakeLoginOptions()).create()
        cls.run_id = uuid.uuid4().hex
        cls._db_manager = db_manager.DBManager(cls._session)
        cls.registry_name = db_manager.TestObjectNameGenerator.get_snowml_test_object_name(cls.run_id, "registry_db")
        model_registry.create_model_registry(session=cls._session, database_name=cls.registry_name)
        cls.perm_stage = "@" + cls._db_manager.create_stage(
            "model_registry_test_stage", "PUBLIC", cls.registry_name, sse_encrypted=True
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._db_manager.drop_database(cls.registry_name)
        cls._session.close()

    def test_basic_workflow(self) -> None:
        registry = model_registry.ModelRegistry(session=self._session, database_name=self.registry_name)

        # Prepare the model
        model_name = "basic_model"
        model_version = self.run_id
        model, test_features, test_labels = model_factory.ModelFactory.prepare_sklearn_model()

        local_prediction = model.predict(test_features)
        local_prediction_proba = model.predict_proba(test_features)

        model_tags: Dict[str, str] = {"stage": "testing", "classifier_type": "svm.SVC", "num_training_examples": "10"}

        # Test model logging
        with self.assertRaisesRegex(
            KeyError, f"The model {model_name}/{model_version} does not exist in the current registry."
        ):
            model_ref = model_registry.ModelReference(
                registry=registry, model_name=model_name, model_version=model_version
            )

        model_ref = registry.log_model(
            model_name=model_name,
            model_version=model_version,
            model=model,
            tags=model_tags,
            conda_dependencies=[
                test_env_utils.get_latest_package_versions_in_server(self._session, "snowflake-snowpark-python")
            ],
            sample_input_data=test_features,
            options={"embed_local_ml_library": True},
        )

        with self.assertRaisesRegex(
            connector.DataError, f"Model {model_name}/{model_version} already exists. Unable to log the model."
        ):
            registry.log_model(
                model_name=model_name,
                model_version=model_version,
                model=model,
                tags={"stage": "testing", "classifier_type": "svm.SVC"},
                conda_dependencies=[
                    test_env_utils.get_latest_package_versions_in_server(self._session, "snowflake-snowpark-python")
                ],
                sample_input_data=test_features,
                options={"embed_local_ml_library": True},
            )

        model_ref = model_registry.ModelReference(registry=registry, model_name=model_name, model_version=model_version)

        # Test getting model name and model version
        self.assertEqual(model_ref.get_name(), model_name)
        self.assertEqual(model_ref.get_version(), model_version)

        # Test metrics
        test_accuracy = metrics.accuracy_score(test_labels, local_prediction)

        model_ref.set_metric(metric_name="test_accuracy", metric_value=test_accuracy)  # type: ignore[attr-defined]

        model_ref.set_metric(metric_name="num_training_examples", metric_value=10)  # type: ignore[attr-defined]

        model_ref.set_metric(  # type: ignore[attr-defined]
            metric_name="dataset_test",
            metric_value={"accuracy": test_accuracy},
        )

        test_confusion_matrix = metrics.confusion_matrix(test_labels, local_prediction)

        model_ref.set_metric(  # type: ignore[attr-defined]
            metric_name="confusion_matrix",
            metric_value=test_confusion_matrix,
        )

        stored_metrics = model_ref.get_metrics()  # type: ignore[attr-defined]

        np.testing.assert_almost_equal(stored_metrics.pop("confusion_matrix"), test_confusion_matrix)

        self.assertDictEqual(
            stored_metrics,
            {
                "test_accuracy": test_accuracy,
                "num_training_examples": 10,
                "dataset_test": {"accuracy": test_accuracy},
            },
        )

        model_ref.remove_metric("confusion_matrix")  # type: ignore[attr-defined]
        self.assertDictEqual(
            model_ref.get_metrics(),  # type: ignore[attr-defined]
            {
                "test_accuracy": test_accuracy,
                "num_training_examples": 10,
                "dataset_test": {"accuracy": test_accuracy},
            },
        )

        with self.assertRaisesRegex(
            connector.DataError, f"Model {model_name}/{model_version} has no metric named confusion_matrix."
        ):
            model_ref.remove_metric(metric_name="confusion_matrix")  # type: ignore[attr-defined]

        model_ref.set_metric(metric_name="num_training_examples", metric_value=20)  # type: ignore[attr-defined]
        self.assertDictEqual(
            model_ref.get_metrics(),  # type: ignore[attr-defined]
            {
                "test_accuracy": test_accuracy,
                "num_training_examples": 20,
                "dataset_test": {"accuracy": test_accuracy},
            },
        )

        # Test list models
        model_list = registry.list_models().to_pandas()

        filtered_model_list = model_list.loc[model_list["ID"] == model_ref._id].reset_index(drop=True)

        self.assertEqual(filtered_model_list.shape[0], 1)
        self.assertEqual(filtered_model_list["NAME"][0], second=model_name)
        self.assertEqual(filtered_model_list["VERSION"][0], second=model_version)

        # Test tags
        self.assertDictEqual(model_ref.get_tags(), model_tags)  # type: ignore[attr-defined]

        model_ref.set_tag(tag_name="minor_version", tag_value="23")  # type: ignore[attr-defined]
        self.assertDictEqual(model_ref.get_tags(), {**model_tags, "minor_version": "23"})  # type: ignore[attr-defined]

        model_ref.remove_tag(tag_name="minor_version")  # type: ignore[attr-defined]
        self.assertDictEqual(model_ref.get_tags(), model_tags)  # type: ignore[attr-defined]

        with self.assertRaisesRegex(
            connector.DataError, f"Model {model_name}/{model_version} has no tag named minor_version."
        ):
            model_ref.remove_tag(tag_name="minor_version")  # type: ignore[attr-defined]

        model_ref.set_tag("stage", "production")  # type: ignore[attr-defined]
        model_tags.update({"stage": "production"})
        self.assertDictEqual(model_ref.get_tags(), model_tags)  # type: ignore[attr-defined]

        # Test model description
        model_ref.set_model_description(  # type: ignore[attr-defined]
            description="My model is better than talkgpt-5!",
        )
        self.assertEqual(
            model_ref.get_model_description(), "My model is better than talkgpt-5!"  # type: ignore[attr-defined]
        )

        # Test loading model
        restored_model = model_ref.load_model()  # type: ignore[attr-defined]
        restored_prediction = restored_model.predict(test_features)
        np.testing.assert_allclose(local_prediction, restored_prediction)

        # Test permanent deployment
        permanent_deployment_name = f"{model_name}_{model_version}_perm_deploy"
        model_ref.deploy(  # type: ignore[attr-defined]
            deployment_name=permanent_deployment_name,
            target_method="predict",
            permanent=True,
            options={"relax_version": test_env_utils.is_in_pip_env()},
        )
        remote_prediction_perm = model_ref.predict(permanent_deployment_name, test_features)
        np.testing.assert_allclose(remote_prediction_perm.to_numpy(), np.expand_dims(local_prediction, axis=1))

        custom_permanent_deployment_name = f"{model_name}_{model_version}_custom_perm_deploy"
        model_ref.deploy(  # type: ignore[attr-defined]
            deployment_name=custom_permanent_deployment_name,
            target_method="predict_proba",
            permanent=True,
            options={"permanent_udf_stage_location": self.perm_stage, "relax_version": test_env_utils.is_in_pip_env()},
        )
        remote_prediction_proba_perm = model_ref.predict(custom_permanent_deployment_name, test_features)
        np.testing.assert_allclose(remote_prediction_proba_perm.to_numpy(), local_prediction_proba)

        # Test deployment information
        model_deployment_list = model_ref.list_deployments().to_pandas()  # type: ignore[attr-defined]
        self.assertEqual(model_deployment_list.shape[0], 2)

        filtered_model_deployment_list = model_deployment_list.loc[
            model_deployment_list["DEPLOYMENT_NAME"] == custom_permanent_deployment_name
        ].reset_index(drop=True)

        self.assertEqual(filtered_model_deployment_list.shape[0], 1)
        self.assertEqual(filtered_model_deployment_list["MODEL_NAME"][0], second=model_name)
        self.assertEqual(filtered_model_deployment_list["MODEL_VERSION"][0], second=model_version)
        self.assertEqual(filtered_model_deployment_list["STAGE_PATH"][0], second=self.perm_stage)

        self.assertEqual(
            self._session.sql(
                f"SHOW USER FUNCTIONS LIKE '%{custom_permanent_deployment_name}' IN DATABASE \"{self.registry_name}\";"
            ).count(),
            1,
        )

        model_ref.delete_deployment(deployment_name=custom_permanent_deployment_name)  # type: ignore[attr-defined]

        model_deployment_list = model_ref.list_deployments().to_pandas()  # type: ignore[attr-defined]
        self.assertEqual(model_deployment_list.shape[0], 1)
        self.assertEqual(model_deployment_list["MODEL_NAME"][0], second=model_name)
        self.assertEqual(model_deployment_list["MODEL_VERSION"][0], second=model_version)
        self.assertEqual(model_deployment_list["DEPLOYMENT_NAME"][0], second=permanent_deployment_name)

        self.assertEqual(
            self._session.sql(
                f"SHOW USER FUNCTIONS LIKE '%{custom_permanent_deployment_name}' IN DATABASE \"{self.registry_name}\";"
            ).count(),
            0,
        )

        # Test temp deployment
        temp_deployment_name = f"{model_name}_{model_version}_temp_deploy"
        model_ref.deploy(  # type: ignore[attr-defined]
            deployment_name=temp_deployment_name,
            target_method="predict",
            permanent=False,
            options={"relax_version": test_env_utils.is_in_pip_env()},
        )
        remote_prediction_temp = model_ref.predict(temp_deployment_name, test_features)
        np.testing.assert_allclose(remote_prediction_temp.to_numpy(), np.expand_dims(local_prediction, axis=1))

        model_history = model_ref.get_model_history().to_pandas()  # type: ignore[attr-defined]
        self.assertEqual(model_history.shape[0], 16)

        registry.delete_model(model_name=model_name, model_version=model_version, delete_artifact=True)
        model_list = registry.list_models().to_pandas()
        filtered_model_list = model_list.loc[model_list["ID"] == model_ref._id].reset_index(drop=True)
        self.assertEqual(filtered_model_list.shape[0], 0)

    @pytest.mark.pip_incompatible
    def test_snowml_model(self) -> None:
        registry = model_registry.ModelRegistry(session=self._session, database_name=self.registry_name)

        model_name = "snowml_xgb_classifier"
        model_version = self.run_id
        model, test_features, _ = model_factory.ModelFactory.prepare_snowml_model_xgb()

        local_prediction = model.predict(test_features)
        local_prediction_proba = model.predict_proba(test_features)

        registry.log_model(
            model_name=model_name,
            model_version=model_version,
            model=model,
            conda_dependencies=[
                test_env_utils.get_latest_package_versions_in_server(self._session, "snowflake-snowpark-python")
            ],
            options={"embed_local_ml_library": True},
        )

        model_ref = model_registry.ModelReference(registry=registry, model_name=model_name, model_version=model_version)

        restored_model = model_ref.load_model()  # type: ignore[attr-defined]
        restored_prediction = restored_model.predict(test_features)
        pd.testing.assert_frame_equal(local_prediction, restored_prediction)

        temp_predict_deployment_name = f"{model_name}_{model_version}_predict_temp_deploy"
        model_ref.deploy(  # type: ignore[attr-defined]
            deployment_name=temp_predict_deployment_name,
            target_method="predict",
            permanent=False,
        )
        remote_prediction_temp = model_ref.predict(temp_predict_deployment_name, test_features)

        # TODO: Remove check_dtype=False after SNOW-853634 gets fixed.
        pd.testing.assert_frame_equal(remote_prediction_temp, local_prediction, check_dtype=False)

        temp_predict_proba_deployment_name = f"{model_name}_{model_version}_predict_proba_temp_deploy"
        model_ref.deploy(  # type: ignore[attr-defined]
            deployment_name=temp_predict_proba_deployment_name,
            target_method="predict_proba",
            permanent=False,
        )
        remote_prediction_proba_temp = model_ref.predict(temp_predict_proba_deployment_name, test_features)
        # TODO: Remove check_dtype=False after SNOW-853634 gets fixed.
        pd.testing.assert_frame_equal(remote_prediction_proba_temp, local_prediction_proba, check_dtype=False)

        registry.delete_model(model_name=model_name, model_version=model_version, delete_artifact=True)

    @pytest.mark.pip_incompatible
    def test_snowml_pipeline(self) -> None:
        registry = model_registry.ModelRegistry(session=self._session, database_name=self.registry_name)

        model_name = "snowml_pipeline"
        model_version = self.run_id
        model, test_features = model_factory.ModelFactory.prepare_snowml_pipeline(self._session)

        local_prediction = model.predict(test_features)

        registry.log_model(
            model_name=model_name,
            model_version=model_version,
            model=model,
            conda_dependencies=[
                test_env_utils.get_latest_package_versions_in_server(self._session, "snowflake-snowpark-python")
            ],
            options={"embed_local_ml_library": True},
        )

        model_ref = model_registry.ModelReference(registry=registry, model_name=model_name, model_version=model_version)

        restored_model = model_ref.load_model()  # type: ignore[attr-defined]
        restored_prediction = restored_model.predict(test_features)
        pd.testing.assert_frame_equal(local_prediction.to_pandas(), restored_prediction.to_pandas())

        temp_predict_deployment_name = f"{model_name}_{model_version}_predict_temp_deploy"
        model_ref.deploy(  # type: ignore[attr-defined]
            deployment_name=temp_predict_deployment_name,
            target_method="predict",
            permanent=False,
        )
        remote_prediction_temp = model_ref.predict(temp_predict_deployment_name, test_features.to_pandas())
        # TODO: Remove .astype(dtype={"OUTPUT_TARGET": np.float64} after SNOW-853638 gets fixed.
        pd.testing.assert_frame_equal(
            remote_prediction_temp,
            local_prediction.to_pandas().astype(dtype={"OUTPUT_TARGET": np.float64}),
        )

    @pytest.mark.pip_incompatible
    def test_log_model_with_traing_dataset(self) -> None:
        registry = model_registry.ModelRegistry(session=self._session, database_name=self.registry_name)

        model_name = "snowml_test_training_dataset"
        model_version = self.run_id
        model, test_features, training_data_df = model_factory.ModelFactory.prepare_snowml_model_xgb()

        database_name = identifier.get_unescaped_names(self._session.get_current_database())
        schema_name = identifier.get_unescaped_names(self._session.get_current_schema())
        dummy_materialized_table_full_path = f"{database_name}.{schema_name}.dummy_materialized_table"
        dummy_snapshot_table_full_path = f"{dummy_materialized_table_full_path}_SNAPSHOT"
        self._session.create_dataframe(training_data_df).write.mode("overwrite").save_as_table(
            f"{dummy_snapshot_table_full_path}"
        )

        spine_query = f"SELECT * FROM {dummy_materialized_table_full_path}"

        fs_metadata = training_dataset.FeatureStoreMetadata(
            spine_query=spine_query,
            connection_params={
                "database": "test_db",
                "schema": "test_schema",
                "default_warehouse": "test_warehouse",
            },
            features=[],
        )
        dummy_training_dataset = training_dataset.TrainingDataset(
            df=self._session.sql(spine_query),
            materialized_table=dummy_materialized_table_full_path,
            snapshot_table=dummy_snapshot_table_full_path,
            timestamp_col="ts",
            label_cols=["TARGET"],
            feature_store_metadata=fs_metadata,
            desc="a dummy training dataset metadata",
        )

        with self.assertRaisesRegex(
            ValueError,
            "Only one of sample_input_data and training_dataset should be provided.",
        ):
            registry.log_model(
                model_name=model_name,
                model_version=model_version,
                model=model,
                conda_dependencies=[
                    test_env_utils.get_latest_package_versions_in_server(self._session, "snowflake-snowpark-python")
                ],
                sample_input_data=test_features,
                training_dataset=dummy_training_dataset,
                options={"embed_local_ml_library": True},
            )

        registry.log_model(
            model_name=model_name,
            model_version=model_version,
            model=model,
            conda_dependencies=[
                test_env_utils.get_latest_package_versions_in_server(self._session, "snowflake-snowpark-python")
            ],
            options={"embed_local_ml_library": True},
            training_dataset=dummy_training_dataset,
        )

        # test deserialized training dataset from get_training_dataset
        des_ds_0 = registry.get_training_dataset(model_name, model_version)
        self.assertIsNotNone(des_ds_0)
        self.assertEqual(des_ds_0, dummy_training_dataset)

        # test deserialized training dataset from list_artifacts
        rows_list = registry.list_artifacts(model_name, model_version).collect()
        self.assertEqual(len(rows_list), 1)
        self.assertEqual(rows_list[0]["ID"], dummy_training_dataset.id())
        self.assertEqual(_ml_artifact.ArtifactType[rows_list[0]["TYPE"]], _ml_artifact.ArtifactType.TRAINING_DATASET)
        des_ds_1 = training_dataset.TrainingDataset.from_json(rows_list[0]["ARTIFACT_SPEC"], self._session)
        self.assertEqual(des_ds_1, dummy_training_dataset)


if __name__ == "__main__":
    absltest.main()
