import inflection
import numpy as np
import pytest
from absl.testing.absltest import TestCase, main
from sklearn.datasets import load_diabetes, load_iris
from sklearn.model_selection import GridSearchCV as SkGridSearchCV
from sklearn.svm import SVR as SkSVR
from xgboost import XGBClassifier as SkXGBClassifier

from snowflake.ml.modeling.model_selection._internal import GridSearchCV
from snowflake.ml.modeling.svm import SVR
from snowflake.ml.modeling.xgboost import XGBClassifier
from snowflake.ml.utils.connection_params import SnowflakeLoginOptions
from snowflake.snowpark import Session


@pytest.mark.pip_incompatible
class GridSearchCVTest(TestCase):
    def setUp(self):
        """Creates Snowpark and Snowflake environments for testing."""
        self._session = Session.builder.configs(SnowflakeLoginOptions()).create()

    def tearDown(self):
        self._session.close()

    def _compare_cv_results(self, cv_result_1, cv_result_2) -> None:
        # compare the keys
        self.assertEqual(cv_result_1.keys(), cv_result_2.keys())
        # compare the values
        for k, v in cv_result_1.items():
            if isinstance(v, np.ndarray):
                if k.startswith("param_"):  # compare the masked array
                    np.ma.allequal(v, cv_result_2[k])
                elif k == "params":  # compare the parameter combination
                    self.assertEqual(v.tolist(), cv_result_2[k])
                elif k.endswith("test_score"):  # compare the test score
                    np.testing.assert_allclose(v, cv_result_2[k], rtol=1.0e-1, atol=1.0e-2)
                # Do not compare the fit time

    def test_fit_and_compare_results(self) -> None:
        input_df_pandas = load_diabetes(as_frame=True).frame
        input_df_pandas.columns = [inflection.parameterize(c, "_").upper() for c in input_df_pandas.columns]
        input_cols = [c for c in input_df_pandas.columns if not c.startswith("TARGET")]
        label_col = [c for c in input_df_pandas.columns if c.startswith("TARGET")]
        input_df_pandas["INDEX"] = input_df_pandas.reset_index().index
        input_df = self._session.create_dataframe(input_df_pandas)

        sklearn_reg = SkGridSearchCV(estimator=SkSVR(), param_grid={"C": [1, 10], "kernel": ("linear", "rbf")})
        reg = GridSearchCV(estimator=SVR(), param_grid={"C": [1, 10], "kernel": ("linear", "rbf")})
        reg.set_input_cols(input_cols)
        output_cols = ["OUTPUT_" + c for c in label_col]
        reg.set_output_cols(output_cols)
        reg.set_label_cols(label_col)

        reg.fit(input_df)
        sklearn_reg.fit(X=input_df_pandas[input_cols], y=input_df_pandas[label_col].squeeze())

        actual_arr = reg.predict(input_df).to_pandas().sort_values(by="INDEX")[output_cols].to_numpy()
        sklearn_numpy_arr = sklearn_reg.predict(input_df_pandas[input_cols])

        assert reg._sklearn_object.best_params_ == sklearn_reg.best_params_
        np.testing.assert_allclose(reg._sklearn_object.best_score_, sklearn_reg.best_score_)
        self._compare_cv_results(reg._sklearn_object.cv_results_, sklearn_reg.cv_results_)

        np.testing.assert_allclose(actual_arr.flatten(), sklearn_numpy_arr.flatten(), rtol=1.0e-1, atol=1.0e-2)

    def test_fit_xgboost(self) -> None:
        input_df_pandas = load_iris(as_frame=True).frame
        input_df_pandas.columns = [inflection.parameterize(c, "_").upper() for c in input_df_pandas.columns]
        input_cols = [c for c in input_df_pandas.columns if not c.startswith("TARGET")]
        label_col = [c for c in input_df_pandas.columns if c.startswith("TARGET")]
        input_df_pandas["INDEX"] = input_df_pandas.reset_index().index
        input_df = self._session.create_dataframe(input_df_pandas)

        sk_estimator = SkXGBClassifier(seed=42, n_jobs=1)
        parameters = {
            "max_depth": range(2, 6, 1),
            "learning_rate": [0.1, 0.01],
        }
        sklearn_reg = SkGridSearchCV(estimator=sk_estimator, param_grid=parameters, verbose=True)
        sklearn_reg.fit(X=input_df_pandas[input_cols], y=input_df_pandas[label_col].squeeze())

        estimator = XGBClassifier(seed=42, n_jobs=1)
        reg = GridSearchCV(estimator=estimator, param_grid=parameters, verbose=True)
        reg.set_input_cols(input_cols)
        output_cols = ["OUTPUT_" + c for c in label_col]
        reg.set_output_cols(output_cols)
        reg.set_label_cols(label_col)
        reg.fit(input_df)

        actual_arr = reg.predict(input_df).to_pandas().sort_values(by="INDEX")[output_cols].to_numpy()
        sklearn_numpy_arr = sklearn_reg.predict(input_df_pandas[input_cols])

        np.testing.assert_allclose(reg._sklearn_object.best_score_, sklearn_reg.best_score_)
        self._compare_cv_results(reg._sklearn_object.cv_results_, sklearn_reg.cv_results_)
        np.testing.assert_allclose(actual_arr.flatten(), sklearn_numpy_arr.flatten(), rtol=1.0e-1, atol=1.0e-2)


if __name__ == "__main__":
    main()
