#!/usr/bin/env python3

import numpy as np
import pandas as pd
from absl.testing.absltest import TestCase, main

from snowflake.ml.modeling import metrics
from snowflake.ml.utils.connection_params import SnowflakeLoginOptions
from snowflake.snowpark import Row, Session


class CorrelationTest(TestCase):
    """Test Correlation matrix."""

    def setUp(self) -> None:
        """Creates Snowpark and Snowflake environments for testing."""
        self._session = Session.builder.configs(SnowflakeLoginOptions()).create()

    def tearDown(self) -> None:
        self._session.close()

    def test_with_string_and_numeric_cols(self) -> None:
        input_df = self._session.create_dataframe(
            [
                Row(-1.0, -1.5, "a"),
                Row(8.3, 7.6, "b"),
                Row(2.0, 2.5, "c"),
                Row(3.5, 4.7, "d"),
                Row(2.5, 1.5, "e"),
                Row(4.0, 3.8, "f"),
            ],
            schema=["COL1", "COL2", "COL3"],
        )

        corr_matrix = metrics.correlation(df=input_df).to_numpy()
        expected_corr_matrix = input_df.to_pandas().corr().to_numpy()
        assert np.allclose(corr_matrix, expected_corr_matrix)

    def test_with_nans(self) -> None:
        input_df = self._session.create_dataframe(
            [
                Row(-1.0, -1.5, 3.4, 1.4, 6.0),
                Row(8.3, 7.6, 2.3, 9.8, 4.5),
                Row(2.0, 2.5, 5.6, 2.4, 1.1),
                Row(3.5, 4.7, 0.4, 2.1, 3.8),
                Row(2.5, 1.5, 6.7, None, 9.1),
                Row(4.0, 3.8, 2.3, 5.5, np.NaN),
            ],
            schema=["COL1", "COL2", "COL3", "COL4", "COL5"],
        )

        corr_matrix = metrics.correlation(df=input_df).to_numpy()
        expected_corr_matrix = np.corrcoef(input_df.to_pandas().to_numpy(), rowvar=False)

        assert np.allclose(corr_matrix, expected_corr_matrix, equal_nan=True)

    def test_with_selected_cols(self) -> None:
        input_df = self._session.create_dataframe(
            [
                Row(-1.0, -1.5, 3.4, 1.4, 6.0),
                Row(8.3, 7.6, 2.3, 9.8, 4.5),
                Row(2.0, 2.5, 5.6, 2.4, 1.1),
                Row(3.5, 4.7, 0.4, 2.1, 3.8),
                Row(2.5, 1.5, 6.7, None, 9.1),
                Row(4.0, 3.8, 2.3, 5.5, np.NaN),
            ],
            schema=["col1", "col2", "col3", "col4", "col5"],
        )
        columns = ["col1", "col2", "col3"]

        corr_matrix = metrics.correlation(df=input_df, columns=columns).to_numpy()
        expected_corr_matrix = np.corrcoef(input_df.select(columns).to_pandas().to_numpy(), rowvar=False)

        assert np.allclose(corr_matrix, expected_corr_matrix)

    def test_with_large_num_of_cols(self) -> None:
        num_rows = 1000
        num_cols = 3000
        arr = np.random.rand(num_rows, num_cols)
        columns = []
        for i in range(num_cols):
            columns.append(f"COL_{i}")
        pddf = pd.DataFrame(arr, columns=columns)
        input_df = self._session.create_dataframe(pddf)

        corr_matrix = metrics.correlation(df=input_df).to_numpy()
        expected_corr_matrix = np.corrcoef(arr, rowvar=False)

        assert np.allclose(corr_matrix, expected_corr_matrix)

    def test_with_large_num_of_rows(self) -> None:
        num_rows = 100 * 1000 + 7  # add an offset to also test corner cases
        num_cols = 10
        arr = np.random.rand(num_rows, num_cols)
        columns = []
        for i in range(num_cols):
            columns.append(f"COL_{i}")
        pddf = pd.DataFrame(arr, columns=columns)
        input_df = self._session.create_dataframe(pddf)

        corr_matrix = metrics.correlation(df=input_df).to_numpy()
        expected_corr_matrix = np.corrcoef(arr, rowvar=False)

        assert np.allclose(corr_matrix, expected_corr_matrix)


if __name__ == "__main__":
    main()
