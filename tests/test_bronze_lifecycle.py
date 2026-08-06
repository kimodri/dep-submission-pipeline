from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import Mock

import duckdb

from pipeline.__main__ import run_bronze_pipeline
from pipeline.config import Config
from pipeline.etl.errors import ExtractionError
from pipeline.etl.load import extract_canonical_bronze
from pipeline.models import Extraction, RunMetadata


def test_config() -> Config:
    return Config(
        token="source-secret",
        owner_name="example-owner",
        owner_type="organization",
        project_number=1,
        database_path=Path("unused.duckdb"),
        duckdb_path=":memory:",
        motherduckdb_path="md:example",
        sample_data_path="sample.json",
    )


def successful_extraction(**kwargs) -> Extraction:
    return Extraction(
        run_id=kwargs["run_id"],
        attempt_number=kwargs["attempt_number"],
        extracted_at=datetime.now(timezone.utc),
        payload={"pages": [{"data": {"example": True}}]},
    )


class BronzeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.conn = duckdb.connect(":memory:")
        self.config = test_config()

    def tearDown(self):
        self.conn.close()

    def test_success_creates_bronze_and_succeeded_attempt(self):
        metadata = RunMetadata("run-1", 1)

        result = run_bronze_pipeline(
            self.conn,
            self.config,
            metadata,
            extractor=successful_extraction,
        )

        self.assertIsNotNone(result)
        status = self.conn.execute(
            "SELECT attempt_status FROM ops.pipeline_attempts"
        ).fetchone()[0]
        bronze_count = self.conn.execute(
            "SELECT count(*) FROM bronze.raw_issue_extractions"
        ).fetchone()[0]
        self.assertEqual(status, "succeeded")
        self.assertEqual(bronze_count, 1)

    def test_no_attempt_is_written_before_extraction_finishes(self):
        def inspect_during_extraction(**kwargs):
            attempt_count = self.conn.execute(
                "SELECT count(*) FROM ops.pipeline_attempts"
            ).fetchone()[0]
            self.assertEqual(attempt_count, 0)
            return successful_extraction(**kwargs)

        run_bronze_pipeline(
            self.conn,
            self.config,
            RunMetadata("run-1", 1),
            extractor=inspect_during_extraction,
        )

    def test_extraction_failure_records_failure_without_bronze(self):
        def failing_extractor(**kwargs):
            raise ExtractionError("source-secret was rejected " + ("x" * 3_000))

        with self.assertRaises(ExtractionError):
            run_bronze_pipeline(
                self.conn,
                self.config,
                RunMetadata("run-1", 1),
                extractor=failing_extractor,
            )

        attempt = self.conn.execute(
            """
            SELECT attempt_status, error_stage, error_type, error_message
            FROM ops.pipeline_attempts
            """
        ).fetchone()
        bronze_count = self.conn.execute(
            "SELECT count(*) FROM bronze.raw_issue_extractions"
        ).fetchone()[0]
        self.assertEqual(attempt[0], "failed")
        self.assertEqual(attempt[1], "extraction")
        self.assertEqual(attempt[2], "ExtractionError")
        self.assertNotIn("source-secret", attempt[3])
        self.assertEqual(len(attempt[3]), 2_000)
        self.assertEqual(bronze_count, 0)

    def test_load_failure_records_failure_without_partial_bronze(self):
        def unserializable_extraction(**kwargs):
            return Extraction(
                run_id=kwargs["run_id"],
                attempt_number=kwargs["attempt_number"],
                extracted_at=datetime.now(timezone.utc),
                payload={"bad": object()},
            )

        with self.assertRaises(TypeError):
            run_bronze_pipeline(
                self.conn,
                self.config,
                RunMetadata("run-1", 1),
                extractor=unserializable_extraction,
            )

        status, error_stage = self.conn.execute(
            "SELECT attempt_status, error_stage FROM ops.pipeline_attempts"
        ).fetchone()
        bronze_count = self.conn.execute(
            "SELECT count(*) FROM bronze.raw_issue_extractions"
        ).fetchone()[0]
        self.assertEqual(status, "failed")
        self.assertEqual(error_stage, "bronze_load")
        self.assertEqual(bronze_count, 0)

    def test_same_attempt_is_idempotent_after_success(self):
        extractor = Mock(side_effect=successful_extraction)
        metadata = RunMetadata("run-1", 1)

        run_bronze_pipeline(
            self.conn,
            self.config,
            metadata,
            extractor=extractor,
        )
        second_result = run_bronze_pipeline(
            self.conn,
            self.config,
            metadata,
            extractor=extractor,
        )

        self.assertIsNone(second_result)
        self.assertEqual(extractor.call_count, 1)
        count = self.conn.execute(
            "SELECT count(*) FROM bronze.raw_issue_extractions"
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_failed_attempt_is_immutable_when_same_attempt_is_reused(self):
        failing_extractor = Mock(side_effect=ExtractionError("temporary failure"))
        metadata = RunMetadata("run-1", 1)

        with self.assertRaises(ExtractionError):
            run_bronze_pipeline(
                self.conn,
                self.config,
                metadata,
                extractor=failing_extractor,
            )

        successful_extractor = Mock(side_effect=successful_extraction)
        second_result = run_bronze_pipeline(
            self.conn,
            self.config,
            metadata,
            extractor=successful_extractor,
        )

        status = self.conn.execute(
            "SELECT attempt_status FROM ops.pipeline_attempts"
        ).fetchone()[0]
        bronze_count = self.conn.execute(
            "SELECT count(*) FROM bronze.raw_issue_extractions"
        ).fetchone()[0]
        self.assertIsNone(second_result)
        self.assertEqual(status, "failed")
        self.assertEqual(bronze_count, 0)
        successful_extractor.assert_not_called()

    def test_higher_successful_attempt_becomes_canonical(self):
        def failing_extractor(**kwargs):
            raise ExtractionError("temporary failure")

        with self.assertRaises(ExtractionError):
            run_bronze_pipeline(
                self.conn,
                self.config,
                RunMetadata("run-1", 1),
                extractor=failing_extractor,
            )

        run_bronze_pipeline(
            self.conn,
            self.config,
            RunMetadata("run-1", 2),
            extractor=successful_extraction,
        )

        attempts = self.conn.execute(
            """
            SELECT attempt_number, attempt_status
            FROM ops.pipeline_attempts
            ORDER BY attempt_number
            """
        ).fetchall()
        canonical = extract_canonical_bronze(self.conn)
        self.assertEqual(attempts, [(1, "failed"), (2, "succeeded")])
        self.assertEqual(canonical["attempt_number"].tolist(), [2])

    def test_canonical_selection_uses_highest_of_two_successes(self):
        run_bronze_pipeline(
            self.conn,
            self.config,
            RunMetadata("run-1", 1),
            extractor=successful_extraction,
        )
        run_bronze_pipeline(
            self.conn,
            self.config,
            RunMetadata("run-1", 2),
            extractor=successful_extraction,
        )

        bronze_count = self.conn.execute(
            "SELECT count(*) FROM bronze.raw_issue_extractions"
        ).fetchone()[0]
        canonical = extract_canonical_bronze(self.conn)
        self.assertEqual(bronze_count, 2)
        self.assertEqual(canonical["attempt_number"].tolist(), [2])


if __name__ == "__main__":
    unittest.main()
