import argparse
from pathlib import Path

from analytics.datasets import DashboardDatasets
from analytics.fixtures import load_fixture_dashboard_datasets
from analytics.repository import load_gold_dashboard_datasets
from dashboard.build import build_site
from pipeline import get_database_connection, init_motherduck_config


def _load_datasets(source: str) -> DashboardDatasets:
    if source == "fixtures":
        return load_fixture_dashboard_datasets()

    config = init_motherduck_config()
    with get_database_connection(config) as connection:
        return load_gold_dashboard_datasets(connection)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the DEP dashboard site")
    parser.add_argument(
        "--source",
        choices=("gold", "fixtures"),
        default="gold",
        help="Dashboard data source",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("site"),
        help="Generated site directory",
    )
    args = parser.parse_args()

    datasets = _load_datasets(args.source)
    build_site(datasets, args.output)
    print(f"Dashboard built at {args.output.resolve()}")


if __name__ == "__main__":
    main()
