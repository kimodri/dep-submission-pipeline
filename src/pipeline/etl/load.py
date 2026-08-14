import json, duckdb
import pandas as pd
from datetime import datetime, timezone

from pipeline.models import (
    AttemptStatus, 
    Extraction, 
    PipelineAttempt,
    RunMetadata
) 

_SILVER_COLUMNS = frozenset(
    {
        "issue_id",
        "issue_title",
        "issue_url",
        "issue_author",
        "created_at",
        "updated_at",
        "state",
        "reviewer",
        "milestone",
        "status",
        "run_id",
        "extracted_at",
        "is_assigned",
        "days_since_update",
        "submission_age_days",
        "current_milestone",
        "builder_status",
    }
)

def _safe_error_message(
    error: Exception,
    secrets: list[str | None],
    max_length: int,
) -> str:
    message = str(error)
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[REDACTED]")
    return message[:max_length]

def create_pipeline_tables(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE SCHEMA IF NOT EXISTS ops;
        CREATE SCHEMA IF NOT EXISTS bronze;
        CREATE SCHEMA IF NOT EXISTS silver;

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

        CREATE TABLE IF NOT EXISTS silver.issue_submissions (
            run_id VARCHAR NOT NULL,
            issue_id VARCHAR NOT NULL,
            issue_title VARCHAR NOT NULL,
            issue_url VARCHAR NOT NULL,
            issue_author VARCHAR,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            state VARCHAR NOT NULL,
            reviewer VARCHAR[] NOT NULL,
            milestone VARCHAR NOT NULL,
            status VARCHAR,
            extracted_at TIMESTAMPTZ NOT NULL,
            is_assigned BOOLEAN NOT NULL,
            days_since_update BIGINT NOT NULL,
            submission_age_days BIGINT NOT NULL,
            current_milestone VARCHAR NOT NULL,
            builder_status VARCHAR CHECK (
                builder_status IS NULL
                OR builder_status IN ('active', 'delayed')
            ),
            PRIMARY KEY (run_id, issue_id)
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
    metadata: RunMetadata,
    started_at: datetime,
    stage: str,
    error: Exception,
    secrets: list[str | None],
    max_error_message: int,
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
                    secrets,
                    max_error_message,
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
def load_silver(
    conn: duckdb.DuckDBPyConnection,
    df: pd.DataFrame,
) -> None:
    columns = list(df.columns)
    actual_columns = set(columns)
    missing_columns = sorted(_SILVER_COLUMNS - actual_columns)
    unexpected_columns = sorted(actual_columns - _SILVER_COLUMNS)
    duplicate_columns = sorted(
        column for column in actual_columns if columns.count(column) > 1
    )

    if missing_columns or unexpected_columns or duplicate_columns:
        problems = []
        if missing_columns:
            problems.append(f"missing columns: {missing_columns}")
        if unexpected_columns:
            problems.append(f"unexpected columns: {unexpected_columns}")
        if duplicate_columns:
            problems.append(f"duplicate columns: {duplicate_columns}")
        raise ValueError(
            "Silver DataFrame does not match issue_submissions schema ("
            + "; ".join(problems)
            + ")"
        )

    conn.register("incoming_silver", df)
    try:
        conn.execute(
            """
            INSERT INTO silver.issue_submissions BY NAME
            SELECT * FROM incoming_silver
            """
        )
    finally:
        conn.unregister("incoming_silver")

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

def extract_pending_canonical_bronze(
    conn: duckdb.DuckDBPyConnection,
) -> list[Extraction]:
    rows = conn.execute(
        """
        WITH canonical_bronze AS (
            SELECT b.*
            FROM bronze.raw_issue_extractions AS b
            JOIN ops.pipeline_attempts AS a
              USING (run_id, attempt_number)
            WHERE a.attempt_status = 'succeeded'
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY b.run_id
                ORDER BY b.attempt_number DESC
            ) = 1
        )
        SELECT
            c.run_id,
            c.attempt_number,
            c.extracted_at,
            c.payload
        FROM canonical_bronze AS c
        WHERE NOT EXISTS (
            SELECT 1
            FROM silver.issue_submissions AS s
            WHERE s.run_id = c.run_id
        )
        ORDER BY c.run_id
        """
    ).fetchall()

    pending_extractions = []
    for run_id, attempt_number, extracted_at, payload in rows:
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            raise TypeError(
                f"Bronze payload for run_id={run_id} must decode to a dictionary"
            )
        pending_extractions.append(
            Extraction(
                run_id=run_id,
                attempt_number=attempt_number,
                extracted_at=extracted_at,
                payload=payload,
            )
        )

    return pending_extractions

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
