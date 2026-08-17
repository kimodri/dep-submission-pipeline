import tempfile
import unittest
from pathlib import Path

import duckdb

from analytics.repository import (
    load_builder_schedule,
    load_gold_dashboard_datasets,
    load_progress_trend,
    load_reviewer_workload,
)


QUERIES = {
    "submission_distribution.sql": """
        SELECT 'M0' AS milestone, 'Passed' AS status, 3 AS submission_count
    """,
    "builder_status.sql": """
        SELECT 'on_track' AS schedule_status,
               3 AS builder_count,
               75.0 AS builder_percentage
    """,
    "builder_progress.sql": """
        SELECT DATE '2026-08-17' AS extraction_date,
               42.5 AS average_completion_percentage
    """,
    "builder_interventions.sql": """
        SELECT
            'builder-one' AS builder,
            'M2' AS current_milestone,
            'In review' AS status,
            'On track' AS schedule_status,
            'reviewer-one' AS reviewer,
            'OPEN' AS issue_state,
            10 AS submission_age_days,
            2 AS days_since_update,
            'Reviewer' AS next_actor,
            'Complete review' AS next_action,
            'https://example.com/issue/1' AS issue_url
    """,
    "reviewer_workload.sql": """
        SELECT 'reviewer-one' AS reviewer, 2 AS unresolved_count
    """,
}


class AnalyticsRepositoryFunctionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.query_dir = Path(self.temp_dir.name)
        for filename, query in QUERIES.items():
            (self.query_dir / filename).write_text(query, encoding="utf-8")
        self.connection = duckdb.connect(":memory:")

    def tearDown(self):
        self.connection.close()
        self.temp_dir.cleanup()

    def test_load_returns_all_dashboard_datasets_in_contract_shape(self):
        datasets = load_gold_dashboard_datasets(self.connection, self.query_dir)

        self.assertEqual(
            datasets.submission_status.columns.tolist(),
            ["milestone", "status", "submission_count"],
        )
        self.assertEqual(
            datasets.builder_schedule["schedule_status"].tolist(),
            ["On track"],
        )
        self.assertEqual(
            datasets.progress_trend["completion_rate"].tolist(),
            [42.5],
        )
        self.assertEqual(
            datasets.interventions["next_action"].tolist(),
            ["Complete review"],
        )
        self.assertEqual(
            datasets.reviewer_workload["unresolved_count"].tolist(),
            [2],
        )

    def test_individual_loaders_normalize_query_outputs(self):
        schedule = load_builder_schedule(self.connection, self.query_dir)
        progress = load_progress_trend(self.connection, self.query_dir)

        self.assertEqual(schedule["schedule_status"].tolist(), ["On track"])
        self.assertEqual(progress["completion_rate"].tolist(), [42.5])

    def test_missing_query_has_a_clear_error(self):
        (self.query_dir / "reviewer_workload.sql").unlink()

        with self.assertRaisesRegex(
            FileNotFoundError,
            "Analytics query does not exist",
        ):
            load_reviewer_workload(self.connection, self.query_dir)

    def test_empty_query_has_a_clear_error(self):
        (self.query_dir / "reviewer_workload.sql").write_text("", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "Analytics query is empty"):
            load_reviewer_workload(self.connection, self.query_dir)


if __name__ == "__main__":
    unittest.main()
