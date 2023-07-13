#
# Copyright (c) 2012-2022 Snowflake Computing Inc. All rights reserved.
#

import uuid
from typing import Any, Callable, Dict, Optional, Tuple, Union, cast

import numpy as np
import pandas as pd
import xgboost
from absl.testing import absltest, parameterized
from sklearn import datasets, ensemble, linear_model, model_selection, multioutput

from snowflake.ml.model import type_hints as model_types
from snowflake.ml.utils import connection_params
from snowflake.snowpark import DataFrame as SnowparkDataFrame, Session
from tests.integ.snowflake.ml.model import warehouse_model_integ_test_utils
from tests.integ.snowflake.ml.test_utils import db_manager


class TestWarehouseSKLearnXGBoostModelInteg(parameterized.TestCase):
    @classmethod
    def setUpClass(self) -> None:
        """Creates Snowpark and Snowflake environments for testing."""
        self._session = Session.builder.configs(connection_params.SnowflakeLoginOptions()).create()

        self._db_manager = db_manager.DBManager(self._session)
        self._db_manager.cleanup_schemas()
        self._db_manager.cleanup_stages()
        self._db_manager.cleanup_user_functions()

        # To create different UDF names among different runs
        self.run_id = uuid.uuid4().hex
        self._test_schema_name = db_manager.TestObjectNameGenerator.get_snowml_test_object_name(
            self.run_id, "model_deployment_sklearn_xgboost_model_test_schema"
        )
        self._db_manager.create_schema(self._test_schema_name)
        self._db_manager.use_schema(self._test_schema_name)

        self.deploy_stage_name = db_manager.TestObjectNameGenerator.get_snowml_test_object_name(
            self.run_id, "deployment_stage"
        )
        self.full_qual_stage = self._db_manager.create_stage(
            self.deploy_stage_name, schema_name=self._test_schema_name, sse_encrypted=False
        )

    @classmethod
    def tearDownClass(self) -> None:
        self._db_manager.drop_stage(self.deploy_stage_name, schema_name=self._test_schema_name)
        self._db_manager.drop_schema(self._test_schema_name)
        self._session.close()

    def base_test_case(
        self,
        name: str,
        model: model_types.SupportedModelType,
        sample_input: model_types.SupportedDataType,
        test_input: model_types.SupportedDataType,
        deploy_params: Dict[str, Tuple[Dict[str, Any], Callable[[Union[pd.DataFrame, SnowparkDataFrame]], Any]]],
        model_in_stage: Optional[bool] = False,
        permanent_deploy: Optional[bool] = False,
        test_released_library: Optional[bool] = False,
    ) -> None:
        warehouse_model_integ_test_utils.base_test_case(
            self._db_manager,
            run_id=self.run_id,
            full_qual_stage=self.full_qual_stage,
            name=name,
            model=model,
            sample_input=sample_input,
            test_input=test_input,
            deploy_params=deploy_params,
            model_in_stage=model_in_stage,
            permanent_deploy=permanent_deploy,
            test_released_library=test_released_library,
        )

    @parameterized.parameters(  # type: ignore[misc]
        {"model_in_stage": True, "permanent_deploy": True, "test_released_library": False},
        {"model_in_stage": False, "permanent_deploy": False, "test_released_library": False},
        # {"model_in_stage": True, "permanent_deploy": False, "test_released_library": True},
        # {"model_in_stage": False, "permanent_deploy": True, "test_released_library": True},
    )
    def test_skl_model_deploy(
        self,
        model_in_stage: Optional[bool] = False,
        permanent_deploy: Optional[bool] = False,
        test_released_library: Optional[bool] = False,
    ) -> None:
        iris_X, iris_y = datasets.load_iris(return_X_y=True)
        # LogisticRegression is for classfication task, such as iris
        regr = linear_model.LogisticRegression()
        regr.fit(iris_X, iris_y)
        self.base_test_case(
            name="skl_model",
            model=regr,
            sample_input=iris_X,
            test_input=iris_X,
            deploy_params={
                "predict": (
                    {},
                    lambda res: np.testing.assert_allclose(res["output_feature_0"].values, regr.predict(iris_X)),
                ),
            },
            model_in_stage=model_in_stage,
            permanent_deploy=permanent_deploy,
            test_released_library=test_released_library,
        )

    @parameterized.parameters(  # type: ignore[misc]
        {"model_in_stage": True, "permanent_deploy": True, "test_released_library": False},
        {"model_in_stage": False, "permanent_deploy": False, "test_released_library": False},
        # {"model_in_stage": True, "permanent_deploy": False, "test_released_library": True},
        # {"model_in_stage": False, "permanent_deploy": True, "test_released_library": True},
    )
    def test_skl_model_proba_deploy(
        self,
        model_in_stage: Optional[bool] = False,
        permanent_deploy: Optional[bool] = False,
        test_released_library: Optional[bool] = False,
    ) -> None:
        iris_X, iris_y = datasets.load_iris(return_X_y=True)
        model = ensemble.RandomForestClassifier(random_state=42)
        model.fit(iris_X[:10], iris_y[:10])
        self.base_test_case(
            name="skl_model_proba_deploy",
            model=model,
            sample_input=iris_X,
            test_input=iris_X[:10],
            deploy_params={
                "predict": (
                    {},
                    lambda res: np.testing.assert_allclose(res["output_feature_0"].values, model.predict(iris_X[:10])),
                ),
                "predict_proba": (
                    {},
                    lambda res: np.testing.assert_allclose(res.values, model.predict_proba(iris_X[:10])),
                ),
            },
            model_in_stage=model_in_stage,
            permanent_deploy=permanent_deploy,
            test_released_library=test_released_library,
        )

    @parameterized.parameters(  # type: ignore[misc]
        {"model_in_stage": True, "permanent_deploy": True, "test_released_library": False},
        {"model_in_stage": False, "permanent_deploy": False, "test_released_library": False},
        # {"model_in_stage": True, "permanent_deploy": False, "test_released_library": True},
        # {"model_in_stage": False, "permanent_deploy": True, "test_released_library": True},
    )
    def test_skl_multiple_output_model_proba_deploy(
        self,
        model_in_stage: Optional[bool] = False,
        permanent_deploy: Optional[bool] = False,
        test_released_library: Optional[bool] = False,
    ) -> None:
        iris_X, iris_y = datasets.load_iris(return_X_y=True)
        target2 = np.random.randint(0, 6, size=iris_y.shape)
        dual_target = np.vstack([iris_y, target2]).T
        model = multioutput.MultiOutputClassifier(ensemble.RandomForestClassifier(random_state=42))
        model.fit(iris_X[:10], dual_target[:10])
        self.base_test_case(
            name="skl_multiple_output_model_proba",
            model=model,
            sample_input=iris_X,
            test_input=iris_X[-10:],
            deploy_params={
                "predict": (
                    {},
                    lambda res: np.testing.assert_allclose(res.to_numpy(), model.predict(iris_X[-10:])),
                ),
                "predict_proba": (
                    {},
                    lambda res: np.testing.assert_allclose(
                        np.hstack([np.array(res[col].to_list()) for col in cast(pd.DataFrame, res)]),
                        np.hstack(model.predict_proba(iris_X[-10:])),
                    ),
                ),
            },
            model_in_stage=model_in_stage,
            permanent_deploy=permanent_deploy,
            test_released_library=test_released_library,
        )

    @parameterized.parameters(  # type: ignore[misc]
        {"model_in_stage": True, "permanent_deploy": True, "test_released_library": False},
        {"model_in_stage": False, "permanent_deploy": False, "test_released_library": False},
        # {"model_in_stage": True, "permanent_deploy": False, "test_released_library": True},
        # {"model_in_stage": False, "permanent_deploy": True, "test_released_library": True},
    )
    def test_xgb(
        self,
        model_in_stage: Optional[bool] = False,
        permanent_deploy: Optional[bool] = False,
        test_released_library: Optional[bool] = False,
    ) -> None:
        cal_data = datasets.load_breast_cancer(as_frame=True)
        cal_X = cal_data.data
        cal_y = cal_data.target
        cal_X_train, cal_X_test, cal_y_train, cal_y_test = model_selection.train_test_split(cal_X, cal_y)
        regressor = xgboost.XGBRegressor(n_estimators=100, reg_lambda=1, gamma=0, max_depth=3)
        regressor.fit(cal_X_train, cal_y_train)
        self.base_test_case(
            name="xgb_model",
            model=regressor,
            sample_input=cal_X_test,
            test_input=cal_X_test,
            deploy_params={
                "predict": (
                    {},
                    lambda res: np.testing.assert_allclose(
                        res.values, np.expand_dims(regressor.predict(cal_X_test), axis=1)
                    ),
                ),
            },
            model_in_stage=model_in_stage,
            permanent_deploy=permanent_deploy,
            test_released_library=test_released_library,
        )

    @parameterized.parameters(  # type: ignore[misc]
        {"model_in_stage": True, "permanent_deploy": True, "test_released_library": False},
        {"model_in_stage": False, "permanent_deploy": False, "test_released_library": False},
        # {"model_in_stage": True, "permanent_deploy": False, "test_released_library": True},
        # {"model_in_stage": False, "permanent_deploy": True, "test_released_library": True},
    )
    def test_xgb_sp(
        self,
        model_in_stage: Optional[bool] = False,
        permanent_deploy: Optional[bool] = False,
        test_released_library: Optional[bool] = False,
    ) -> None:
        cal_data = datasets.load_breast_cancer(as_frame=True)
        cal_data_sp_df = self._session.create_dataframe(cal_data.frame)
        cal_data_sp_df_train, cal_data_sp_df_test = tuple(cal_data_sp_df.random_split([0.25, 0.75], seed=2568))
        regressor = xgboost.XGBRegressor(n_estimators=100, reg_lambda=1, gamma=0, max_depth=3)
        cal_data_pd_df_train = cal_data_sp_df_train.to_pandas()
        regressor.fit(cal_data_pd_df_train.drop(columns=["target"]), cal_data_pd_df_train["target"])
        cal_data_sp_df_test_X = cal_data_sp_df_test.drop('"target"')
        self.base_test_case(
            name="xgb_model_sp",
            model=regressor,
            sample_input=cal_data_sp_df_train.drop('"target"'),
            test_input=cal_data_sp_df_test_X,
            deploy_params={
                "predict": (
                    {},
                    lambda res: np.testing.assert_allclose(
                        res.to_pandas().values,
                        np.expand_dims(regressor.predict(cal_data_sp_df_test_X.to_pandas()), axis=1),
                    ),
                ),
            },
            model_in_stage=model_in_stage,
            permanent_deploy=permanent_deploy,
            test_released_library=test_released_library,
        )


if __name__ == "__main__":
    absltest.main()
