"""Stable data contracts shared by dashboard data sources and presentation code."""

from dataclasses import dataclass

import pandas as pd
from pandas.api.types import is_numeric_dtype


@dataclass(frozen=True)
class DatasetContract:
    name: str
    columns: tuple[str, ...]
    numeric_columns: tuple[str, ...] = ()
    date_columns: tuple[str, ...] = ()


CONTRACTS = {
    "submission_status": DatasetContract(
        name="submission status",
        columns=("milestone", "status", "submission_count"),
        numeric_columns=("submission_count",),
    ),
    "builder_schedule": DatasetContract(
        name="builder schedule",
        columns=("schedule_status", "builder_count", "builder_percentage"),
        numeric_columns=("builder_count", "builder_percentage"),
    ),
    "progress_trend": DatasetContract(
        name="progress trend",
        columns=("extraction_date", "completion_rate"),
        numeric_columns=("completion_rate",),
        date_columns=("extraction_date",),
    ),
    "interventions": DatasetContract(
        name="interventions",
        columns=(
            "builder",
            "current_milestone",
            "status",
            "schedule_status",
            "reviewer",
            "issue_state",
            "submission_age_days",
            "days_since_update",
            "next_actor",
            "next_action",
            "issue_url",
        ),
        numeric_columns=("submission_age_days", "days_since_update"),
    ),
    "reviewer_workload": DatasetContract(
        name="reviewer workload",
        columns=("reviewer", "unresolved_count"),
        numeric_columns=("unresolved_count",),
    ),
}


@dataclass(frozen=True)
class DashboardDatasets:
    submission_status: pd.DataFrame
    builder_schedule: pd.DataFrame
    progress_trend: pd.DataFrame
    interventions: pd.DataFrame
    reviewer_workload: pd.DataFrame


def validate_dataset(frame: pd.DataFrame, contract: DatasetContract) -> pd.DataFrame:
    """Return a defensive copy after validating a dashboard dataset."""
    missing = [column for column in contract.columns if column not in frame.columns]
    if missing:
        raise ValueError(
            f"{contract.name} dataset is missing required columns: {', '.join(missing)}"
        )

    validated = frame.loc[:, contract.columns].copy()
    for column in contract.numeric_columns:
        if not is_numeric_dtype(validated[column]):
            raise TypeError(
                f"{contract.name} dataset column '{column}' must be numeric"
            )
        if validated[column].isna().any():
            raise ValueError(
                f"{contract.name} dataset column '{column}' cannot contain null values"
            )

    for column in contract.date_columns:
        try:
            validated[column] = pd.to_datetime(validated[column], errors="raise")
        except (TypeError, ValueError) as error:
            raise TypeError(
                f"{contract.name} dataset column '{column}' must contain dates"
            ) from error

    label_columns = set(contract.columns) - set(contract.numeric_columns) - set(
        contract.date_columns
    )
    for column in label_columns:
        if validated[column].isna().any():
            raise ValueError(
                f"{contract.name} dataset column '{column}' cannot contain null values"
            )
        invalid = validated[column].map(lambda value: not isinstance(value, str))
        if invalid.any():
            raise TypeError(
                f"{contract.name} dataset column '{column}' must contain text"
            )

    return validated


def validate_dashboard_datasets(datasets: DashboardDatasets) -> DashboardDatasets:
    return DashboardDatasets(
        submission_status=validate_dataset(
            datasets.submission_status, CONTRACTS["submission_status"]
        ),
        builder_schedule=validate_dataset(
            datasets.builder_schedule, CONTRACTS["builder_schedule"]
        ),
        progress_trend=validate_dataset(
            datasets.progress_trend, CONTRACTS["progress_trend"]
        ),
        interventions=validate_dataset(
            datasets.interventions, CONTRACTS["interventions"]
        ),
        reviewer_workload=validate_dataset(
            datasets.reviewer_workload, CONTRACTS["reviewer_workload"]
        ),
    )
