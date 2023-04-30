import fsspec
from absl.testing import absltest

from snowflake import snowpark
from snowflake.connector import connection
from snowflake.ml.fileset import sfcfs


class SFFileSystemTest(absltest.TestCase):
    def setUp(self) -> None:
        self.mock_connection = absltest.mock.MagicMock(spec=connection.SnowflakeConnection)
        self.mock_connection._telemetry = absltest.mock.Mock()
        self.mock_connection._session_parameters = absltest.mock.Mock()

    def test_init_sf_file_system(self) -> None:
        """Test if the FS could be initilized with a snowpark session or a snowflake python connection."""

        # Manually add some missing artifacts to make sure the success of creating the snowpark session
        self.mock_connection.is_closed.return_value = False
        snowpark_session = snowpark.Session.builder.config("connection", self.mock_connection).create()

        sffs1 = sfcfs.SFFileSystem(snowpark_session=snowpark_session)
        sffs2 = sfcfs.SFFileSystem(sf_connection=self.mock_connection)
        self.assertEqual(sffs1._conn, sffs2._conn)

        with self.assertRaises(ValueError):
            sfcfs.SFFileSystem()

    def test_parse_sfc_file_path(self) -> None:
        """Test if the FS could parse the input stage location correctly"""
        test_cases = [
            ("sfc://@_testdb.testschema._foo/", "_testdb", "testschema", "_foo", ""),
            ('@testdb$."test""s""chema"._foo/', "testdb$", '"test""s""chema"', "_foo", ""),
            ("@test1db.test$schema.foo/nytrain/", "test1db", "test$schema", "foo", "nytrain/"),
            ("@test_db.test_schema.foo/nytrain/1.txt", "test_db", "test_schema", "foo", "nytrain/1.txt"),
            ('@test_d$b."test.schema".fo$_o/nytrain/', "test_d$b", '"test.schema"', "fo$_o", "nytrain/"),
            (
                '@"идентификатор"."test schema"."f.o_o1"/nytrain/',
                '"идентификатор"',
                '"test schema"',
                '"f.o_o1"',
                "nytrain/",
            ),
        ]

        for test_case in test_cases:
            with self.subTest():
                with absltest.mock.patch(
                    "snowflake.ml.fileset.stage_fs.SFStageFileSystem", autospec=True
                ) as MockSFStageFileSystem:
                    instance = MockSFStageFileSystem.return_value
                    sffs = sfcfs.SFFileSystem(self.mock_connection)
                    sffs.ls(test_case[0])
                    MockSFStageFileSystem.assert_any_call(
                        sf_connection=self.mock_connection,
                        db=test_case[1],
                        schema=test_case[2],
                        stage=test_case[3],
                    )
                    instance.ls.assert_any_call(test_case[4], detail=True)

    def test_negative_parse_sfc_file_path(self) -> None:
        """Test if the FS could fail the invalid input stage path"""
        test_cases = [
            "@foo/",  # Missing database and schema
            "@schema.foo/",  # Missing database
            "db.schema.foo/",  # Missing leading "@"
            "@db.schema.foo.file",  # Missing "/" after the stage name
            "@db.schema.foo",  # Missing "/" after the stage name
            '@db."s"chema".foo/',  # Double quoted identifier contains a single \"
            "@3db.schema.foo/1.txt",  # Database name starts with digit
        ]

        for test_case in test_cases:
            with self.subTest():
                with absltest.mock.patch("snowflake.ml.fileset.stage_fs.SFStageFileSystem", autospec=True):
                    sffs = sfcfs.SFFileSystem(self.mock_connection)
                    self.assertRaises(ValueError, sffs.ls, test_case[0])

    def test_ls(self) -> None:
        """Test if `ls` is able to retrieve correct results by initializing file system object directly."""
        with absltest.mock.patch(
            "snowflake.ml.fileset.stage_fs.SFStageFileSystem", autospec=True
        ) as MockSFStageFileSystem:
            # Test use case of initializing file system object directly
            instance = MockSFStageFileSystem.return_value
            instance.stage_name = "@testdb.testschema.foo"
            instance.ls.return_value = [
                {"name": "nytrain/a/", "size": 10, "type": "directory", "md5": "xx", "last_modified": "yy"},
                {"name": "nytrain/b", "size": 10, "type": "file", "md5": "xx", "last_modified": "yy"},
            ]
            sffs = sfcfs.SFFileSystem(sf_connection=self.mock_connection)
            res = sffs.ls("@testdb.testschema.foo/nytrain/")
            MockSFStageFileSystem.assert_any_call(
                sf_connection=self.mock_connection,
                db="testdb",
                schema="testschema",
                stage="foo",
            )
            instance.ls.assert_any_call("nytrain/", detail=True)
            self.assertListEqual(res, ["@testdb.testschema.foo/nytrain/a/", "@testdb.testschema.foo/nytrain/b"])

    def test_ls_with_fsspec(self) -> None:
        """Test if `ls` is able to retrieve correct results by using fsspec"""
        with absltest.mock.patch(
            "snowflake.ml.fileset.stage_fs.SFStageFileSystem", autospec=True
        ) as MockSFStageFileSystem:
            instance = MockSFStageFileSystem.return_value
            instance.stage_name = "@testdb.testschema.foo"
            instance.ls.return_value = [
                {"name": "nytrain/a/", "size": 10, "type": "directory", "md5": "xx", "last_modified": "yy"},
                {"name": "nytrain/b", "size": 10, "type": "file", "md5": "xx", "last_modified": "yy"},
            ]
            sffs = fsspec.filesystem("sfc", sf_connection=self.mock_connection)
            res = sffs.ls("@testdb.testschema.foo/nytrain/")
            MockSFStageFileSystem.assert_any_call(
                sf_connection=self.mock_connection,
                db="testdb",
                schema="testschema",
                stage="foo",
            )
            instance.ls.assert_any_call("nytrain/", detail=True)
            self.assertListEqual(res, ["@testdb.testschema.foo/nytrain/a/", "@testdb.testschema.foo/nytrain/b"])

    def test_exists(self) -> None:
        """Test if `exists` is able to parse the input and return if the path exists."""
        with absltest.mock.patch(
            "snowflake.ml.fileset.stage_fs.SFStageFileSystem", autospec=True
        ) as MockSFStageFileSystem:
            instance = MockSFStageFileSystem.return_value
            instance.exists.return_value = True
            sffs = sfcfs.SFFileSystem(self.mock_connection)
            res = sffs.exists("@testdb.testschema.foo/nytrain/b")
            MockSFStageFileSystem.assert_any_call(
                sf_connection=self.mock_connection,
                db="testdb",
                schema="testschema",
                stage="foo",
            )
            self.assertTrue(res)

    def test_info(self) -> None:
        """Test if `info` is able to parse the input and return the information of the given path."""
        with absltest.mock.patch(
            "snowflake.ml.fileset.stage_fs.SFStageFileSystem", autospec=True
        ) as MockSFStageFileSystem:
            instance = MockSFStageFileSystem.return_value
            expected_res = {
                "name": "nytrain/b",
                "size": 10,
                "type": "file",
                "md5": "xx",
                "last_modified": "yy",
            }
            instance.info.return_value = expected_res
            sffs = sfcfs.SFFileSystem(self.mock_connection)
            res = sffs.info("@testdb.testschema.foo/nytrain/b")
            MockSFStageFileSystem.assert_any_call(
                sf_connection=self.mock_connection,
                db="testdb",
                schema="testschema",
                stage="foo",
            )
            self.assertDictEqual(res, expected_res)

    def test_optimize_read(self) -> None:
        """Test if optimize_read() can call correct stage filesystems to do their read optimization."""
        with absltest.mock.patch(
            "snowflake.ml.fileset.stage_fs.SFStageFileSystem", autospec=True
        ) as MockSFStageFileSystem:
            instance1 = absltest.mock.MagicMock()
            instance2 = absltest.mock.MagicMock()
            MockSFStageFileSystem.side_effect = [instance1, instance2]
            sffs = sfcfs.SFFileSystem(self.mock_connection)

            # Confirm optimize_read() will do noting for empty input
            sffs.optimize_read([])
            MockSFStageFileSystem.assert_not_called()

            file_list = [
                "@testdb.testschema.foo/nytrain/a",
                "@testdb.testschema.foo/nytrain/b",
                "@testdb.testschema.bar/nytrain/c",
            ]
            sffs.optimize_read(file_list)
            MockSFStageFileSystem.assert_any_call(
                sf_connection=self.mock_connection,
                db="testdb",
                schema="testschema",
                stage="bar",
            )
            MockSFStageFileSystem.assert_any_call(
                sf_connection=self.mock_connection,
                db="testdb",
                schema="testschema",
                stage="foo",
            )
            instance1.optimize_read.assert_any_call(["nytrain/a", "nytrain/b"])
            instance2.optimize_read.assert_any_call(["nytrain/c"])

    def test_open(self) -> None:
        """Test if 'open' is able to parse the input and call the underlying file system to open files."""
        with absltest.mock.patch(
            "snowflake.ml.fileset.stage_fs.SFStageFileSystem", autospec=True
        ) as MockSFStageFileSystem:
            # Test use case of initializing file system object and using it to read
            instance = MockSFStageFileSystem.return_value
            instance._open.return_value = absltest.mock.MagicMock(spec=fsspec.spec.AbstractBufferedFile)
            sffs = sfcfs.SFFileSystem(self.mock_connection)
            sffs.open("@testdb.testschema.foo/nytrain/1.txt")
            MockSFStageFileSystem.assert_any_call(
                sf_connection=self.mock_connection,
                db="testdb",
                schema="testschema",
                stage="foo",
            )
            instance._open.assert_called()
            instance._open.assert_any_call(
                "nytrain/1.txt", mode="rb", block_size=None, autocommit=True, cache_options=None
            )

        with absltest.mock.patch(
            "snowflake.ml.fileset.stage_fs.SFStageFileSystem", autospec=True
        ) as MockSFStageFileSystem:
            # Test use case of reading from fsspec
            instance = MockSFStageFileSystem.return_value
            instance._open.return_value = absltest.mock.MagicMock(spec=fsspec.spec.AbstractBufferedFile)
            fp = fsspec.open("sfc://@testdb.testschema.foo/nytrain/1.txt", sf_connection=self.mock_connection)
            fp.open()
            MockSFStageFileSystem.assert_any_call(
                sf_connection=self.mock_connection,
                db="testdb",
                schema="testschema",
                stage="foo",
            )
            instance._open.assert_called()
            instance._open.assert_any_call(
                "nytrain/1.txt", mode="rb", block_size=None, autocommit=True, cache_options=None
            )


if __name__ == "__main__":
    absltest.main()
