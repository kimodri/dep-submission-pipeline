import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd

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
                                    "updatedAt": "2026-08-02T00:00:00Z",
                                    "state": "OPEN",
                                    "assignees": {"nodes": []},
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

    def test_builder_is_active_before_the_first_deadline(self):
        result = transform_bronze_to_silver(
            run_id="run-123",
            extracted_at=datetime(2026, 6, 22, tzinfo=timezone.utc),
            payload={"pages": [_page("issue-1", "M0", "In review")]},
        )

        self.assertEqual(result["builder_status"].tolist(), ["active"])

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
        self.assertEqual(result["current_milestone"].tolist(), ["M2", "M2"])
        self.assertEqual(result["builder_status"].tolist(), ["delayed", "delayed"])

    def test_builder_is_active_while_current_window_is_open(self):
        result = transform_bronze_to_silver(
            run_id="run-123",
            extracted_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
            payload={"pages": [_page("issue-1", "M2", "Passed")]},
        )

        self.assertEqual(result["builder_status"].tolist(), ["active"])

    def test_builder_becomes_delayed_after_milestone_deadline(self):
        payload = {"pages": [_page("issue-1", "M2", "Passed")]}

        on_deadline = transform_bronze_to_silver(
            "run-123",
            datetime(2026, 9, 13, 8, tzinfo=timezone.utc),
            payload,
        )
        after_deadline = transform_bronze_to_silver(
            "run-123",
            datetime(2026, 9, 14, tzinfo=timezone.utc),
            payload,
        )

        self.assertEqual(on_deadline["builder_status"].tolist(), ["active"])
        self.assertEqual(after_deadline["builder_status"].tolist(), ["delayed"])

    def test_later_passed_milestone_satisfies_an_earlier_requirement(self):
        result = transform_bronze_to_silver(
            run_id="run-123",
            extracted_at=datetime(2026, 9, 14, tzinfo=timezone.utc),
            payload={"pages": [_page("issue-1", "M4", "pAsSeD")]},
        )

        self.assertEqual(result["builder_status"].tolist(), ["active"])

    def test_uses_manila_date_for_deadline_boundary(self):
        payload = {"pages": [_page("issue-1", "M1", "Passed")]}

        before_midnight = transform_bronze_to_silver(
            "run-123",
            datetime(2026, 8, 2, 15, 59, tzinfo=timezone.utc),
            payload,
        )
        after_midnight = transform_bronze_to_silver(
            "run-123",
            datetime(2026, 8, 2, 16, tzinfo=timezone.utc),
            payload,
        )

        self.assertEqual(before_midnight["builder_status"].tolist(), ["active"])
        self.assertEqual(after_midnight["builder_status"].tolist(), ["delayed"])

    def test_passed_milestone_on_another_page_applies_to_all_builder_rows(self):
        result = transform_bronze_to_silver(
            run_id="run-123",
            extracted_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
            payload={
                "pages": [
                    _page("issue-1", "M1", "In review", author="builder"),
                    _page("issue-2", "M2", "PASSED", author="builder"),
                ]
            },
        )

        self.assertEqual(result["builder_status"].tolist(), ["active", "active"])

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

    def test_builder_status_is_null_without_an_issue_author(self):
        result = transform_bronze_to_silver(
            run_id="run-123",
            extracted_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
            payload={
                "pages": [
                    _page("issue-1", "M2", "Passed", author=None),
                ]
            },
        )

        self.assertTrue(result["builder_status"].isna().all())


if __name__ == "__main__":
    unittest.main()
