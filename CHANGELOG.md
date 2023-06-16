# Release History

## 1.0.1 (2023-06-16)
### Behavior Changes

- Model Development: Changed Metrics APIs to imitate sklearn metrics modules:
  - `accuracy_score()`, `confusion_matrix()`, `precision_recall_fscore_support()`, `precision_score()` methods move from respective modules to `metrics.classification`.
- Model Registry: The dafault table/stage created by the Registry now uses "_SYSTEM_" as a prefix.
- Model Registry: `get_model_history()` method as been enhanced to include the history of model deployment.

### New Features

- Model Registry: A default `False` flag named `replace_udf` has been added to the options of `deploy()`. Setting this to `True` will allow overwrite existing UDF with the same name when deploying.
- Model Development: Added metrics:
  - f1_score
  - fbeta_score
  - recall_score
  - roc_auc_score
  - roc_curve
  - log_loss
  - precision_recall_curve
- Model Registry: A new argument named `permanent` has been added to the arguemnt of `deploy()`. Setting this to `True` allows the creation of a permanent deployment without needing to specify the UDF location.
- Model Registry: A new method `list_deployments()` has been added to enumerate all permanent deployments originating from a specific model.
- Model Registry: A new method `get_deployment()` has been added to fetch a deployment by its deployment name.
- Model Registry: A new method `delete_deployment()` has been added to remove an existing permanent deployment.

## 1.0.0 (2023-06-09)

### Behavior Changes

- Model Registry: `predict()` method moves from Registry to ModelReference.
- Model Registry: `_snowml_wheel_path` parameter in options of `deploy()`, is replaced with `_use_local_snowml` with default value of `False`. Setting this to `True` will have the same effect of uploading local SnowML code when executing model in the warehouse.
- Model Registry: Removed `id` field from `ModelReference` constructor.
- Model Development: Preprocessing and Metrics move to the modeling package: `snowflake.ml.modeling.preprocessing` and `snowflake.ml.modeling.metrics`.
- Model Development: `get_sklearn_object()` method is renamed to `to_sklearn()`, `to_xgboost()`, and `to_lightgbm()` for respective native models.

### New Features

- Added PolynomialFeatures transformer to the snowflake.ml.modeling.preprocessing module.
- Added metrics:
  - accuracy_score
  - confusion_matrix
  - precision_recall_fscore_support
  - precision_score

### Bug Fixes

- Model Registry: Model version can now be any string (not required to be a valid identifier)
- Model Deployment: `deploy()` & `predict()` methods now correctly escapes identifiers

## 0.3.2 (2023-05-23)

### Behavior Changes

- Use cloudpickle to serialize and deserialize models throughout the codebase and removed dependency on joblib.

### New Features

- Model Deployment: Added support for snowflake.ml models.

## 0.3.1 (2023-05-18)

### Behavior Changes

- Standardized registry API with following
  - Create & open registry taking same set of arguments
  - Create & Open can choose schema to use
  - Set_tag, set_metric, etc now explicitly calls out arg name as metric_name, tag_name, metric_name, etc.

### New Features

- Changes to support python 3.9, 3.10
- Added kBinsDiscretizer
- Support for deployment of XGBoost models & int8 types of data

## 0.3.0 (2023-05-11)

### Behavior Changes

- Big Model Registry Refresh
  - Fixed API discrepancies between register_model & log_model.
  - Model can be referred by Name + Version (no opaque internal id is required)

### New Features

- Model Registry: Added support save/load/deploy SKL & XGB Models

## 0.2.3 (2023-04-27)

### Bug Fixes

- Allow using OneHotEncoder along with sklearn style estimators in a pipeline.

### New Features

- Model Registry: Added support for delete_model. Use delete_artifact = False to not delete the underlying model data but just unregister.

## 0.2.2 (2023-04-11)

### New Features

- Initial version of snowflake-ml modeling package.
  - Provide support for training most of scikit-learn and xgboost estimators and transformers.

### Bug Fixes

- Minor fixes in preprocessing package.

## 0.2.1 (2023-03-23)

### New Features

- New in Preprocessing:
  - SimpleImputer
  - Covariance Matrix
- Optimization of Ordinal Encoder client computations.

### Bug Fixes

- Minor fixes in OneHotEncoder.

## 0.2.0 (2023-02-27)

### New Features

- Model Registry
- PyTorch & Tensorflow connector file generic FileSet API
- New to Preprocessing:
  - Binarizer
  - Normalizer
  - Pearson correlation Matrix
- Optimization in Ordinal Encoder to cache vocabulary in temp tables.

## 0.1.3 (2023-02-02)

### New Features

- Initial version of transformers including:
  - Label Encoder
  - Max Abs Scaler
  - Min Max Scaler
  - One Hot Encoder
  - Ordinal Encoder
  - Robust Scaler
  - Standard Scaler
