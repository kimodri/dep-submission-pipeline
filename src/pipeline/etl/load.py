import json, duckdb
import pandas as pd
from datetime import datetime, timezone

from pipeline.models import (
    AttemptStatus, 
    Extraction, 
    PipelineAttempt,
    RunMetadata
) 

_SILVER_COLUMN_ORDER = (
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
)
_SILVER_COLUMNS = frozenset(_SILVER_COLUMN_ORDER)

_GOLD_DIMENSIONS = {
    "dim_issue": {
        "key": "issue_key",
        "natural_key": "issue_id",
        "columns": ["issue_id", "issue_title", "issue_url", "issue_author"],
        "updates": ["issue_title", "issue_url", "issue_author"],
    },
    "dim_reviewer": {
        "key": "reviewer_key",
        "natural_key": "reviewer",
        "columns": ["reviewer"],
        "updates": [],
    },
    "dim_state": {
        "key": "state_key",
        "natural_key": "state",
        "columns": ["state"],
        "updates": [],
    },
    "dim_status": {
        "key": "status_key",
        "natural_key": "status",
        "columns": ["status"],
        "updates": [],
    },
    "dim_milestone": {
        "key": "milestone_key",
        "natural_key": "milestone",
        "columns": ["milestone", "milestone_number", "deadline_date"],
        "updates": ["milestone_number", "deadline_date"],
    },
    "dim_date": {
        "key": "date_key",
        "natural_key": "date",
        "columns": ["date", "year", "month", "month_name", "day", "day_name"],
        "updates": [],
    },
}

_GOLD_FACT_COLUMN_ORDER = (
    "submission_snapshot_key",
    "run_id",
    "issue_key",
    "state_key",
    "status_key",
    "milestone_key",
    "created_at_key",
    "updated_at_key",
    "extracted_at_key",
    "created_at",
    "updated_at",
    "extracted_at",
    "is_assigned",
    "days_since_update",
    "submission_age_days",
)
_GOLD_FACT_COLUMNS = frozenset(_GOLD_FACT_COLUMN_ORDER)
_GOLD_BRIDGE_COLUMN_ORDER = (
    "submission_snapshot_key",
    "reviewer_key",
)
_GOLD_BRIDGE_COLUMNS = frozenset(_GOLD_BRIDGE_COLUMN_ORDER)

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
        CREATE SCHEMA IF NOT EXISTS gold;

        CREATE SEQUENCE IF NOT EXISTS gold.issue_key_seq START 1;
        CREATE SEQUENCE IF NOT EXISTS gold.reviewer_key_seq START 1;
        CREATE SEQUENCE IF NOT EXISTS gold.state_key_seq START 1;
        CREATE SEQUENCE IF NOT EXISTS gold.status_key_seq START 1;
        CREATE SEQUENCE IF NOT EXISTS gold.milestone_key_seq START 1;
        CREATE SEQUENCE IF NOT EXISTS gold.date_key_seq START 1;
        CREATE SEQUENCE IF NOT EXISTS gold.submission_snapshot_key_seq START 1;

        CREATE TABLE IF NOT EXISTS ops.pipeline_attempts (
            run_id VARCHAR NOT NULL,
            attempt_number INTEGER NOT NULL,
            started_at TIMESTAMPTZ NOT NULL,
            completed_at TIMESTAMPTZ NOT NULL,
            attempt_status VARCHAR NOT NULL CHECK (
                attempt_status IN ('succeeded', 'failed')
            ),
            error_stage VARCHAR CHECK (
                error_stage IS NULL OR error_stage IN (
                    'extraction',
                    'bronze_transform',
                    'bronze_load',
                    'silver_transform',
                    'silver_load',
                    'gold_transform',
                    'gold_load'
                )
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
            PRIMARY KEY (run_id, issue_id)
        );

        CREATE TABLE IF NOT EXISTS ops.gold_loads (
            run_id VARCHAR PRIMARY KEY,
            extracted_at TIMESTAMPTZ NOT NULL,
            loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS gold.dim_issue (
            issue_key BIGINT DEFAULT nextval('gold.issue_key_seq') PRIMARY KEY,
            issue_id VARCHAR NOT NULL UNIQUE,
            issue_title VARCHAR NOT NULL,
            issue_url VARCHAR NOT NULL,
            issue_author VARCHAR
        );

        CREATE TABLE IF NOT EXISTS gold.dim_reviewer (
            reviewer_key BIGINT DEFAULT nextval('gold.reviewer_key_seq') PRIMARY KEY,
            reviewer VARCHAR NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS gold.dim_state (
            state_key BIGINT DEFAULT nextval('gold.state_key_seq') PRIMARY KEY,
            state VARCHAR NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS gold.dim_status (
            status_key BIGINT DEFAULT nextval('gold.status_key_seq') PRIMARY KEY,
            status VARCHAR NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS gold.dim_milestone (
            milestone_key BIGINT DEFAULT nextval('gold.milestone_key_seq') PRIMARY KEY,
            milestone VARCHAR NOT NULL UNIQUE,
            milestone_number INTEGER,
            deadline_date DATE
        );

        CREATE TABLE IF NOT EXISTS gold.dim_date (
            date_key BIGINT DEFAULT nextval('gold.date_key_seq') PRIMARY KEY,
            date DATE NOT NULL UNIQUE,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            month_name VARCHAR NOT NULL,
            day INTEGER NOT NULL,
            day_name VARCHAR NOT NULL
        );

        CREATE TABLE IF NOT EXISTS gold.fact_submission_snapshot (
            submission_snapshot_key BIGINT
                DEFAULT nextval('gold.submission_snapshot_key_seq') PRIMARY KEY,
            run_id VARCHAR NOT NULL,
            issue_key BIGINT NOT NULL REFERENCES gold.dim_issue(issue_key),
            state_key BIGINT NOT NULL REFERENCES gold.dim_state(state_key),
            status_key BIGINT REFERENCES gold.dim_status(status_key),
            milestone_key BIGINT NOT NULL REFERENCES gold.dim_milestone(milestone_key),
            created_at_key BIGINT NOT NULL REFERENCES gold.dim_date(date_key),
            updated_at_key BIGINT NOT NULL REFERENCES gold.dim_date(date_key),
            extracted_at_key BIGINT NOT NULL REFERENCES gold.dim_date(date_key),
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            extracted_at TIMESTAMPTZ NOT NULL,
            is_assigned BOOLEAN NOT NULL,
            days_since_update BIGINT NOT NULL,
            submission_age_days BIGINT NOT NULL,
            UNIQUE (issue_key, extracted_at)
        );

        CREATE TABLE IF NOT EXISTS gold.bridge_submission_reviewer (
            submission_snapshot_key BIGINT NOT NULL REFERENCES
                gold.fact_submission_snapshot(submission_snapshot_key),
            reviewer_key BIGINT NOT NULL REFERENCES gold.dim_reviewer(reviewer_key),
            PRIMARY KEY (submission_snapshot_key, reviewer_key)
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


def extract_pending_silver(
    conn: duckdb.DuckDBPyConnection,
) -> list[pd.DataFrame]:
    pending = conn.execute(
        """
        SELECT
            s.issue_id,
            s.issue_title,
            s.issue_url,
            s.issue_author,
            s.created_at,
            s.updated_at,
            s.state,
            s.reviewer,
            s.milestone,
            s.status,
            s.run_id,
            s.extracted_at,
            s.is_assigned,
            s.days_since_update,
            s.submission_age_days
        FROM silver.issue_submissions AS s
        WHERE NOT EXISTS (
            SELECT 1
            FROM ops.gold_loads AS g
            WHERE g.run_id = s.run_id
        )
        ORDER BY s.extracted_at, s.run_id, s.issue_id
        """
    ).df()

    if pending.empty:
        return []

    pending_runs = []
    for run_id, run_df in pending.groupby("run_id", sort=False):
        run_df = run_df.reset_index(drop=True)
        if run_df["extracted_at"].nunique(dropna=False) != 1:
            raise ValueError(
                f"Silver run_id={run_id} contains multiple extraction timestamps"
            )
        pending_runs.append(run_df)
    return pending_runs


def _validate_gold_frame(
    table_name: str,
    df: pd.DataFrame,
    expected_columns: frozenset[str],
) -> None:
    columns = list(df.columns)
    actual_columns = set(columns)
    missing_columns = sorted(expected_columns - actual_columns)
    unexpected_columns = sorted(actual_columns - expected_columns)
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
            f"Gold DataFrame does not match {table_name} schema ("
            + "; ".join(problems)
            + ")"
        )


def _upsert_gold_dimension(
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
    df: pd.DataFrame,
) -> dict[int, int]:
    config = _GOLD_DIMENSIONS[table_name]
    temporary_key = config["key"]
    natural_key = config["natural_key"]
    load_columns = config["columns"]
    expected_columns = frozenset([temporary_key, *load_columns])
    _validate_gold_frame(table_name, df, expected_columns)

    incoming_name = f"incoming_{table_name}"
    conn.register(incoming_name, df[load_columns])
    try:
        column_sql = ", ".join(load_columns)
        update_columns = config["updates"]
        if update_columns:
            conflict_sql = "DO UPDATE SET " + ", ".join(
                f"{column} = excluded.{column}" for column in update_columns
            )
        else:
            conflict_sql = "DO NOTHING"
        conn.execute(
            f"""
            INSERT INTO gold.{table_name} ({column_sql})
            SELECT {column_sql}
            FROM {incoming_name}
            ON CONFLICT ({natural_key}) {conflict_sql}
            """
        )
    finally:
        conn.unregister(incoming_name)

    persisted = conn.execute(
        f"SELECT {temporary_key}, {natural_key} FROM gold.{table_name}"
    ).fetchall()
    key_by_natural_value = {
        natural_value: persisted_key
        for persisted_key, natural_value in persisted
    }
    temporary_to_persisted = {}
    for temporary_value, natural_value in df[
        [temporary_key, natural_key]
    ].itertuples(index=False, name=None):
        if natural_value not in key_by_natural_value:
            raise ValueError(
                f"Could not resolve {table_name} key for {natural_value!r}"
            )
        temporary_to_persisted[int(temporary_value)] = key_by_natural_value[
            natural_value
        ]
    return temporary_to_persisted


def _remap_gold_key(
    values: pd.Series,
    key_mapping: dict[int, int],
    *,
    nullable: bool = False,
) -> pd.Series:
    remapped = values.map(key_mapping)
    unresolved = values.notna() & remapped.isna()
    if unresolved.any() or (not nullable and remapped.isna().any()):
        raise ValueError("Gold batch contains an unresolved dimension key")
    return remapped.astype("Int64")


def load_gold(
    conn: duckdb.DuckDBPyConnection,
    gold_tables: dict[str, dict[str, pd.DataFrame] | pd.DataFrame],
) -> None:
    expected_tables = {
        "dimensions",
        "fact_submission_snapshot",
        "bridge_submission_reviewer",
    }
    if set(gold_tables) != expected_tables:
        raise ValueError("Gold transformation output has unexpected table groups")

    dimensions = gold_tables["dimensions"]
    fact = gold_tables["fact_submission_snapshot"]
    bridge = gold_tables["bridge_submission_reviewer"]
    if not isinstance(dimensions, dict):
        raise TypeError("Gold dimensions must be a dictionary of DataFrames")
    if not isinstance(fact, pd.DataFrame) or not isinstance(bridge, pd.DataFrame):
        raise TypeError("Gold fact and bridge outputs must be DataFrames")
    if set(dimensions) != set(_GOLD_DIMENSIONS):
        raise ValueError("Gold transformation output has unexpected dimensions")

    _validate_gold_frame(
        "fact_submission_snapshot",
        fact,
        _GOLD_FACT_COLUMNS,
    )
    _validate_gold_frame(
        "bridge_submission_reviewer",
        bridge,
        _GOLD_BRIDGE_COLUMNS,
    )
    if fact.empty:
        raise ValueError("Gold load requires at least one submission snapshot")
    if fact["run_id"].nunique(dropna=False) != 1:
        raise ValueError("Gold load requires exactly one run_id")
    if fact["extracted_at"].nunique(dropna=False) != 1:
        raise ValueError("Gold load requires exactly one extraction timestamp")

    run_id = fact["run_id"].iloc[0]
    extracted_at = fact["extracted_at"].iloc[0]
    fact = fact.copy()
    bridge = bridge.copy()

    conn.execute("BEGIN")
    try:
        already_loaded = conn.execute(
            "SELECT EXISTS (SELECT 1 FROM ops.gold_loads WHERE run_id = ?)",
            [run_id],
        ).fetchone()[0]
        if already_loaded:
            raise ValueError(f"Gold run_id={run_id} is already loaded")

        dimension_key_maps = {
            table_name: _upsert_gold_dimension(
                conn,
                table_name,
                dimensions[table_name],
            )
            for table_name in _GOLD_DIMENSIONS
        }

        fact_key_dimensions = {
            "issue_key": "dim_issue",
            "state_key": "dim_state",
            "status_key": "dim_status",
            "milestone_key": "dim_milestone",
            "created_at_key": "dim_date",
            "updated_at_key": "dim_date",
            "extracted_at_key": "dim_date",
        }
        for key_column, table_name in fact_key_dimensions.items():
            fact[key_column] = _remap_gold_key(
                fact[key_column],
                dimension_key_maps[table_name],
                nullable=key_column == "status_key",
            )

        temporary_snapshot_keys = fact["submission_snapshot_key"].tolist()
        persistent_snapshot_keys = [
            row[0]
            for row in conn.execute(
                """
                SELECT nextval('gold.submission_snapshot_key_seq')
                FROM range(?)
                """,
                [len(fact)],
            ).fetchall()
        ]
        snapshot_key_map = dict(
            zip(temporary_snapshot_keys, persistent_snapshot_keys, strict=True)
        )
        fact["submission_snapshot_key"] = _remap_gold_key(
            fact["submission_snapshot_key"],
            snapshot_key_map,
        )
        bridge["submission_snapshot_key"] = _remap_gold_key(
            bridge["submission_snapshot_key"],
            snapshot_key_map,
        )
        bridge["reviewer_key"] = _remap_gold_key(
            bridge["reviewer_key"],
            dimension_key_maps["dim_reviewer"],
        )

        conn.register(
            "incoming_gold_fact",
            fact[list(_GOLD_FACT_COLUMN_ORDER)],
        )
        try:
            conn.execute(
                """
                INSERT INTO gold.fact_submission_snapshot BY NAME
                SELECT * FROM incoming_gold_fact
                """
            )
        finally:
            conn.unregister("incoming_gold_fact")

        if not bridge.empty:
            conn.register(
                "incoming_gold_bridge",
                bridge[list(_GOLD_BRIDGE_COLUMN_ORDER)],
            )
            try:
                conn.execute(
                    """
                    INSERT INTO gold.bridge_submission_reviewer BY NAME
                    SELECT * FROM incoming_gold_bridge
                    """
                )
            finally:
                conn.unregister("incoming_gold_bridge")

        conn.execute(
            """
            INSERT INTO ops.gold_loads (run_id, extracted_at)
            VALUES (?, ?)
            """,
            [run_id, extracted_at],
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

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
