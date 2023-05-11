from abc import ABC, abstractmethod
from typing import Generic, Optional

from snowflake.ml.model import _model_meta, type_hints as model_types


class _ModelHandler(ABC, Generic[model_types.ModelType]):
    """Provides handling for a given type of model defined by `type` class property."""

    handler_type = "_base"
    MODEL_BLOB_FILE = "model.pkl"
    MODEL_ARTIFACTS_DIR = "artifacts"
    DEFAULT_TARGET_METHODS = ["predict"]

    @staticmethod
    @abstractmethod
    def can_handle(model: model_types.SupportedModelType) -> bool:
        """Whether this handler could support the type of the `model`.

        Args:
            model: The model object.
        """
        ...

    @staticmethod
    @abstractmethod
    def cast_model(model: model_types.SupportedModelType) -> model_types.ModelType:
        """Cast the model from Union type into the type that handler could handle.

        Args:
            model: The model object.
        """
        ...

    @staticmethod
    @abstractmethod
    def _save_model(
        name: str,
        model: model_types.ModelType,
        model_meta: _model_meta.ModelMetadata,
        model_blobs_dir_path: str,
        sample_input: Optional[model_types.SupportedDataType] = None,
        is_sub_model: Optional[bool] = False,
    ) -> None:
        """Save the model.

        Args:
            name: Name of the model.
            model: The model object.
            model_meta: The model metadata.
            model_blobs_dir_path: Directory path to the model.
            sample_input: Sample input to infer the signatures from.
            is_sub_model: Flag to show if it is a sub model, a sub model does not need signature.
        """
        ...

    @staticmethod
    @abstractmethod
    def _load_model(
        name: str, model_meta: _model_meta.ModelMetadata, model_blobs_dir_path: str
    ) -> model_types.ModelType:
        """Load the model into memory.

        Args:
            name: Name of the model.
            model_meta: The model metadata.
            model_blobs_dir_path: Directory path to the whole model.
        """
        ...
