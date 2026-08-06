import json, duckdb, os
from datetime import datetime, timezone

from pipeline import init_config
from pipeline.models import (
    AttemptStatus, 
    Extraction, 
    PipelineAttempt,
    Config,
    RunMetadata
) 

def _safe_error_message(error: Exception, secrets: list[str | None]) -> str:
    config = init_config()
    message = str(error)
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[REDACTED]")
    return message[:config.max_error_message]

def create_pipeline_tables(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE SCHEMA IF NOT EXISTS ops;
        CREATE SCHEMA IF NOT EXISTS bronze;

        CREATE TABLE IF NOT EXISTS ops.pipeline_attempts (
            run_id VARCHAR NOT NULL,
            attempt_number INTEGER NOT NULL,
            started_at TIMESTAMPTZ NOT NULL,
            completed_at TIMESTAMPTZ NOT NULL,
            attempt_status VARCHAR NOT NULL CHECK (
                attempt_status IN ('succeeded', 'failed')
            ),
            error_stage VARCHAR CHECK (
                error_stage IS NULL OR error_stage IN ('extraction', 'bronze_load', 'silver_load', 'gold_load')
            ),
            error_type VARCHAR,
            error_message VARCHAR,
            CHECK (
                (attempt_status = 'succeeded'
                    AND error_stage IS NULL
                    AND error_type IS NULL
                    AND error_message IS NULL)
                OR
                (attempt_status = 'failed'
                    AND error_stage IS NOT NULL
                    AND error_type IS NOT NULL
                    AND error_message IS NOT NULL)
            ),
            PRIMARY KEY (run_id, attempt_number)
        );

        CREATE TABLE IF NOT EXISTS bronze.raw_issue_extractions (
            run_id VARCHAR NOT NULL,
            attempt_number INTEGER NOT NULL,
            extracted_at TIMESTAMPTZ NOT NULL,
            payload JSON NOT NULL,
            PRIMARY KEY (run_id, attempt_number)
        );
        """
    )

def attempt_exists(
    conn: duckdb.DuckDBPyConnection,
    run_id: str,
    attempt_number: int,
) -> bool:
    
    # Return whether this immutable terminal attempt has already been recorded.
    
    return conn.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM ops.pipeline_attempts
            WHERE run_id = ?
              AND attempt_number = ?
        )
        """,
        [run_id, attempt_number],
    ).fetchone()[0]

def load_failed_attempt(
    conn: duckdb.DuckDBPyConnection,
    attempt: PipelineAttempt,
) -> None:
    if attempt.attempt_status is not AttemptStatus.FAILED:
        raise ValueError("load_failed_attempt requires a failed attempt")
    if (
        not attempt.error_stage
        or not attempt.error_type
        or attempt.error_message is None
    ):
        raise ValueError("A failed attempt requires failure diagnostics")

    conn.execute(
        """
        INSERT INTO ops.pipeline_attempts (
            run_id,
            attempt_number,
            started_at,
            completed_at,
            attempt_status,
            error_stage,
            error_type,
            error_message
        )
        VALUES (?, ?, ?, ?, 'failed', ?, ?, ?)
        ON CONFLICT (run_id, attempt_number) DO NOTHING
        """,
        [
            attempt.run_id,
            attempt.attempt_number,
            attempt.started_at,
            attempt.completed_at,
            attempt.error_stage,
            attempt.error_type,
            attempt.error_message,
        ],
    )

def record_failure_safely(
    conn: duckdb.DuckDBPyConnection,
    config: Config,
    metadata: RunMetadata,
    started_at: datetime,
    stage: str,
    error: Exception,
    logger
) -> None:
    try:
        load_failed_attempt(
            conn,
            PipelineAttempt(
                run_id=metadata.run_id,
                attempt_number=metadata.attempt_number,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                attempt_status=AttemptStatus.FAILED,
                error_stage=stage,
                error_type=type(error).__name__,
                error_message=_safe_error_message(
                    error,
                    [config.token, os.getenv("MOTHERDUCK_TOKEN")],
                ),
            ),
        )
    except Exception:
        logger.exception(
            "Could not persist failure for Bronze attempt %s/%s",
            metadata.run_id,
            metadata.attempt_number,
        )

# For Bronze
def load_successful_extraction_to_bronze(
    conn: duckdb.DuckDBPyConnection,
    extraction: Extraction,
    attempt: PipelineAttempt,
) -> None:
    if attempt.attempt_status is not AttemptStatus.SUCCEEDED:
        raise ValueError("load_successful_extraction requires a succeeded attempt")
    if (extraction.run_id, extraction.attempt_number) != (
        attempt.run_id,
        attempt.attempt_number,
    ):
        raise ValueError("Extraction and attempt metadata do not match")

    serialized_payload = json.dumps(
        extraction.payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    conn.execute("BEGIN")
    try:
        conn.execute(
            """
            INSERT INTO bronze.raw_issue_extractions (
                run_id,
                attempt_number,
                extracted_at,
                payload
            )
            VALUES (?, ?, ?, ?)
            """,
            [
                extraction.run_id,
                extraction.attempt_number,
                extraction.extracted_at,
                serialized_payload,
            ],
        )
        conn.execute(
            """
            INSERT INTO ops.pipeline_attempts (
                run_id,
                attempt_number,
                started_at,
                completed_at,
                attempt_status,
                error_stage,
                error_type,
                error_message
            )
            VALUES (?, ?, ?, ?, 'succeeded', NULL, NULL, NULL)
            """,
            [
                attempt.run_id,
                attempt.attempt_number,
                attempt.started_at,
                attempt.completed_at,
            ],
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

# For Silver
def extract_canonical_bronze(conn: duckdb.DuckDBPyConnection):
    """Return the future Silver input: latest succeeded attempt per run."""
    return conn.execute(
        """
        SELECT b.*
        FROM bronze.raw_issue_extractions AS b
        JOIN ops.pipeline_attempts AS a
          USING (run_id, attempt_number)
        WHERE a.attempt_status = 'succeeded'
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY b.run_id
            ORDER BY b.attempt_number DESC
        ) = 1
        ORDER BY b.run_id
        """
    ).df()

def extract_bronze_submission(
    conn: duckdb.DuckDBPyConnection,
    run_id: str,
    attempt_number: int,
):
    return conn.execute(
        """
        SELECT *
        FROM bronze.raw_issue_extractions
        WHERE run_id = ? AND attempt_number = ?
        """,
        [run_id, attempt_number],
    ).df()
