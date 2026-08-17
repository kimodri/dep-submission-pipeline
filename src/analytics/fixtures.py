from pathlib import Path

import pandas as pd

from analytics.datasets import DashboardDatasets, validate_dashboard_datasets


def _read_fixture(fixture_dir: Path, name: str) -> pd.DataFrame:
    path = fixture_dir / f"{name}.csv"
    if not path.is_file():
        raise FileNotFoundError(f"Dashboard fixture does not exist: {path}")
    return pd.read_csv(path)


def load_fixture_dashboard_datasets(
    fixture_dir: Path | None = None,
) -> DashboardDatasets:
    resolved_fixture_dir = fixture_dir or (
        Path(__file__).resolve().parents[1] / "dashboard" / "fixtures"
    )
    progress = _read_fixture(resolved_fixture_dir, "progress_trend")
    progress["extraction_date"] = pd.to_datetime(
        progress["extraction_date"], errors="raise"
    )

    interventions = _read_fixture(resolved_fixture_dir, "interventions")
    interventions["reviewer"] = interventions["reviewer"].fillna("Unassigned")

    reviewer_workload = _read_fixture(resolved_fixture_dir, "reviewer_workload")
    reviewer_workload["reviewer"] = reviewer_workload["reviewer"].fillna(
        "Unassigned"
    )

    return validate_dashboard_datasets(
        DashboardDatasets(
            submission_status=_read_fixture(
                resolved_fixture_dir, "submission_status"
            ),
            builder_schedule=_read_fixture(
                resolved_fixture_dir, "builder_schedule"
            ),
            progress_trend=progress,
            interventions=interventions,
            reviewer_workload=reviewer_workload,
        )
    )
