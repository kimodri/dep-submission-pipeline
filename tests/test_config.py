import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pipeline.config import (
    init_local_config,
    init_motherduck_config,
    init_source_config,
)
from pipeline.database import get_dev_database_connection
from pipeline.models import LocalConfig


class RuntimeConfigurationTests(unittest.TestCase):
    def test_local_config_requires_no_remote_secrets(self):
        with TemporaryDirectory() as temp_dir:
            environment = {
                "DUCKDB_PATH": str(Path(temp_dir) / "warehouse.duckdb"),
                "SAMPLE_DATA_PATH": str(Path(temp_dir) / "sample.json"),
            }
            with (
                patch.dict(os.environ, environment, clear=True),
                patch("pipeline.config.load_dotenv"),
            ):
                config = init_local_config()

        self.assertEqual(config.duckdb_path, Path(environment["DUCKDB_PATH"]))
        self.assertEqual(
            config.sample_data_path,
            Path(environment["SAMPLE_DATA_PATH"]),
        )

    def test_source_config_does_not_require_motherduck(self):
        environment = {
            "TOKEN": "github-token",
            "OWNER_NAME": "example-owner",
            "OWNER_TYPE": "organization",
            "PROJECT_NUMBER": "1",
        }
        with (
            patch.dict(os.environ, environment, clear=True),
            patch("pipeline.config.load_dotenv"),
        ):
            config = init_source_config()

        self.assertEqual(config.token, "github-token")
        self.assertEqual(config.project_number, 1)

    def test_motherduck_config_requires_path_and_token(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("pipeline.config.load_dotenv"),
        ):
            with self.assertRaisesRegex(ValueError, "MOTHERDUCKDB_PATH"):
                init_motherduck_config()

        with (
            patch.dict(
                os.environ,
                {
                    "MOTHERDUCKDB_PATH": "md:example",
                    "MOTHERDUCK_TOKEN": "motherduck-token",
                },
                clear=True,
            ),
            patch("pipeline.config.load_dotenv"),
        ):
            config = init_motherduck_config()

        self.assertEqual(config.database_path, "md:example")
        self.assertEqual(config.token, "motherduck-token")

    def test_local_connection_creates_missing_parent_directory(self):
        with TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "nested" / "warehouse.duckdb"
            config = LocalConfig(
                duckdb_path=database_path,
                sample_data_path=Path(temp_dir) / "sample.json",
            )

            with get_dev_database_connection(config) as conn:
                result = conn.execute("SELECT 1").fetchone()[0]

            self.assertEqual(result, 1)
            self.assertTrue(database_path.parent.is_dir())


if __name__ == "__main__":
    unittest.main()
