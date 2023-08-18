import os
from typing import Tuple

import pandas as pd
import sklearn.datasets as datasets
import sklearn.neighbors as neighbors
from absl.testing import absltest
from absl.testing.absltest import mock
from starlette import testclient

from snowflake.ml.model import _model as model_api, _model_meta, custom_model


class MainTest(absltest.TestCase):
    """
    This test utilizes TestClient, powered by httpx, to send requests to the Starlette application. It optionally skips
    the model loading step in the inference code, which is irrelevant for route testing and challenging to mock due to
    gunicorn's preload option when loading the Starlette Python app. This skipping is achieved by checking the presence
    of the 'PYTEST_CURRENT_TEST' environment variable during pytest execution, the 'TEST_WORKSPACE' variable during
    bazel test execution, or the 'TEST_SRCDIR' variable during Absl test execution.
    """

    def setUp(self) -> None:
        super().setUp()
        from main import app

        self.client = testclient.TestClient(app)
        self.loaded_sklearn_model, self.loaded_sklearn_meta = self.get_custom_sklearn_model()

    def get_custom_sklearn_model(self) -> Tuple[custom_model.CustomModel, _model_meta.ModelMetadata]:
        iris = datasets.load_iris(as_frame=True)
        x = iris.data
        y = iris.target
        knn_model = neighbors.KNeighborsClassifier()
        knn_model.fit(x, y)

        class TestCustomModel(custom_model.CustomModel):
            def __init__(self, context: custom_model.ModelContext) -> None:
                super().__init__(context)

            @custom_model.inference_api
            def predict(self, input: pd.DataFrame) -> pd.DataFrame:
                return pd.DataFrame(knn_model.predict(input))

        model = TestCustomModel(custom_model.ModelContext())
        tmpdir = self.create_tempdir()
        model_name = "model_name"
        model_api.save_model(
            name=model_name,
            model_dir_path=os.path.join(tmpdir.full_path, model_name),
            model=model,
            sample_input=x,
            metadata={"author": "halu", "version": "1"},
        )
        return model_api._load_model_for_deploy(model_dir_path=os.path.join(tmpdir, model_name))

    def test_ready_endpoint(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ready"})

    def test_predict_endpoint_happy_path(self) -> None:
        loaded_model, loaded_meta = self.get_custom_sklearn_model()

        # Construct data input based on external function data input format
        data = {
            "data": [
                [
                    0,
                    {
                        "_ID": 0,
                        "sepal length (cm)": 5.1,
                        "sepal width (cm)": 3.5,
                        "petal length (cm)": 4.2,
                        "petal width (cm)": 1.3,
                    },
                ],
                [
                    1,
                    {
                        "_ID": 1,
                        "sepal length (cm)": 4.7,
                        "sepal width (cm)": 3.2,
                        "petal length (cm)": 4.1,
                        "petal width (cm)": 4.2,
                    },
                ],
            ]
        }

        with mock.patch.dict(os.environ, {"TARGET_METHOD": "predict"}, clear=True), mock.patch(
            "main._LOADED_MODEL", loaded_model
        ), mock.patch("main._LOADED_META", loaded_meta):
            response = self.client.post("/predict", json=data)
            self.assertEqual(response.status_code, 200)
            expected_response = {
                "data": [[0, {"output_feature_0": 1, "_ID": 0}], [1, {"output_feature_0": 2, "_ID": 1}]]
            }
            self.assertEqual(response.json(), expected_response)

    def test_predict_endpoint_with_invalid_input(self) -> None:
        loaded_model, loaded_meta = self.get_custom_sklearn_model()
        with mock.patch.dict(os.environ, {"TARGET_METHOD": "predict"}, clear=True), mock.patch(
            "main._LOADED_MODEL", loaded_model
        ), mock.patch("main._LOADED_META", loaded_meta):
            response = self.client.post("/predict", json={})
            self.assertEqual(response.status_code, 400)
            self.assertRegex(response.text, "Input data malformed: missing data field in the request input")

            response = self.client.post("/predict", json={"data": []})
            self.assertEqual(response.status_code, 400)
            self.assertRegex(response.text, "Input data malformed")

            # Input data with indexes only.
            response = self.client.post("/predict", json={"data": [[0], [1]]})
            self.assertEqual(response.status_code, 400)
            self.assertRegex(response.text, "Input data malformed")

            response = self.client.post(
                "/predict",
                json={
                    "foo": [
                        [1, 2],
                        [2, 3],
                    ]
                },
            )
            self.assertEqual(response.status_code, 400)
            self.assertRegex(response.text, "Input data malformed: missing data field in the request input")

    #
    def test_predict_with_misshaped_data(self) -> None:
        loaded_model, loaded_meta = self.get_custom_sklearn_model()

        data = {
            "data": [
                [
                    0,
                    {
                        "_ID": 0,
                        "sepal length (cm)": 5.1,
                        "sepal width (cm)": 3.5,
                        "petal length (cm)": 4.2,
                    },
                ],
                [
                    1,
                    {
                        "_ID": 1,
                        "sepal length (cm)": 4.7,
                        "sepal width (cm)": 3.2,
                        "petal length (cm)": 4.1,
                    },
                ],
            ]
        }

        with mock.patch.dict(os.environ, {"TARGET_METHOD": "predict"}, clear=True), mock.patch(
            "main._LOADED_MODEL", loaded_model
        ), mock.patch("main._LOADED_META", loaded_meta):
            response = self.client.post("/predict", json=data)
            self.assertEqual(response.status_code, 400)
            self.assertRegex(response.text, r"Input data malformed: .*dtype mappings argument.*")

    def test_predict_with_incorrect_data_type(self) -> None:
        loaded_model, loaded_meta = self.get_custom_sklearn_model()
        data = {
            "data": [
                [
                    0,
                    {
                        "_ID": 0,
                        "sepal length (cm)": "a",
                        "sepal width (cm)": "b",
                        "petal length (cm)": "c",
                        "petal width (cm)": "d",
                    },
                ]
            ]
        }

        with mock.patch.dict(os.environ, {"TARGET_METHOD": "predict"}, clear=True), mock.patch(
            "main._LOADED_MODEL", loaded_model
        ), mock.patch("main._LOADED_META", loaded_meta):
            response = self.client.post("/predict", json=data)
            self.assertEqual(response.status_code, 400)
            self.assertRegex(response.text, "Input data malformed: could not convert string to float")


if __name__ == "__main__":
    absltest.main()
