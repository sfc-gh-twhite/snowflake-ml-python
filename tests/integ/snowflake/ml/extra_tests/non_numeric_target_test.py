import inflection
import numpy as np
import pytest
from absl.testing.absltest import TestCase, main
from sklearn.datasets import load_iris
from sklearn.ensemble import RandomForestClassifier as SkRandomForestClassifier

from snowflake.ml.modeling.ensemble import RandomForestClassifier
from snowflake.ml.utils.connection_params import SnowflakeLoginOptions
from snowflake.snowpark import Session


@pytest.mark.pip_incompatible
class NonNumericTargetTest(TestCase):
    def setUp(self):
        """Creates Snowpark and Snowflake environments for testing."""
        self._session = Session.builder.configs(SnowflakeLoginOptions()).create()

    def tearDown(self):
        self._session.close()

    def test_fit_and_compare_results(self) -> None:
        data = load_iris(as_frame=True)
        input_df_pandas = data.frame

        input_df_pandas.columns = [inflection.parameterize(c, "_").upper() for c in input_df_pandas.columns]

        # Coerce target column to string.
        input_df_pandas["TARGET"] = input_df_pandas["TARGET"].apply(lambda x: data.target_names[x])
        input_cols = [c for c in input_df_pandas.columns if not c.startswith("TARGET")]
        label_col = [c for c in input_df_pandas.columns if c.startswith("TARGET")]
        input_df_pandas["INDEX"] = input_df_pandas.reset_index().index
        input_df = self._session.create_dataframe(input_df_pandas)

        sklearn_reg = SkRandomForestClassifier(random_state=0)

        reg = RandomForestClassifier(random_state=0)
        reg.set_input_cols(input_cols)
        output_cols = ["OUTPUT_" + c for c in label_col]
        reg.set_output_cols(output_cols)
        reg.set_label_cols(label_col)

        reg.fit(input_df)
        sklearn_reg.fit(X=input_df_pandas[input_cols], y=input_df_pandas[label_col].squeeze())

        actual_arr = reg.predict(input_df).to_pandas().sort_values(by="INDEX")[output_cols].to_numpy()
        sklearn_numpy_arr = sklearn_reg.predict(input_df_pandas[input_cols])

        np.testing.assert_equal(actual_arr.flatten(), sklearn_numpy_arr.flatten())


if __name__ == "__main__":
    main()
