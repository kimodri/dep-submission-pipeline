import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import duckdb
import pandas as pd

from pipeline.etl.load import create_pipeline_tables, load_silver
from pipeline.etl.silver import (
    transform_bronze_to_silver,
    transform_extraction_to_silver,
)
from pipeline.models import Extraction


def _page(
    issue_id: str,
    milestone: str,
    status: str,
    *,
    author: str | None = "author",
    created_at: str = "2026-08-01T00:00:00Z",
    updated_at: str = "2026-08-02T00:00:00Z",
    reviewers: tuple[str, ...] = (),
) -> dict:
    return {
        "data": {
            "organization": {
                "projectV2": {
                    "items": {
                        "nodes": [
                            {
                                "content": {
                                    "id": issue_id,
                                    "title": f"[{milestone}] Example submission",
                                    "url": f"https://example.com/{issue_id}",
                                    "author": (
                                        {"login": author} if author is not None else None
                                    ),
                                    "createdAt": created_at,
                                    "updatedAt": updated_at,
                                    "state": "OPEN",
                                    "assignees": {
                                        "nodes": [
                                            {"login": reviewer}
                                            for reviewer in reviewers
                                        ]
                                    },
                                    "labels": {"nodes": [{"name": milestone}]},
                                },
                                "fieldValues": {
                                    "nodes": [
                                        {
                                            "name": status,
                                            "field": {"name": "Status"},
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                }
            }
        }
    }


class TransformBronzeToSilverTests(unittest.TestCase):
    @patch("pipeline.etl.silver.transform_bronze_to_silver")
    def test_extraction_wrapper_forwards_bronze_values(self, transform):
        expected = pd.DataFrame({"issue_id": ["issue-1"]})
        transform.return_value = expected
        extracted_at = datetime(2026, 8, 3, tzinfo=timezone.utc)
        extraction = Extraction(
            run_id="run-123",
            attempt_number=2,
            extracted_at=extracted_at,
            payload={"pages": []},
        )

        result = transform_extraction_to_silver(extraction)

        self.assertIs(result, expected)
        transform.assert_called_once_with(
            run_id="run-123",
            extracted_at=extracted_at,
            payload={"pages": []},
        )

    def test_transforms_and_concatenates_every_payload_page(self):
        extracted_at = datetime(2026, 8, 3, tzinfo=timezone.utc)
        payload = {
            "pages": [
                _page("issue-1", "M1", "Passed"),
                _page("issue-2", "M2", "In Review"),
            ]
        }

        result = transform_bronze_to_silver(
            run_id="run-123",
            extracted_at=extracted_at,
            payload=payload,
        )

        self.assertEqual(result["issue_id"].tolist(), ["issue-1", "issue-2"])
        self.assertEqual(result["run_id"].tolist(), ["run-123", "run-123"])

    def test_deduplicates_across_pages_using_latest_created_at(self):
        result = transform_bronze_to_silver(
            run_id="run-123",
            extracted_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
            payload={
                "pages": [
                    _page(
                        "older-issue",
                        "M2",
                        "In review",
                        author="builder",
                        created_at="2026-07-20T00:00:00Z",
                    ),
                    _page(
                        "newer-issue",
                        "M2",
                        "Passed",
                        author="builder",
                        created_at="2026-08-01T00:00:00Z",
                    ),
                ]
            },
        )

        self.assertEqual(result["issue_id"].tolist(), ["newer-issue"])
        self.assertFalse(
            result.duplicated(
                subset=["issue_author", "milestone"],
                keep=False,
            ).any()
        )

    def test_derives_assignment_and_age_metrics(self):
        result = transform_bronze_to_silver(
            run_id="run-123",
            extracted_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
            payload={
                "pages": [
                    _page("unassigned", "M1", "In review"),
                    _page(
                        "assigned",
                        "M2",
                        "In review",
                        reviewers=("reviewer",),
                    ),
                ]
            },
        ).set_index("issue_id")

        self.assertFalse(result.loc["unassigned", "is_assigned"])
        self.assertTrue(result.loc["assigned", "is_assigned"])
        self.assertEqual(result.loc["unassigned", "days_since_update"], 3)
        self.assertEqual(result.loc["unassigned", "submission_age_days"], 4)

    def test_loader_rejects_builder_progress_columns(self):
        result = transform_bronze_to_silver(
            run_id="run-123",
            extracted_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
            payload={"pages": [_page("issue-1", "M1", "Passed")]},
        )
        conn = duckdb.connect(":memory:")
        self.addCleanup(conn.close)
        create_pipeline_tables(conn)

        load_silver(conn, result)
        self.assertEqual(
            conn.execute("SELECT count(*) FROM silver.issue_submissions").fetchone()[0],
            1,
        )

        legacy_result = result.assign(
            current_milestone="M2",
            schedule_status="delayed",
        )
        with self.assertRaises(ValueError) as raised:
            load_silver(conn, legacy_result)

        self.assertIn(
            "unexpected columns: ['current_milestone', 'schedule_status']",
            str(raised.exception),
        )


if __name__ == "__main__":
    unittest.main()
