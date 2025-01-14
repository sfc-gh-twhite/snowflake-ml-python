#!/usr/bin/env python3
import sys

import numpy as np
from absl.testing.absltest import TestCase, main
from sklearn.preprocessing import KBinsDiscretizer as SklearnKBinsDiscretizer

from snowflake.ml.modeling.preprocessing import (
    KBinsDiscretizer,  # type: ignore[attr-defined]
)
from snowflake.ml.utils import sparse as sparse_utils
from snowflake.ml.utils.connection_params import SnowflakeLoginOptions
from snowflake.snowpark import Session
from tests.integ.snowflake.ml.modeling.framework import utils

np.set_printoptions(threshold=sys.maxsize)


class KBinsDiscretizerTest(TestCase):
    def setUp(self) -> None:
        self._session = Session.builder.configs(SnowflakeLoginOptions()).create()
        self._strategies = ["quantile", "uniform"]

    def tearDown(self) -> None:
        self._session.close()

    # TODO(tbao): just some small dev functions for fast iteration, remove later
    # def test_dummy(self) -> None:
    #     import pandas as pd
    #     data = {"COL1": [-3, 0, 6], "COL2": [5, 6, 3]}
    #     df = pd.DataFrame(data)

    #     k_bins_discretizer = KBinsDiscretizer(
    #         n_bins=[3, 2],
    #         encode="onehot-dense",
    #         strategy="uniform",
    #         input_cols=["COL1", "COL2"],
    #         output_cols=["OUTPUT1", "OUTPUT2"],
    #     )
    #     k_bins_discretizer.fit(df)
    #     print(f"bin_edges_: {k_bins_discretizer.bin_edges_}")
    #     print(f"n_bins_: {k_bins_discretizer.n_bins_}")

    #     df = k_bins_discretizer.transform(df)
    #     print(df)

    # def test_snowpark(self) -> None:
    #     df = self._session.create_dataframe([[-3, 5], [0, 6], [6, 3]], schema=["col1", "col2"])
    #     k_bins_discretizer = KBinsDiscretizer(
    #         n_bins=[3, 2],
    #         encode="onehot-dense",
    #         strategy="uniform",
    #         input_cols=["col1", "col2"],
    #         output_cols=["output1", "output2"],
    #     )
    #     k_bins_discretizer.fit(df)
    #     print(f"bin_edges_: {k_bins_discretizer.bin_edges_}")
    #     print(f"n_bins_: {k_bins_discretizer.n_bins_}")

    #     df = k_bins_discretizer.transform(df)
    #     print(df.show())

    def test_invalid_inputs(self) -> None:
        INPUT_COLS = utils.NUMERIC_COLS
        _, snowpark_df = utils.get_df(self._session, utils.DATA, utils.SCHEMA)

        # 1. Invalid n_bins
        with self.assertRaisesRegex(ValueError, "n_bins must have same size as input_cols"):
            discretizer = KBinsDiscretizer(
                n_bins=[3],
                encode="ordinal",
                input_cols=INPUT_COLS,
            )
            discretizer.fit(snowpark_df)

        with self.assertRaisesRegex(ValueError, "n_bins cannot be less than 2"):
            discretizer = KBinsDiscretizer(
                n_bins=[1, 3],
                encode="ordinal",
                input_cols=INPUT_COLS,
            )
            discretizer.fit(snowpark_df)

        # 2. Invalid encode
        with self.assertRaisesRegex(ValueError, "encode must be one of"):
            discretizer = KBinsDiscretizer(
                n_bins=[2, 3],
                encode="foo",
                input_cols=INPUT_COLS,
            )
            discretizer.fit(snowpark_df)

        # 3. Invalid strategy
        with self.assertRaisesRegex(ValueError, "strategy must be one of"):
            discretizer = KBinsDiscretizer(
                n_bins=[2, 3],
                strategy="foo",
                input_cols=INPUT_COLS,
            )
            discretizer.fit(snowpark_df)

    def test_fit(self) -> None:
        N_BINS = [3, 2]
        ENCODE = "ordinal"
        INPUT_COLS = utils.NUMERIC_COLS

        pandas_df, snowpark_df = utils.get_df(self._session, utils.DATA, utils.SCHEMA, np.nan)

        for strategy in self._strategies:
            sklearn_discretizer = SklearnKBinsDiscretizer(n_bins=N_BINS, encode=ENCODE, strategy=strategy)
            sklearn_discretizer.fit(pandas_df[INPUT_COLS])
            target_n_bins = sklearn_discretizer.n_bins_.tolist()
            target_bin_edges = sklearn_discretizer.bin_edges_.tolist()

            for df in [pandas_df, snowpark_df]:
                discretizer = KBinsDiscretizer(
                    n_bins=N_BINS,
                    encode=ENCODE,
                    strategy=strategy,
                    input_cols=INPUT_COLS,
                )
                discretizer.fit(df)
                actual_edges = discretizer.bin_edges_.tolist()

                np.testing.assert_equal(target_n_bins, discretizer.n_bins_.tolist())
                for i in range(len(target_bin_edges)):
                    np.testing.assert_allclose(target_bin_edges[i], actual_edges[i])

    def test_fit_fuzz_data(self) -> None:
        N_BINS = [10, 7]
        ENCODE = "ordinal"

        data, schema = utils.gen_fuzz_data(
            rows=1000,
            types=[utils.DataType.INTEGER, utils.DataType.FLOAT],
        )
        pandas_df, snowpark_df = utils.get_df(self._session, data, schema)

        for strategy in self._strategies:
            sklearn_discretizer = SklearnKBinsDiscretizer(n_bins=N_BINS, encode=ENCODE, strategy=strategy)
            sklearn_discretizer.fit(pandas_df[schema[1:]])
            target_n_bins = sklearn_discretizer.n_bins_.tolist()
            target_bin_edges = sklearn_discretizer.bin_edges_.tolist()

            for df in [pandas_df, snowpark_df]:
                discretizer = KBinsDiscretizer(
                    n_bins=N_BINS,
                    encode=ENCODE,
                    strategy=strategy,
                    input_cols=schema[1:],
                )
                discretizer.fit(df)
                actual_edges = discretizer.bin_edges_.tolist()

                np.testing.assert_allclose(target_n_bins, discretizer.n_bins_.tolist())
                for i in range(len(target_bin_edges)):
                    np.testing.assert_allclose(target_bin_edges[i], actual_edges[i])

    def test_transform_ordinal_encoding(self) -> None:
        N_BINS = [3, 2]
        ENCODE = "ordinal"
        INPUT_COLS, ID_COL, OUTPUT_COLS = (
            utils.NUMERIC_COLS,
            utils.ID_COL,
            utils.OUTPUT_COLS,
        )

        pandas_df, snowpark_df = utils.get_df(self._session, utils.DATA, utils.SCHEMA, np.nan)

        for strategy in self._strategies:
            # 1. Create OSS SKLearn discretizer
            sklearn_discretizer = SklearnKBinsDiscretizer(n_bins=N_BINS, encode=ENCODE, strategy=strategy)
            sklearn_discretizer.fit(pandas_df[INPUT_COLS])
            target_output = sklearn_discretizer.transform(pandas_df.sort_values(by=[ID_COL])[INPUT_COLS])

            # 2. Create SnowML discretizer
            discretizer = KBinsDiscretizer(
                n_bins=N_BINS,
                encode=ENCODE,
                strategy=strategy,
                input_cols=INPUT_COLS,
                output_cols=OUTPUT_COLS,
            )
            discretizer.fit(snowpark_df)

            # 3. Transform with Snowpark DF and compare
            actual_output = discretizer.transform(snowpark_df).sort(ID_COL)[OUTPUT_COLS].to_pandas().to_numpy()

            np.testing.assert_allclose(target_output, actual_output)

            # 4. Transform with Pandas DF and compare
            pd_actual_output = discretizer.transform(pandas_df.sort_values(by=[ID_COL])[INPUT_COLS])[OUTPUT_COLS]
            np.testing.assert_allclose(target_output, pd_actual_output)

    def test_transform_ordinal_encoding_fuzz_data(self) -> None:
        N_BINS = [2, 9, 5]
        ENCODE = "ordinal"
        OUTPUT_COLS = [f"OUT_{x}" for x in range(len(N_BINS))]

        data, schema = utils.gen_fuzz_data(
            rows=10000,
            types=[
                utils.DataType.INTEGER,
                utils.DataType.INTEGER,
                utils.DataType.INTEGER,
            ],
            low=-999999,
            high=999999,
        )
        pandas_df, snowpark_df = utils.get_df(self._session, data, schema)

        for strategy in self._strategies:
            # 1. Create OSS SKLearn discretizer
            sklearn_discretizer = SklearnKBinsDiscretizer(n_bins=N_BINS, encode=ENCODE, strategy=strategy)
            sklearn_discretizer.fit(pandas_df[schema[1:]])
            target_output = sklearn_discretizer.transform(pandas_df.sort_values(by=[schema[0]])[schema[1:]])

            # 2. Create SnowML discretizer
            discretizer = KBinsDiscretizer(
                n_bins=N_BINS,
                encode=ENCODE,
                strategy=strategy,
                input_cols=schema[1:],
                output_cols=OUTPUT_COLS,
            )
            discretizer.fit(snowpark_df)

            # 3. Transform with Snowpark DF and compare
            actual_output = discretizer.transform(snowpark_df).sort(schema[0])[OUTPUT_COLS].to_pandas().to_numpy()
            np.testing.assert_allclose(target_output, actual_output)

            # 4. Transform with Pandas DF and compare
            pd_actual_output = discretizer.transform(pandas_df.sort_values(by=[schema[0]])[schema[1:]])[OUTPUT_COLS]
            np.testing.assert_allclose(target_output, pd_actual_output)

    def test_transform_onehot_encoding(self) -> None:
        N_BINS = [3, 2]
        ENCODE = "onehot"
        INPUT_COLS, ID_COL, OUTPUT_COLS = (
            utils.NUMERIC_COLS,
            utils.ID_COL,
            utils.OUTPUT_COLS,
        )

        pandas_df, snowpark_df = utils.get_df(self._session, utils.DATA, utils.SCHEMA, np.nan)

        for strategy in self._strategies:
            # 1. Create OSS SKLearn discretizer
            sklearn_discretizer = SklearnKBinsDiscretizer(n_bins=N_BINS, encode=ENCODE, strategy=strategy)
            sklearn_discretizer.fit(pandas_df[INPUT_COLS])
            target_output = sklearn_discretizer.transform(pandas_df.sort_values(by=[ID_COL])[INPUT_COLS])

            # 2. Create SnowML discretizer, fit and transform with snowpark DF
            discretizer = KBinsDiscretizer(
                n_bins=N_BINS,
                encode=ENCODE,
                strategy=strategy,
                input_cols=INPUT_COLS,
                output_cols=OUTPUT_COLS,
            )
            discretizer.fit(snowpark_df)
            snowpark_output = discretizer.transform(snowpark_df).sort(ID_COL)[OUTPUT_COLS]
            snowpark_actual_output = sparse_utils.to_pandas_with_sparse(snowpark_output, OUTPUT_COLS)
            np.testing.assert_equal(target_output.toarray(), snowpark_actual_output.to_numpy())

            # 3. Create SnowML discretizer, fit and transform with pandas DF
            discretizer = KBinsDiscretizer(
                n_bins=N_BINS,
                encode=ENCODE,
                strategy=strategy,
                input_cols=INPUT_COLS,
                output_cols=OUTPUT_COLS,
            )
            discretizer.fit(pandas_df)
            pd_actual_output = discretizer.transform(pandas_df.sort_values(by=[ID_COL])[INPUT_COLS])
            np.testing.assert_equal(target_output.toarray(), pd_actual_output.toarray())

    def test_transform_onehot_dense_encoding(self) -> None:
        N_BINS = [3, 2]
        ENCODE = "onehot-dense"
        INPUT_COLS, ID_COL, OUTPUT_COLS = (
            utils.NUMERIC_COLS,
            utils.ID_COL,
            utils.OUTPUT_COLS,
        )

        pandas_df, snowpark_df = utils.get_df(self._session, utils.DATA, utils.SCHEMA, np.nan)

        for strategy in self._strategies:
            # 1. Create OSS SKLearn discretizer
            sklearn_discretizer = SklearnKBinsDiscretizer(n_bins=N_BINS, encode=ENCODE, strategy=strategy)
            sklearn_discretizer.fit(pandas_df[INPUT_COLS])
            target_output = sklearn_discretizer.transform(pandas_df.sort_values(by=[ID_COL])[INPUT_COLS])

            # 2. Create SnowML discretizer, fit and transform with snowpark DF
            discretizer = KBinsDiscretizer(
                n_bins=N_BINS,
                encode=ENCODE,
                strategy=strategy,
                input_cols=INPUT_COLS,
                output_cols=OUTPUT_COLS,
            )
            discretizer.fit(snowpark_df)
            snowpark_actual_output = (
                discretizer.transform(snowpark_df).sort(ID_COL)[discretizer.get_output_cols()].to_pandas()
            )
            np.testing.assert_equal(target_output, snowpark_actual_output)

            # 3. Create SnowML discretizer, fit and transform with pandas DF
            discretizer = KBinsDiscretizer(
                n_bins=N_BINS,
                encode=ENCODE,
                strategy=strategy,
                input_cols=INPUT_COLS,
                output_cols=OUTPUT_COLS,
            )
            discretizer.fit(pandas_df)
            pd_actual_output = discretizer.transform(pandas_df.sort_values(by=[ID_COL])[INPUT_COLS])[
                discretizer.get_output_cols()
            ]
            np.testing.assert_equal(target_output, pd_actual_output)


if __name__ == "__main__":
    main()
