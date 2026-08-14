from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, Mock, patch

import duckdb
import pandas as pd

import pipeline.__main__ as entrypoint
from pipeline.etl.bronze import run_bronze, should_run_bronze
from pipeline.etl.errors import ExtractionError
from pipeline.etl.load import (
    create_pipeline_tables,
    extract_canonical_bronze,
    extract_pending_canonical_bronze,
    load_failed_attempt,
    load_successful_extraction_to_bronze,
    record_failure_safely,
)
from pipeline.models import (
    AttemptStatus,
    Extraction,
    LocalConfig,
    MotherDuckConfig,
    PipelineAttempt,
    RunMetadata,
    SourceConfig,
)


def test_source_config() -> SourceConfig:
    return SourceConfig(
        token="source-secret",
        owner_name="example-owner",
        owner_type="organization",
        project_number=1,
    )


def make_extraction(
    metadata: RunMetadata,
    payload: dict | None = None,
) -> Extraction:
    return Extraction(
        run_id=metadata.run_id,
        attempt_number=metadata.attempt_number,
        extracted_at=datetime.now(timezone.utc),
        payload=payload or {"pages": [{"data": {"example": True}}]},
    )


def make_attempt(
    metadata: RunMetadata,
    status: AttemptStatus = AttemptStatus.SUCCEEDED,
    *,
    error_stage: str | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> PipelineAttempt:
    started_at = datetime.now(timezone.utc)
    return PipelineAttempt(
        run_id=metadata.run_id,
        attempt_number=metadata.attempt_number,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc),
        attempt_status=status,
        error_stage=error_stage,
        error_type=error_type,
        error_message=error_message,
    )


class BronzeComponentTests(unittest.TestCase):
    def setUp(self):
        self.conn = duckdb.connect(":memory:")
        create_pipeline_tables(self.conn)
        self.logger = Mock()

    def tearDown(self):
        self.conn.close()

    def test_should_run_bronze_returns_true_for_new_attempt(self):
        should_run = should_run_bronze(
            self.conn,
            RunMetadata("run-1", 1),
            self.logger,
        )

        self.assertTrue(should_run)
        self.logger.info.assert_not_called()

    def test_should_run_bronze_returns_false_for_successful_attempt(self):
        metadata = RunMetadata("run-1", 1)
        load_successful_extraction_to_bronze(
            self.conn,
            make_extraction(metadata),
            make_attempt(metadata),
        )

        should_run = should_run_bronze(self.conn, metadata, self.logger)

        self.assertFalse(should_run)
        self.logger.info.assert_called_once()

    def test_should_run_bronze_returns_false_for_failed_attempt(self):
        metadata = RunMetadata("run-1", 1)
        load_failed_attempt(
            self.conn,
            make_attempt(
                metadata,
                AttemptStatus.FAILED,
                error_stage="extraction",
                error_type="ExtractionError",
                error_message="temporary failure",
            ),
        )

        should_run = should_run_bronze(self.conn, metadata, self.logger)

        self.assertFalse(should_run)

    def test_run_bronze_prepares_matching_successful_models(self):
        metadata = RunMetadata("run-1", 1)
        extraction = make_extraction(metadata)

        attempt, extraction_row = run_bronze(
            metadata,
            extraction,
            datetime.now(timezone.utc),
        )

        self.assertEqual(
            (attempt.run_id, attempt.attempt_number),
            (extraction_row.run_id, extraction_row.attempt_number),
        )
        self.assertIs(attempt.attempt_status, AttemptStatus.SUCCEEDED)
        self.assertIsInstance(attempt.started_at, datetime)
        self.assertIsNotNone(attempt.started_at.utcoffset())
        self.assertIsInstance(attempt.completed_at, datetime)
        self.assertIsNotNone(attempt.completed_at.utcoffset())
        self.assertIsNone(attempt.error_stage)
        self.assertIsNone(attempt.error_type)
        self.assertIsNone(attempt.error_message)

    def test_success_loads_bronze_and_attempt_atomically(self):
        metadata = RunMetadata("run-1", 1)

        load_successful_extraction_to_bronze(
            self.conn,
            make_extraction(metadata),
            make_attempt(metadata),
        )

        status = self.conn.execute(
            "SELECT attempt_status FROM ops.pipeline_attempts"
        ).fetchone()[0]
        bronze_count = self.conn.execute(
            "SELECT count(*) FROM bronze.raw_issue_extractions"
        ).fetchone()[0]
        self.assertEqual(status, "succeeded")
        self.assertEqual(bronze_count, 1)

        timestamps = self.conn.execute(
            "SELECT started_at, completed_at FROM ops.pipeline_attempts"
        ).fetchone()
        extracted_at = self.conn.execute(
            "SELECT extracted_at FROM bronze.raw_issue_extractions"
        ).fetchone()[0]
        for timestamp in (*timestamps, extracted_at):
            self.assertIsInstance(timestamp, datetime)
            self.assertIsNotNone(timestamp.utcoffset())

    def test_failed_extraction_attempt_has_no_bronze_row(self):
        metadata = RunMetadata("run-1", 1)
        load_failed_attempt(
            self.conn,
            make_attempt(
                metadata,
                AttemptStatus.FAILED,
                error_stage="extraction",
                error_type="ExtractionError",
                error_message="temporary failure",
            ),
        )

        attempt = self.conn.execute(
            "SELECT attempt_status, error_stage FROM ops.pipeline_attempts"
        ).fetchone()
        bronze_count = self.conn.execute(
            "SELECT count(*) FROM bronze.raw_issue_extractions"
        ).fetchone()[0]
        self.assertEqual(attempt, ("failed", "extraction"))
        self.assertEqual(bronze_count, 0)

    def test_failure_sanitization_uses_explicit_secrets_and_limit(self):
        metadata = RunMetadata("run-1", 1)
        error = ExtractionError("source-secret " + ("x" * 100))

        record_failure_safely(
            self.conn,
            metadata,
            started_at=datetime.now(timezone.utc),
            stage="extraction",
            error=error,
            secrets=["source-secret"],
            max_error_message=20,
            logger=self.logger,
        )

        message = self.conn.execute(
            "SELECT error_message FROM ops.pipeline_attempts"
        ).fetchone()[0]
        self.assertNotIn("source-secret", message)
        self.assertEqual(len(message), 20)

    def test_load_failure_leaves_no_partial_success(self):
        metadata = RunMetadata("run-1", 1)
        extraction = make_extraction(metadata, {"bad": object()})

        with self.assertRaises(TypeError):
            load_successful_extraction_to_bronze(
                self.conn,
                extraction,
                make_attempt(metadata),
            )

        attempt_count = self.conn.execute(
            "SELECT count(*) FROM ops.pipeline_attempts"
        ).fetchone()[0]
        bronze_count = self.conn.execute(
            "SELECT count(*) FROM bronze.raw_issue_extractions"
        ).fetchone()[0]
        self.assertEqual(attempt_count, 0)
        self.assertEqual(bronze_count, 0)

    def test_higher_successful_attempt_is_canonical(self):
        failed_metadata = RunMetadata("run-1", 1)
        successful_metadata = RunMetadata("run-1", 2)
        load_failed_attempt(
            self.conn,
            make_attempt(
                failed_metadata,
                AttemptStatus.FAILED,
                error_stage="extraction",
                error_type="ExtractionError",
                error_message="temporary failure",
            ),
        )
        load_successful_extraction_to_bronze(
            self.conn,
            make_extraction(successful_metadata),
            make_attempt(successful_metadata),
        )

        canonical = extract_canonical_bronze(self.conn)

        self.assertEqual(canonical["attempt_number"].tolist(), [2])

    def test_pending_canonical_bronze_returns_decoded_latest_attempts(self):
        load_successful_extraction_to_bronze(
            self.conn,
            make_extraction(
                RunMetadata("already-loaded", 1),
                {"pages": [{"run": "already-loaded"}]},
            ),
            make_attempt(RunMetadata("already-loaded", 1)),
        )
        self.conn.execute(
            """
            INSERT INTO silver.issue_submissions (
                run_id,
                issue_id,
                issue_title,
                issue_url,
                issue_author,
                created_at,
                updated_at,
                state,
                reviewer,
                milestone,
                status,
                extracted_at,
                is_assigned,
                days_since_update,
                submission_age_days,
                current_milestone,
                builder_status
            )
            VALUES (
                'already-loaded',
                'issue-1',
                '[M1] Example',
                'https://example.com/issue-1',
                'builder',
                now(),
                now(),
                'OPEN',
                [],
                'M1',
                'Passed',
                now(),
                false,
                0,
                0,
                'M2',
                'active'
            )
            """
        )
        for attempt_number in (1, 2):
            metadata = RunMetadata("retried", attempt_number)
            load_successful_extraction_to_bronze(
                self.conn,
                make_extraction(
                    metadata,
                    {"pages": [{"attempt": attempt_number}]},
                ),
                make_attempt(metadata),
            )
        pending_metadata = RunMetadata("pending", 1)
        load_successful_extraction_to_bronze(
            self.conn,
            make_extraction(
                pending_metadata,
                {"pages": [{"run": "pending"}]},
            ),
            make_attempt(pending_metadata),
        )
        failed_metadata = RunMetadata("failed", 1)
        load_failed_attempt(
            self.conn,
            make_attempt(
                failed_metadata,
                AttemptStatus.FAILED,
                error_stage="extraction",
                error_type="ExtractionError",
                error_message="temporary failure",
            ),
        )

        pending = extract_pending_canonical_bronze(self.conn)

        self.assertEqual(
            [(row.run_id, row.attempt_number) for row in pending],
            [("pending", 1), ("retried", 2)],
        )
        self.assertEqual(pending[0].payload, {"pages": [{"run": "pending"}]})
        self.assertEqual(pending[1].payload, {"pages": [{"attempt": 2}]})


class MainOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.source_config = test_source_config()
        self.metadata = RunMetadata("run-1", 1)
        self.conn = Mock()
        self.connection_context = MagicMock()
        self.connection_context.__enter__.return_value = self.conn
        self.connection_factory = Mock(return_value=self.connection_context)

    def test_local_fixture_runs_without_source_config(self):
        captured_payloads: list[dict] = []

        def transform(metadata, extraction, started_at):
            captured_payloads.append(extraction.payload)
            return make_attempt(metadata), extraction

        with TemporaryDirectory() as temp_dir:
            sample_path = Path(temp_dir) / "sample.json"
            sample_path.write_text('{"pages": [{"local": true}]}', encoding="utf-8")

            with (
                patch.object(
                    entrypoint,
                    "resolve_run_metadata",
                    return_value=self.metadata,
                ),
                patch.object(entrypoint, "create_pipeline_tables"),
                patch.object(entrypoint, "should_run_bronze", return_value=True),
                patch.object(entrypoint, "extract_submissions") as extractor,
                patch.object(entrypoint, "run_bronze", side_effect=transform),
                patch.object(entrypoint, "load_successful_extraction_to_bronze"),
            ):
                entrypoint._run(
                    self.connection_factory,
                    None,
                    sample_data_path=sample_path,
                )

        extractor.assert_not_called()
        self.assertEqual(captured_payloads, [{"pages": [{"local": True}]}])

    def test_main_initializes_remote_configuration_once(self):
        motherduck_config = MotherDuckConfig(
            database_path="md:example",
            token="motherduck-secret",
        )

        with (
            patch.object(
                entrypoint,
                "init_source_config",
                return_value=self.source_config,
            ) as init_source,
            patch.object(
                entrypoint,
                "init_motherduck_config",
                return_value=motherduck_config,
            ) as init_motherduck,
            patch.object(entrypoint, "_run") as run,
        ):
            entrypoint.main()

        init_source.assert_called_once_with()
        init_motherduck.assert_called_once_with()
        self.assertIs(run.call_args.args[1], self.source_config)
        self.assertEqual(
            run.call_args.kwargs["error_secrets"],
            [self.source_config.token, motherduck_config.token],
        )

    def test_local_dev_initializes_no_source_configuration(self):
        local_config = LocalConfig(
            duckdb_path=Path(":memory:"),
            sample_data_path=Path("sample.json"),
        )

        with (
            patch("sys.argv", ["dep-pipeline-dev", "--local"]),
            patch.object(
                entrypoint,
                "init_local_config",
                return_value=local_config,
            ) as init_local,
            patch.object(entrypoint, "init_source_config") as init_source,
            patch.object(entrypoint, "_run") as run,
        ):
            entrypoint.dev()

        init_local.assert_called_once_with()
        init_source.assert_not_called()
        self.assertIsNone(run.call_args.args[1])
        self.assertEqual(
            run.call_args.kwargs["sample_data_path"],
            local_config.sample_data_path,
        )

    def test_existing_attempt_stops_before_extraction(self):
        with (
            patch.object(
                entrypoint,
                "resolve_run_metadata",
                return_value=self.metadata,
            ),
            patch.object(entrypoint, "create_pipeline_tables"),
            patch.object(entrypoint, "should_run_bronze", return_value=False),
            patch.object(entrypoint, "extract_submissions") as extractor,
            patch.object(entrypoint, "run_bronze") as bronze_transform,
            patch.object(entrypoint, "load_successful_extraction_to_bronze") as loader,
        ):
            entrypoint._run(
                self.connection_factory,
                self.source_config,
                error_secrets=[self.source_config.token],
            )

        extractor.assert_not_called()
        bronze_transform.assert_not_called()
        loader.assert_not_called()

    def test_new_attempt_runs_preflight_extract_transform_load_in_order(self):
        events: list[str] = []
        extraction = make_extraction(self.metadata)
        attempt = make_attempt(self.metadata)

        def create_tables(conn):
            events.append("create_tables")

        def preflight(conn, metadata, logger):
            events.append("preflight")
            return True

        def extract(*args):
            events.append("extract")
            return extraction

        def transform(metadata, extraction_row, started_at):
            events.append("transform")
            return attempt, extraction_row

        def load(conn, extraction_row, attempt_row):
            events.append("load")

        with (
            patch.object(
                entrypoint,
                "resolve_run_metadata",
                return_value=self.metadata,
            ),
            patch.object(entrypoint, "create_pipeline_tables", side_effect=create_tables),
            patch.object(entrypoint, "should_run_bronze", side_effect=preflight),
            patch.object(entrypoint, "extract_submissions", side_effect=extract),
            patch.object(entrypoint, "run_bronze", side_effect=transform),
            patch.object(
                entrypoint,
                "load_successful_extraction_to_bronze",
                side_effect=load,
            ),
        ):
            entrypoint._run(
                self.connection_factory,
                self.source_config,
                error_secrets=[self.source_config.token],
            )

        self.assertEqual(
            events,
            ["create_tables", "preflight", "extract", "transform", "load"],
        )

    def test_extraction_error_is_recorded_and_reraised(self):
        extraction_error = ExtractionError("temporary failure")

        with (
            patch.object(
                entrypoint,
                "resolve_run_metadata",
                return_value=self.metadata,
            ),
            patch.object(entrypoint, "create_pipeline_tables"),
            patch.object(entrypoint, "should_run_bronze", return_value=True),
            patch.object(
                entrypoint,
                "extract_submissions",
                side_effect=extraction_error,
            ),
            patch.object(entrypoint, "record_failure_safely") as record_failure,
        ):
            with self.assertRaises(ExtractionError):
                entrypoint._run(
                    self.connection_factory,
                    self.source_config,
                    error_secrets=[self.source_config.token],
                )

        self.assertEqual(record_failure.call_args.kwargs["stage"], "extraction")
        self.assertIs(record_failure.call_args.kwargs["error"], extraction_error)

    def test_load_error_is_recorded_and_reraised(self):
        extraction = make_extraction(self.metadata)
        attempt = make_attempt(self.metadata)
        load_error = TypeError("payload cannot be loaded")

        with (
            patch.object(
                entrypoint,
                "resolve_run_metadata",
                return_value=self.metadata,
            ),
            patch.object(entrypoint, "create_pipeline_tables"),
            patch.object(entrypoint, "should_run_bronze", return_value=True),
            patch.object(
                entrypoint,
                "extract_submissions",
                return_value=extraction,
            ),
            patch.object(
                entrypoint,
                "run_bronze",
                return_value=(attempt, extraction),
            ),
            patch.object(
                entrypoint,
                "load_successful_extraction_to_bronze",
                side_effect=load_error,
            ),
            patch.object(entrypoint, "record_failure_safely") as record_failure,
        ):
            with self.assertRaises(TypeError):
                entrypoint._run(
                    self.connection_factory,
                    self.source_config,
                    error_secrets=[self.source_config.token],
                )

        self.assertEqual(record_failure.call_args.kwargs["stage"], "bronze_load")
        self.assertIs(record_failure.call_args.kwargs["error"], load_error)


class SilverOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.conn = Mock()
        self.connection_context = MagicMock()
        self.connection_context.__enter__.return_value = self.conn
        self.connection_factory = Mock(return_value=self.connection_context)
        self.first = make_extraction(RunMetadata("run-1", 1))
        self.second = make_extraction(RunMetadata("run-2", 1))

    def test_pending_runs_transform_and_load_in_order(self):
        events: list[str] = []

        with (
            patch.object(
                entrypoint,
                "create_pipeline_tables",
                side_effect=lambda conn: events.append("create_tables"),
            ),
            patch.object(
                entrypoint,
                "extract_pending_canonical_bronze",
                side_effect=lambda conn: (
                    events.append("extract_pending") or [self.first, self.second]
                ),
            ),
            patch.object(
                entrypoint,
                "transform_extraction_to_silver",
                side_effect=lambda extraction: (
                    events.append(f"transform:{extraction.run_id}")
                    or pd.DataFrame({"run_id": [extraction.run_id]})
                ),
            ),
            patch.object(
                entrypoint,
                "load_silver",
                side_effect=lambda conn, df: events.append(
                    f"load:{df.iloc[0]['run_id']}"
                ),
            ),
        ):
            entrypoint._run_pending_silver(self.connection_factory)

        self.assertEqual(
            events,
            [
                "create_tables",
                "extract_pending",
                "transform:run-1",
                "load:run-1",
                "transform:run-2",
                "load:run-2",
            ],
        )

    def test_no_pending_runs_exits_without_transforming(self):
        with (
            patch.object(entrypoint, "create_pipeline_tables"),
            patch.object(
                entrypoint,
                "extract_pending_canonical_bronze",
                return_value=[],
            ),
            patch.object(entrypoint, "transform_extraction_to_silver") as transform,
            patch.object(entrypoint, "load_silver") as load,
            patch.object(entrypoint.logger, "info") as log,
        ):
            entrypoint._run_pending_silver(self.connection_factory)

        transform.assert_not_called()
        load.assert_not_called()
        log.assert_called_once_with("No pending Bronze runs to load into Silver")

    def test_transform_error_is_logged_and_reraised(self):
        error = ValueError("invalid Bronze payload")

        with (
            patch.object(entrypoint, "create_pipeline_tables"),
            patch.object(
                entrypoint,
                "extract_pending_canonical_bronze",
                return_value=[self.first, self.second],
            ),
            patch.object(
                entrypoint,
                "transform_extraction_to_silver",
                side_effect=error,
            ) as transform,
            patch.object(entrypoint, "load_silver") as load,
            patch.object(entrypoint.logger, "exception") as log_exception,
        ):
            with self.assertRaises(ValueError):
                entrypoint._run_pending_silver(self.connection_factory)

        transform.assert_called_once_with(self.first)
        load.assert_not_called()
        log_exception.assert_called_once()

    def test_load_error_is_logged_and_reraised(self):
        error = duckdb.ConstraintException("duplicate Silver row")
        silver_df = pd.DataFrame({"run_id": ["run-1"]})

        with (
            patch.object(entrypoint, "create_pipeline_tables"),
            patch.object(
                entrypoint,
                "extract_pending_canonical_bronze",
                return_value=[self.first, self.second],
            ),
            patch.object(
                entrypoint,
                "transform_extraction_to_silver",
                return_value=silver_df,
            ) as transform,
            patch.object(entrypoint, "load_silver", side_effect=error) as load,
            patch.object(entrypoint.logger, "exception") as log_exception,
        ):
            with self.assertRaises(duckdb.ConstraintException):
                entrypoint._run_pending_silver(self.connection_factory)

        transform.assert_called_once_with(self.first)
        load.assert_called_once_with(self.conn, silver_df)
        log_exception.assert_called_once()

    def test_silver_command_uses_motherduck_connection(self):
        motherduck_config = MotherDuckConfig(
            database_path="md:example",
            token="motherduck-secret",
        )
        connection = Mock()

        with (
            patch.object(
                entrypoint,
                "init_motherduck_config",
                return_value=motherduck_config,
            ) as init_motherduck,
            patch.object(
                entrypoint,
                "get_database_connection",
                return_value=connection,
            ) as get_connection,
            patch.object(entrypoint, "_run_pending_silver") as run,
        ):
            entrypoint.silver()

            connection_factory = run.call_args.args[0]
            self.assertIs(connection_factory(), connection)

        init_motherduck.assert_called_once_with()
        get_connection.assert_called_once_with(motherduck_config)


if __name__ == "__main__":
    unittest.main()
