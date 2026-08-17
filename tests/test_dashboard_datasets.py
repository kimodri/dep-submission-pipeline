import tempfile
import unittest
from pathlib import Path

import pandas as pd

from analytics.datasets import CONTRACTS, DashboardDatasets, validate_dataset
from analytics.fixtures import load_fixture_dashboard_datasets


class DashboardDatasetContractTests(unittest.TestCase):
    def test_rejects_missing_required_column(self):
        frame = pd.DataFrame({"milestone": ["M1"], "status": ["Accepted"]})

        with self.assertRaisesRegex(ValueError, "submission_count"):
            validate_dataset(frame, CONTRACTS["submission_status"])

    def test_rejects_non_numeric_measure(self):
        frame = pd.DataFrame(
            {"milestone": ["M1"], "status": ["Accepted"], "submission_count": ["many"]}
        )

        with self.assertRaisesRegex(TypeError, "must be numeric"):
            validate_dataset(frame, CONTRACTS["submission_status"])

    def test_rejects_null_label(self):
        frame = pd.DataFrame(
            {"milestone": ["M1"], "status": [None], "submission_count": [2]}
        )

        with self.assertRaisesRegex(ValueError, "cannot contain null"):
            validate_dataset(frame, CONTRACTS["submission_status"])

    def test_accepts_empty_dataset_with_declared_columns(self):
        contract = CONTRACTS["reviewer_workload"]
        frame = pd.DataFrame(
            {
                "reviewer": pd.Series(dtype="object"),
                "unresolved_count": pd.Series(dtype="int64"),
            }
        )

        validated = validate_dataset(frame, contract)

        self.assertTrue(validated.empty)
        self.assertEqual(tuple(validated.columns), contract.columns)

    def test_fixture_source_returns_all_contracts_and_normalizes_reviewers(self):
        datasets = load_fixture_dashboard_datasets()

        self.assertIsInstance(datasets, DashboardDatasets)
        self.assertIn("Unassigned", datasets.interventions["reviewer"].tolist())
        self.assertFalse(datasets.progress_trend.empty)

    def test_missing_fixture_has_specific_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(FileNotFoundError, "progress_trend.csv"):
                load_fixture_dashboard_datasets(Path(directory))
