import unittest
from unittest.mock import Mock, patch
from datetime import datetime

import requests

from pipeline.etl.extract import ExtractionError, extract_submissions


def github_page(*, has_next_page: bool, end_cursor: str | None):
    return {
        "data": {
            "viewer": {"id": "viewer-id"},
            "organization": {
                "projectV2": {
                    "items": {
                        "nodes": [{"content": {"id": "issue-id"}}],
                        "pageInfo": {
                            "hasNextPage": has_next_page,
                            "endCursor": end_cursor,
                        },
                    }
                }
            },
        }
    }


class ExtractSubmissionsTests(unittest.TestCase):
    @patch("pipeline.etl.extract.requests.post")
    def test_preserves_every_paginated_response(self, post: Mock):
        first_page = github_page(has_next_page=True, end_cursor="next-page")
        second_page = github_page(has_next_page=False, end_cursor=None)
        first_response = Mock()
        first_response.json.return_value = first_page
        second_response = Mock()
        second_response.json.return_value = second_page
        post.side_effect = [first_response, second_response]

        extraction = extract_submissions(
            owner_name="example-owner",
            owner_type="organization",
            project_number=1,
            token="example-token",
            run_id="example-run",
            attempt_number=1,
        )

        self.assertEqual(extraction.payload, {"pages": [first_page, second_page]})
        self.assertEqual(extraction.attempt_number, 1)
        self.assertIsInstance(extraction.extracted_at, datetime)
        self.assertIsNotNone(extraction.extracted_at.utcoffset())
        self.assertEqual(post.call_count, 2)
        self.assertIsNone(post.call_args_list[0].kwargs["json"]["variables"]["cursor"])
        self.assertEqual(
            post.call_args_list[1].kwargs["json"]["variables"]["cursor"],
            "next-page",
        )

    @patch("pipeline.etl.extract.requests.post")
    def test_rejects_graphql_errors(self, post: Mock):
        response = Mock()
        response.json.return_value = {"errors": [{"message": "Project not found"}]}
        post.return_value = response

        with self.assertRaisesRegex(ExtractionError, "Project not found"):
            extract_submissions(
                owner_name="example-owner",
                owner_type="organization",
                project_number=1,
                token="example-token",
                run_id="example-run",
                attempt_number=1,
            )

    @patch("pipeline.etl.extract.requests.post")
    def test_rejects_a_non_json_response(self, post: Mock):
        response = Mock()
        response.status_code = 200
        response.json.side_effect = ValueError("not json")
        post.return_value = response

        with self.assertRaisesRegex(ExtractionError, "non-JSON"):
            extract_submissions(
                owner_name="example-owner",
                owner_type="organization",
                project_number=1,
                token="example-token",
                run_id="example-run",
                attempt_number=1,
            )

    @patch("pipeline.etl.extract.requests.post")
    def test_rejects_a_malformed_project_response(self, post: Mock):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"data": {"organization": None}}
        post.return_value = response

        with self.assertRaisesRegex(ExtractionError, "requested project items"):
            extract_submissions(
                owner_name="example-owner",
                owner_type="organization",
                project_number=1,
                token="example-token",
                run_id="example-run",
                attempt_number=1,
            )

    @patch("pipeline.etl.extract.requests.post")
    def test_rejects_an_invalid_pagination_cursor(self, post: Mock):
        response = Mock()
        response.status_code = 200
        response.json.return_value = github_page(
            has_next_page=True,
            end_cursor=None,
        )
        post.return_value = response

        with self.assertRaisesRegex(ExtractionError, "pagination cursor"):
            extract_submissions(
                owner_name="example-owner",
                owner_type="organization",
                project_number=1,
                token="example-token",
                run_id="example-run",
                attempt_number=1,
            )

    def test_rejects_an_unknown_owner_type(self):
        with self.assertRaisesRegex(ValueError, "OWNER_TYPE"):
            extract_submissions(
                owner_name="example-owner",
                owner_type="repository",
                project_number=1,
                token="example-token",
                run_id="example-run",
                attempt_number=1,
            )

    @patch("pipeline.etl.extract.time.sleep")
    @patch("pipeline.etl.extract.requests.post")
    def test_retries_a_transient_connection_error(self, post: Mock, sleep: Mock):
        response = Mock()
        response.status_code = 200
        response.json.return_value = github_page(
            has_next_page=False,
            end_cursor=None,
        )
        post.side_effect = [requests.ConnectionError("temporary"), response]

        extraction = extract_submissions(
            owner_name="example-owner",
            owner_type="organization",
            project_number=1,
            token="example-token",
            run_id="example-run",
            attempt_number=1,
        )

        self.assertEqual(len(extraction.payload["pages"]), 1)
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(5.0)

    @patch("pipeline.etl.extract.time.sleep")
    @patch("pipeline.etl.extract.requests.post")
    def test_retries_a_transient_http_status(self, post: Mock, sleep: Mock):
        unavailable = Mock()
        unavailable.status_code = 503
        unavailable.headers = {"Retry-After": "2"}
        recovered = Mock()
        recovered.status_code = 200
        recovered.json.return_value = github_page(
            has_next_page=False,
            end_cursor=None,
        )
        post.side_effect = [unavailable, recovered]

        extract_submissions(
            owner_name="example-owner",
            owner_type="organization",
            project_number=1,
            token="example-token",
            run_id="example-run",
            attempt_number=1,
        )

        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(2.0)

    @patch("pipeline.etl.extract.time.sleep")
    @patch("pipeline.etl.extract.requests.post")
    def test_does_not_retry_an_authentication_error(self, post: Mock, sleep: Mock):
        unauthorized = Mock()
        unauthorized.status_code = 401
        unauthorized.headers = {}
        unauthorized.raise_for_status.side_effect = requests.HTTPError("unauthorized")
        post.return_value = unauthorized

        with self.assertRaises(requests.HTTPError):
            extract_submissions(
                owner_name="example-owner",
                owner_type="organization",
                project_number=1,
                token="example-token",
                run_id="example-run",
                attempt_number=1,
            )

        self.assertEqual(post.call_count, 1)
        sleep.assert_not_called()

    @patch("pipeline.etl.extract.time.sleep")
    @patch("pipeline.etl.extract.requests.post")
    def test_raises_after_transient_retries_are_exhausted(
        self,
        post: Mock,
        sleep: Mock,
    ):
        post.side_effect = requests.Timeout("still unavailable")

        with self.assertRaises(requests.Timeout):
            extract_submissions(
                owner_name="example-owner",
                owner_type="organization",
                project_number=1,
                token="example-token",
                run_id="example-run",
                attempt_number=1,
            )

        self.assertEqual(post.call_count, 4)
        self.assertEqual(sleep.call_count, 3)


if __name__ == "__main__":
    unittest.main()
