import unittest
from datetime import datetime, timezone

from pipeline.etl.silver import transform_bronze_to_silver


def _page(issue_id: str, milestone: str, status: str) -> dict:
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
                                    "author": {"login": "author"},
                                    "createdAt": "2026-08-01T00:00:00Z",
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


if __name__ == "__main__":
    unittest.main()
