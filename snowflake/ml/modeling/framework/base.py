#!/usr/bin/env python3
#
# Copyright (c) 2012-2022 Snowflake Computing Inc. All rights reserved.
#
import inspect
from abc import abstractmethod
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Union, overload

import numpy as np
import numpy.typing as npt
import pandas as pd

from snowflake import snowpark
from snowflake.ml._internal import telemetry
from snowflake.ml._internal.utils import parallelize
from snowflake.ml.modeling.framework import _utils
from snowflake.snowpark import functions as F

PROJECT = "ModelDevelopment"
SUBPROJECT = "Preprocessing"


def _process_cols(cols: Optional[Union[str, Iterable[str]]]) -> List[str]:
    """Convert cols to a list."""
    col_list: List[str] = []
    if cols is None:
        return col_list
    elif type(cols) is list:
        col_list = cols
    elif type(cols) in [range, set, tuple]:
        col_list = list(cols)
    elif type(cols) is str:
        col_list = [cols]
    else:
        raise TypeError(f"Could not convert {cols} to list")

    return col_list


class Base:
    def __init__(self) -> None:
        """
        Base class for all estimators and transformers.

        Attributes:
            input_cols: Input columns.
            output_cols: Output columns.
            label_cols: Label column(s).
        """
        self.input_cols: List[str] = []
        self.output_cols: List[str] = []
        self.label_cols: List[str] = []

    @abstractmethod
    def _create_unfitted_sklearn_object(self) -> Any:
        raise NotImplementedError()

    @abstractmethod
    def _create_sklearn_object(self) -> Any:
        raise NotImplementedError()

    def get_input_cols(self) -> List[str]:
        """
        Input columns getter.

        Returns:
            Input columns.
        """
        return self.input_cols

    def set_input_cols(self, input_cols: Optional[Union[str, Iterable[str]]]) -> "Base":
        """
        Input columns setter.

        Args:
            input_cols: A single input column or multiple input columns.

        Returns:
            self
        """
        self.input_cols = _process_cols(input_cols)
        return self

    def get_output_cols(self) -> List[str]:
        """
        Output columns getter.

        Returns:
            Output columns.
        """
        return self.output_cols

    def set_output_cols(self, output_cols: Optional[Union[str, Iterable[str]]]) -> "Base":
        """
        Output columns setter.

        Args:
            output_cols: A single output column or multiple output columns.

        Returns:
            self
        """
        self.output_cols = _process_cols(output_cols)
        return self

    def get_label_cols(self) -> List[str]:
        """
        Label column getter.

        Returns:
            Label column(s).
        """
        return self.label_cols

    def set_label_cols(self, label_cols: Optional[Union[str, Iterable[str]]]) -> "Base":
        """
        Label column setter.

        Args:
            label_cols: A single label column or multiple label columns if multi task learning.

        Returns:
            self
        """
        self.label_cols = _process_cols(label_cols)
        return self

    def _check_input_cols(self) -> None:
        """
        Check if `self.input_cols` is set.

        Raises:
            RuntimeError: If `self.input_cols` is not set.
        """
        if not self.input_cols:
            raise RuntimeError("input_cols is not set.")

    def _check_output_cols(self) -> None:
        """
        Check if `self.output_cols` is set.

        Raises:
            RuntimeError: If `self.output_cols` is not set or if the size of `self.output_cols`
                does not match that of `self.input_cols`.
        """
        if not self.output_cols:
            raise RuntimeError("output_cols is not set.")
        if len(self.output_cols) != len(self.input_cols):
            raise RuntimeError(
                f"Size mismatch: input_cols: {len(self.input_cols)}, output_cols: {len(self.output_cols)}."
            )

    @classmethod
    def _get_param_names(cls) -> List[str]:
        """Get parameter names for the transformer"""
        # fetch the constructor or the original constructor before
        # deprecation wrapping if any
        init = getattr(cls.__init__, "deprecated_original", cls.__init__)
        if init is object.__init__:
            # No explicit constructor to introspect
            return []

        # introspect the constructor arguments to find the model parameters
        # to represent
        init_signature = inspect.signature(init)
        # consider the constructor parameters excluding 'self'
        parameters = [p for p in init_signature.parameters.values() if p.name != "self" and p.kind != p.VAR_KEYWORD]
        for p in parameters:
            if p.kind == p.VAR_POSITIONAL:
                raise RuntimeError(
                    "Transformers should always specify"
                    " their parameters in the signature"
                    " of their __init__ (no varargs)."
                    " %s with constructor %s doesn't "
                    " follow this convention." % (cls, init_signature)
                )
        # Extract and sort argument names excluding 'self'
        return sorted(p.name for p in parameters)

    def get_params(self, deep: bool = True) -> Dict[str, Any]:
        """
        Get parameters for this transformer.

        Args:
            deep: If True, will return the parameters for this transformer and
                contained subobjects that are transformers.

        Returns:
            Parameter names mapped to their values.
        """
        out: Dict[str, Any] = dict()
        for key in self._get_param_names():
            if hasattr(self, key):
                value = getattr(self, key)
                if deep and hasattr(value, "get_params"):
                    deep_items = value.get_params().items()
                    out.update((key + "__" + k, val) for k, val in deep_items)
                out[key] = value
        return out

    def set_params(self, **params: Dict[str, Any]) -> None:
        """
        Set the parameters of this transformer.

        The method works on simple transformers as well as on nested objects.
        The latter have parameters of the form ``<component>__<parameter>``
        so that it's possible to update each component of a nested object.

        Args:
            **params: Transformer parameter names mapped to their values.

        Raises:
            ValueError: For invalid parameter keys.
        """
        if not params:
            # simple optimization to gain speed (inspect is slow)
            return
        valid_params = self.get_params(deep=True)

        nested_params: Dict[str, Any] = defaultdict(dict)  # grouped by prefix
        for key, value in params.items():
            key, delim, sub_key = key.partition("__")
            if key not in valid_params:
                local_valid_params = self._get_param_names()
                raise ValueError(
                    f"Invalid parameter {key} for transformer {self}. Valid parameters are: {local_valid_params}."
                )

            if delim:
                nested_params[key][sub_key] = value
            else:
                setattr(self, key, value)
                valid_params[key] = value

        for key, sub_params in nested_params.items():
            valid_params[key].set_params(**sub_params)

    def get_sklearn_args(
        self,
        default_sklearn_obj: Optional[object] = None,
        sklearn_initial_keywords: Optional[Union[str, Iterable[str]]] = None,
        sklearn_unused_keywords: Optional[Union[str, Iterable[str]]] = None,
        snowml_only_keywords: Optional[Union[str, Iterable[str]]] = None,
        sklearn_added_keyword_to_version_dict: Optional[Dict[str, str]] = None,
        sklearn_added_kwarg_value_to_version_dict: Optional[Dict[str, Dict[str, str]]] = None,
        sklearn_deprecated_keyword_to_version_dict: Optional[Dict[str, str]] = None,
        sklearn_removed_keyword_to_version_dict: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Get sklearn keyword arguments.

        This method enables modifying object parameters for special cases.

        Args:
            default_sklearn_obj: Sklearn object used to get default parameter values. Necessary when
                `sklearn_added_keyword_to_version_dict` is provided.
            sklearn_initial_keywords: Initial keywords in sklearn.
            sklearn_unused_keywords: Sklearn keywords that are unused in snowml.
            snowml_only_keywords: snowml only keywords not present in sklearn.
            sklearn_added_keyword_to_version_dict: Added keywords mapped to the sklearn versions in which they were
                added.
            sklearn_added_kwarg_value_to_version_dict: Added keyword argument values mapped to the sklearn versions
                in which they were added.
            sklearn_deprecated_keyword_to_version_dict: Deprecated keywords mapped to the sklearn versions in which
                they were deprecated.
            sklearn_removed_keyword_to_version_dict: Removed keywords mapped to the sklearn versions in which they
                were removed.

        Returns:
            Sklearn parameter names mapped to their values.
        """
        default_sklearn_args = _utils.get_default_args(default_sklearn_obj.__class__.__init__)
        given_args = self.get_params()
        sklearn_args: Dict[str, Any] = _utils.get_filtered_valid_sklearn_args(
            args=given_args,
            default_sklearn_args=default_sklearn_args,
            sklearn_initial_keywords=sklearn_initial_keywords,
            sklearn_unused_keywords=sklearn_unused_keywords,
            snowml_only_keywords=snowml_only_keywords,
            sklearn_added_keyword_to_version_dict=sklearn_added_keyword_to_version_dict,
            sklearn_added_kwarg_value_to_version_dict=sklearn_added_kwarg_value_to_version_dict,
            sklearn_deprecated_keyword_to_version_dict=sklearn_deprecated_keyword_to_version_dict,
            sklearn_removed_keyword_to_version_dict=sklearn_removed_keyword_to_version_dict,
        )
        return sklearn_args


class BaseEstimator(Base):
    def __init__(
        self,
        *,
        file_names: Optional[List[str]] = None,
        custom_states: Optional[List[str]] = None,
        sample_weight_col: Optional[str] = None,
    ) -> None:
        """
        Base class for all estimators.

        Following scikit-learn APIs, all estimators should specify all
        the parameters that can be set at the class level in their ``__init__``
        as explicit keyword arguments (no ``*args`` or ``**kwargs``)

        Args:
            file_names: File names.
            custom_states: Custom states.
            sample_weight_col: Sample weight column.

        Attributes:
            start_time: Start time of the transformer.
        """
        super().__init__()

        # transformer state
        self.file_names = file_names
        self.custom_states = custom_states
        self.sample_weight_col = sample_weight_col

        self.start_time = datetime.now().strftime(_utils.DATETIME_FORMAT)[:-3]

    def get_sample_weight_col(self) -> Optional[str]:
        """
        Sample weight column getter.

        Returns:
            Sample weight column.
        """
        return self.sample_weight_col

    def set_sample_weight_col(self, sample_weight_col: Optional[str]) -> "Base":
        """
        Sample weight column setter.

        Args:
            sample_weight_col: A single column that represents sample weight.

        Returns:
            self
        """
        self.sample_weight_col = sample_weight_col
        return self

    def _get_dependencies(self) -> List[str]:
        """
        Return the list of conda dependencies required to work with the object.

        Returns:
            List of dependencies.
        """
        return []

    @abstractmethod
    def fit(self, dataset: snowpark.DataFrame) -> "BaseEstimator":
        raise NotImplementedError()

    def _use_input_cols_only(self, dataset: pd.DataFrame) -> pd.DataFrame:
        """Returns the pandas dataframe filtered on `input_cols`, or raises an error if malformed."""
        input_cols = set(self.input_cols)
        dataset_cols = set(dataset.columns.to_list())
        if not input_cols.issubset(dataset_cols):
            raise KeyError(
                "The `input_cols` contains columns that do not match any of the columns in "
                f"the dataframe: {input_cols - dataset_cols}."
            )
        return dataset[self.input_cols]

    @telemetry.send_api_usage_telemetry(
        project=PROJECT,
        subproject=SUBPROJECT,
    )
    def _compute(
        self, dataset: snowpark.DataFrame, cols: List[str], states: List[str]
    ) -> Dict[str, Dict[str, Union[int, float, str]]]:
        """
        Compute required states of the columns.

        Args:
            dataset: Input dataset.
            cols: Columns to compute.
            states: States to compute. Arguments are appended. For example, "min" represents
                getting min value of the column, and "percentile_cont:0.25" represents gettting
                the 25th percentile disc value of the column.

        Returns:
            A dict of {column_name: {state: value}} of each column.
        """

        def _compute_on_partition(df: snowpark.DataFrame, cols_subset: List[str]) -> snowpark.DataFrame:
            """Returns a DataFrame with the desired computation on the specified column subset."""
            exprs = []
            sql_prefix = "SQL>>>"

            for col_name in cols_subset:
                for state in states:
                    if state.startswith(sql_prefix):
                        sql_expr = state[len(sql_prefix) :].format(col_name=col_name)
                        exprs.append(sql_expr)
                    else:
                        func = _utils.STATE_TO_FUNC_DICT[state].__name__
                        exprs.append(f"{func}({col_name})")

            res: snowpark.DataFrame = df.select_expr(exprs)
            return res

        _results = parallelize.map_dataframe_by_column(
            df=dataset,
            cols=cols,
            map_func=_compute_on_partition,
            partition_size=40,
            statement_params=telemetry.get_statement_params(PROJECT, SUBPROJECT, self.__class__.__name__),
        )

        computed_dict: Dict[str, Dict[str, Union[int, float, str]]] = {}
        for idx, val in enumerate(_results[0]):
            col_name = cols[idx // len(states)]
            if col_name not in computed_dict:
                computed_dict[col_name] = {}

            state = states[idx % len(states)]
            computed_dict[col_name][state] = val

        return computed_dict


class BaseTransformer(BaseEstimator):
    def __init__(
        self,
        *,
        drop_input_cols: Optional[bool] = False,
        file_names: Optional[List[str]] = None,
        custom_states: Optional[List[str]] = None,
        sample_weight_col: Optional[str] = None,
    ) -> None:
        """Base class for all transformers."""
        super().__init__(file_names=file_names, custom_states=custom_states, sample_weight_col=sample_weight_col)
        self._sklearn_object = None
        self._is_fitted = False
        self._drop_input_cols = drop_input_cols

    @overload
    def transform(self, dataset: snowpark.DataFrame) -> snowpark.DataFrame:
        ...

    @overload
    def transform(self, dataset: pd.DataFrame) -> pd.DataFrame:
        ...

    @abstractmethod
    def transform(self, dataset: Union[snowpark.DataFrame, pd.DataFrame]) -> Union[snowpark.DataFrame, pd.DataFrame]:
        raise NotImplementedError()

    def enforce_fit(self) -> None:
        if not self._is_fitted:
            raise RuntimeError("Transformer not fitted before calling transform().")

    def set_drop_input_cols(self, drop_input_cols: Optional[bool] = False) -> None:
        self._drop_input_cols = drop_input_cols

    def to_sklearn(self) -> Any:
        if self._sklearn_object is None:
            self._sklearn_object = self._create_sklearn_object()
        return self._sklearn_object

    # to_xgboost would be only used in XGB estimators
    # to_lightgbm would be only used in LightGBM estimators, but they function the same
    def to_xgboost(self) -> Any:
        raise AttributeError("Object doesn't support to_xgboost. Please use to_sklearn()")

    def to_lightgbm(self) -> Any:
        raise AttributeError("Object doesn't support to_lightgbm. Please use to_sklearn()")

    def _reset(self) -> None:
        self._sklearn_object = None
        self._is_fitted = False

    def _convert_attribute_dict_to_ndarray(
        self,
        attribute: Optional[Mapping[str, Union[int, float, str, Iterable[Union[int, float, str]]]]],
        dtype: Optional[type] = None,
    ) -> Optional[npt.NDArray[Union[np.int_, np.float_, np.str_]]]:
        """
        Convert the attribute from dict to ndarray based on the order of `self.input_cols`.

        Args:
            attribute: Attribute to convert. Attribute is a mapping of a column to its attribute value(s)
                (e.g. `StandardScaler.mean_: {column_name: mean_value}`).
            dtype: The dtype of the converted ndarray. If None, there is no type conversion.

        Returns:
            A np.ndarray of attribute values, or None if the attribute is None.
        """
        if attribute is None:
            return None

        attribute_vals = []
        is_nested = False
        if self.input_cols:
            iterable_types = [list, tuple, set]
            is_nested = type(attribute[self.input_cols[0]]) in iterable_types

        for input_col in self.input_cols:
            val = attribute[input_col]
            attribute_vals.append(np.array(val) if is_nested else val)
        attribute_arr = np.array(attribute_vals, dtype=object if is_nested else None)

        if dtype:
            attribute_arr = attribute_arr.astype(dtype)

        return attribute_arr

    def _transform_sklearn(self, dataset: pd.DataFrame) -> pd.DataFrame:
        """
        Transform the input dataset using the fitted sklearn transform obj.

        Args:
            dataset: Input dataset to transform.

        Returns:
            Transformed dataset

        Raises:
            TypeError: If the supplied output columns don't match that of the transformed array.
        """
        self.enforce_fit()
        dataset = dataset.copy()
        sklearn_transform = self.to_sklearn()
        transformed_data = sklearn_transform.transform(dataset[self.input_cols])
        shape = transformed_data.shape
        if (len(shape) == 1 and len(self.output_cols) != 1) or (len(shape) > 1 and shape[1] != len(self.output_cols)):
            raise TypeError(
                f"output_cols must be same length as transformed array. Got output_cols len: {len(self.output_cols)},"
                f" transformed array shape: {shape}"
            )

        if len(shape) == 1:
            transformed_data = np.reshape(transformed_data, (-1, 1))
        dataset[self.output_cols] = transformed_data
        return dataset

    def _validate_data_has_no_nulls(self, dataset: snowpark.DataFrame) -> None:
        """
        Validate that the supplied data does not contain null values in the supplied input columns.

        Args:
            dataset: DataFrame to validate.

        Raises:
            ValueError: If the dataset contains nulls in the input_cols.
        """
        self._check_input_cols()

        null_count_columns = []
        for input_col in self.input_cols:
            col = F.count(F.lit("*")) - F.count(dataset[input_col])  # type:ignore[arg-type, operator]
            null_count_columns.append(col)

        null_counts = dataset.agg(*null_count_columns).collect(
            statement_params=telemetry.get_statement_params(PROJECT, SUBPROJECT, self.__class__.__name__)
        )
        assert len(null_counts) == 1

        invalid_columns = {col: n for (col, n) in zip(self.input_cols, null_counts[0].as_dict().values()) if n > 0}

        if any(invalid_columns):
            raise ValueError(
                "Dataset may not contain nulls, but "
                f"the following columns have a non-zero number of nulls: {invalid_columns}."
            )

    def _drop_input_columns(
        self, dataset: Union[snowpark.DataFrame, pd.DataFrame]
    ) -> Union[snowpark.DataFrame, pd.DataFrame]:
        """
        Drop input column for given dataset.

        Args:
            dataset: The input Dataset. Either a Snowflake DataFrame or Pandas DataFrame.

        Returns:
            Return a dataset with input columns dropped.

        Raises:
            TypeError: If the dataset is neither DataFrame or Pandas DataFrame.
            RuntimeError: drop_input_cols flag must be true before calling this function.
        """
        if not self._drop_input_cols:
            raise RuntimeError("drop_input_cols must set true before calling.")

        # In case of input_cols and output_cols are the same, compare with get_output_cols()
        input_subset = list(set(self.input_cols) - set(self.get_output_cols()))

        if isinstance(dataset, snowpark.DataFrame):
            return dataset.drop(input_subset)
        elif isinstance(dataset, pd.DataFrame):
            return dataset.drop(columns=input_subset)
        else:
            raise TypeError(
                f"Unexpected dataset type: {type(dataset)}."
                "Supported dataset types: snowpark.DataFrame, pandas.DataFrame."
            )
