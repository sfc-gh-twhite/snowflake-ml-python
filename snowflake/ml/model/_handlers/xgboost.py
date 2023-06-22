# mypy: disable-error-code="import"
import os
from typing import TYPE_CHECKING, Callable, Optional, Sequence, Type, Union

import numpy as np
import pandas as pd
from typing_extensions import TypeGuard, Unpack

from snowflake.ml._internal import type_utils
from snowflake.ml.model import (
    _model_meta as model_meta_api,
    custom_model,
    type_hints as model_types,
)
from snowflake.ml.model._handlers import _base

if TYPE_CHECKING:
    import xgboost


class _XGBModelHandler(_base._ModelHandler[Union["xgboost.Booster", "xgboost.XGBModel"]]):
    """Handler for XGBoost based model.

    Currently xgboost.XGBModel based classes are supported.
    """

    handler_type = "xgboost"
    MODEL_BLOB_FILE = "model.ubj"
    DEFAULT_TARGET_METHODS = ["apply", "predict", "predict_proba"]

    @staticmethod
    def can_handle(model: model_types.SupportedModelType) -> TypeGuard[Union["xgboost.Booster", "xgboost.XGBModel"]]:
        return (
            type_utils.LazyType("xgboost.Booster").isinstance(model)
            or type_utils.LazyType("xgboost.XGBModel").isinstance(model)
        ) and any(
            (hasattr(model, method) and callable(getattr(model, method, None)))
            for method in _XGBModelHandler.DEFAULT_TARGET_METHODS
        )

    @staticmethod
    def cast_model(
        model: model_types.SupportedModelType,
    ) -> Union["xgboost.Booster", "xgboost.XGBModel"]:
        import xgboost

        assert isinstance(model, xgboost.Booster) or isinstance(model, xgboost.XGBModel)

        return model

    @staticmethod
    def _save_model(
        name: str,
        model: Union["xgboost.Booster", "xgboost.XGBModel"],
        model_meta: model_meta_api.ModelMetadata,
        model_blobs_dir_path: str,
        sample_input: Optional[model_types.SupportedDataType] = None,
        is_sub_model: Optional[bool] = False,
        **kwargs: Unpack[model_types.XGBModelSaveOptions],
    ) -> None:
        import xgboost

        assert isinstance(model, xgboost.Booster) or isinstance(model, xgboost.XGBModel)

        if not is_sub_model:
            target_methods = model_meta_api._get_target_methods(
                model=model,
                target_methods=kwargs.pop("target_methods", None),
                default_target_methods=_XGBModelHandler.DEFAULT_TARGET_METHODS,
            )

            def get_prediction(
                target_method_name: str, sample_input: model_types.SupportedLocalDataType
            ) -> model_types.SupportedLocalDataType:
                target_method = getattr(model, target_method_name, None)
                assert callable(target_method)
                predictions_df = target_method(sample_input)
                return predictions_df

            model_meta = model_meta_api._validate_signature(
                model=model,
                model_meta=model_meta,
                target_methods=target_methods,
                sample_input=sample_input,
                get_prediction_fn=get_prediction,
            )

        model_blob_path = os.path.join(model_blobs_dir_path, name)
        os.makedirs(model_blob_path, exist_ok=True)
        model.save_model(os.path.join(model_blob_path, _XGBModelHandler.MODEL_BLOB_FILE))
        base_meta = model_meta_api._ModelBlobMetadata(
            name=name,
            model_type=_XGBModelHandler.handler_type,
            path=_XGBModelHandler.MODEL_BLOB_FILE,
            options={"xgb_estimator_type": model.__class__.__name__},
        )
        model_meta.models[name] = base_meta
        model_meta._include_if_absent([("scikit-learn", "scikit-learn"), ("xgboost", "xgboost")])

    @staticmethod
    def _load_model(
        name: str, model_meta: model_meta_api.ModelMetadata, model_blobs_dir_path: str
    ) -> Union["xgboost.Booster", "xgboost.XGBModel"]:
        import xgboost

        model_blob_path = os.path.join(model_blobs_dir_path, name)
        if not hasattr(model_meta, "models"):
            raise ValueError("Ill model metadata found.")
        model_blobs_metadata = model_meta.models
        if name not in model_blobs_metadata:
            raise ValueError(f"Blob of model {name} does not exist.")
        model_blob_metadata = model_blobs_metadata[name]
        model_blob_filename = model_blob_metadata.path
        xgb_estimator_type = model_blob_metadata.options.get("xgb_estimator_type", None)
        if not xgb_estimator_type or not hasattr(xgboost, xgb_estimator_type):
            raise ValueError("Type of XGB estimator unknown or illegal.")
        m = getattr(xgboost, xgb_estimator_type)()

        assert isinstance(m, xgboost.Booster) or isinstance(m, xgboost.XGBModel)
        m.load_model(os.path.join(model_blob_path, model_blob_filename))
        return m

    @staticmethod
    def _load_as_custom_model(
        name: str, model_meta: model_meta_api.ModelMetadata, model_blobs_dir_path: str
    ) -> custom_model.CustomModel:
        """Create a custom model class wrap for unified interface when being deployed. The predict method will be
        re-targeted based on target_method metadata.

        Args:
            name: Name of the model.
            model_meta: The model metadata.
            model_blobs_dir_path: Directory path to the whole model.

        Returns:
            The model object as a custom model.
        """
        from snowflake.ml.model import custom_model

        def _create_custom_model(
            raw_model: Union["xgboost.Booster", "xgboost.XGBModel"],
            model_meta: model_meta_api.ModelMetadata,
        ) -> Type[custom_model.CustomModel]:
            def fn_factory(
                raw_model: Union["xgboost.Booster", "xgboost.XGBModel"],
                output_col_names: Sequence[str],
                target_method: str,
            ) -> Callable[[custom_model.CustomModel, pd.DataFrame], pd.DataFrame]:
                @custom_model.inference_api
                def fn(self: custom_model.CustomModel, X: pd.DataFrame) -> pd.DataFrame:
                    res = getattr(raw_model, target_method)(X)

                    if isinstance(res, list) and len(res) > 0 and isinstance(res[0], np.ndarray):
                        # In case of multi-output estimators, predict_proba(), decision_function(), etc., functions
                        # return a list of ndarrays. We need to concatenate them.
                        res = np.concatenate(res, axis=1)
                    return pd.DataFrame(res, columns=output_col_names)

                return fn

            type_method_dict = {}
            for target_method_name, sig in model_meta.signatures.items():
                type_method_dict[target_method_name] = fn_factory(
                    raw_model, [spec.name for spec in sig.outputs], target_method_name
                )

            _XGBModel = type(
                "_XGBModel",
                (custom_model.CustomModel,),
                type_method_dict,
            )

            return _XGBModel

        raw_model = _XGBModelHandler._load_model(name, model_meta, model_blobs_dir_path)
        _XGBModel = _create_custom_model(raw_model, model_meta)
        xgb_model = _XGBModel(custom_model.ModelContext())

        return xgb_model
