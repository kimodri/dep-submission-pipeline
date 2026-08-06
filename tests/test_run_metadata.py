import os
import unittest
from unittest.mock import patch

from pipeline.run_metadata import resolve_run_metadata


class ResolveRunMetadataTests(unittest.TestCase):
    def test_uses_github_metadata_in_actions(self):
        with patch.dict(
            os.environ,
            {
                "GITHUB_ACTIONS": "true",
                "GITHUB_RUN_ID": "85001",
                "GITHUB_RUN_ATTEMPT": "2",
            },
            clear=True,
        ):
            metadata = resolve_run_metadata()

        self.assertEqual(metadata.run_id, "85001")
        self.assertEqual(metadata.attempt_number, 2)

    def test_generates_local_metadata_outside_actions(self):
        with patch.dict(os.environ, {}, clear=True):
            metadata = resolve_run_metadata()

        self.assertTrue(metadata.run_id.startswith("local-"))
        self.assertEqual(metadata.attempt_number, 1)

    def test_rejects_missing_github_metadata(self):
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}, clear=True):
            with self.assertRaisesRegex(ValueError, "GITHUB_RUN_ID"):
                resolve_run_metadata()

    def test_rejects_invalid_attempt_number(self):
        with patch.dict(
            os.environ,
            {
                "GITHUB_ACTIONS": "true",
                "GITHUB_RUN_ID": "85001",
                "GITHUB_RUN_ATTEMPT": "not-a-number",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "must be an integer"):
                resolve_run_metadata()

    def test_rejects_non_positive_attempt_number(self):
        with patch.dict(
            os.environ,
            {
                "GITHUB_ACTIONS": "true",
                "GITHUB_RUN_ID": "85001",
                "GITHUB_RUN_ATTEMPT": "0",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "at least 1"):
                resolve_run_metadata()
