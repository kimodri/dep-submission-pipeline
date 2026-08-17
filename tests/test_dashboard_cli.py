import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from dashboard.__main__ import _load_datasets, main


class DashboardCliTests(unittest.TestCase):
    def test_gold_is_the_default_source(self):
        datasets = object()
        with (
            patch.object(sys, "argv", ["dep-dashboard-build"]),
            patch("dashboard.__main__._load_datasets", return_value=datasets) as load,
            patch("dashboard.__main__.build_site") as build,
            patch("builtins.print"),
        ):
            main()

        load.assert_called_once_with("gold")
        build.assert_called_once_with(datasets, Path("site"))

    def test_gold_loads_from_motherduck_and_closes_connection(self):
        config = object()
        datasets = object()
        connection = object()
        connection_manager = MagicMock()
        connection_manager.__enter__.return_value = connection

        with (
            patch(
                "dashboard.__main__.init_motherduck_config",
                return_value=config,
            ) as init_config,
            patch(
                "dashboard.__main__.get_database_connection",
                return_value=connection_manager,
            ) as get_connection,
            patch(
                "dashboard.__main__.load_gold_dashboard_datasets",
                return_value=datasets,
            ) as load_gold,
        ):
            result = _load_datasets("gold")

        self.assertIs(result, datasets)
        init_config.assert_called_once_with()
        get_connection.assert_called_once_with(config)
        load_gold.assert_called_once_with(connection)
        connection_manager.__exit__.assert_called_once()

    def test_fixture_source_does_not_initialize_motherduck(self):
        datasets = object()
        with (
            patch(
                "dashboard.__main__.load_fixture_dashboard_datasets",
                return_value=datasets,
            ) as load_fixtures,
            patch("dashboard.__main__.init_motherduck_config") as init_config,
        ):
            result = _load_datasets("fixtures")

        self.assertIs(result, datasets)
        load_fixtures.assert_called_once_with()
        init_config.assert_not_called()

    def test_missing_motherduck_config_does_not_modify_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "site"
            output.mkdir()
            sentinel = output / "existing.html"
            sentinel.write_text("existing", encoding="utf-8")

            with (
                patch.object(
                    sys,
                    "argv",
                    ["dep-dashboard-build", "--output", str(output)],
                ),
                patch(
                    "dashboard.__main__.init_motherduck_config",
                    side_effect=ValueError("Missing required environment variable"),
                ),
                patch("dashboard.__main__.build_site") as build,
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "Missing required environment variable",
                ):
                    main()

            build.assert_not_called()
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "existing")


if __name__ == "__main__":
    unittest.main()
