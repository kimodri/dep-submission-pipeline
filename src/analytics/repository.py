from pathlib import Path

import duckdb
import pandas as pd

from analytics.datasets import (
    CONTRACTS,
    DashboardDatasets,
    validate_dashboard_datasets,
    validate_dataset,
)


QUERY_FILES = {
    "submission_status": "submission_distribution.sql",
    "builder_schedule": "builder_status.sql",
    "progress_trend": "builder_progress.sql",
    "interventions": "builder_interventions.sql",
    "reviewer_workload": "reviewer_workload.sql",
}


def _execute_query(
    connection: duckdb.DuckDBPyConnection,
    dataset_name: str,
    query_dir: Path | None,
) -> pd.DataFrame:
    resolved_query_dir = query_dir or Path(__file__).resolve().parent / "queries"
    query_path = resolved_query_dir / QUERY_FILES[dataset_name]
    if not query_path.is_file():
        raise FileNotFoundError(f"Analytics query does not exist: {query_path}")

    query = query_path.read_text(encoding="utf-8").strip()
    if not query:
        raise ValueError(f"Analytics query is empty: {query_path}")

    return connection.execute(query).fetchdf()


def load_submission_status(
    connection: duckdb.DuckDBPyConnection,
    query_dir: Path | None = None,
) -> pd.DataFrame:
    return validate_dataset(
        _execute_query(connection, "submission_status", query_dir),
        CONTRACTS["submission_status"],
    )


def load_builder_schedule(
    connection: duckdb.DuckDBPyConnection,
    query_dir: Path | None = None,
) -> pd.DataFrame:
    schedule = _execute_query(connection, "builder_schedule", query_dir)
    if "schedule_status" in schedule.columns:
        schedule["schedule_status"] = (
            schedule["schedule_status"]
            .astype("string")
            .str.replace("_", " ", regex=False)
            .str.capitalize()
            .astype(object)
        )
    return validate_dataset(schedule, CONTRACTS["builder_schedule"])


def load_progress_trend(
    connection: duckdb.DuckDBPyConnection,
    query_dir: Path | None = None,
) -> pd.DataFrame:
    progress = _execute_query(connection, "progress_trend", query_dir).rename(
        columns={"average_completion_percentage": "completion_rate"}
    )
    return validate_dataset(progress, CONTRACTS["progress_trend"])


def load_interventions(
    connection: duckdb.DuckDBPyConnection,
    query_dir: Path | None = None,
) -> pd.DataFrame:
    return validate_dataset(
        _execute_query(connection, "interventions", query_dir),
        CONTRACTS["interventions"],
    )


def load_reviewer_workload(
    connection: duckdb.DuckDBPyConnection,
    query_dir: Path | None = None,
) -> pd.DataFrame:
    return validate_dataset(
        _execute_query(connection, "reviewer_workload", query_dir),
        CONTRACTS["reviewer_workload"],
    )


def load_gold_dashboard_datasets(
    connection: duckdb.DuckDBPyConnection,
    query_dir: Path | None = None,
) -> DashboardDatasets:
    return validate_dashboard_datasets(
        DashboardDatasets(
            submission_status=load_submission_status(connection, query_dir),
            builder_schedule=load_builder_schedule(connection, query_dir),
            progress_trend=load_progress_trend(connection, query_dir),
            interventions=load_interventions(connection, query_dir),
            reviewer_workload=load_reviewer_workload(connection, query_dir),
        )
    )
