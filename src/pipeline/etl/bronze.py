import duckdb
import logging
from datetime import datetime, timezone

from pipeline.etl.extract import Extraction
from pipeline.etl.load import attempt_exists
from pipeline.models import (
    RunMetadata, 
    PipelineAttempt, 
    AttemptStatus    
)


def should_run_bronze(
    conn: duckdb.DuckDBPyConnection,
    metadata: RunMetadata,
    logger: logging.Logger,
) -> bool:
    if attempt_exists(conn, metadata.run_id, metadata.attempt_number):
        logger.info(
            "Bronze attempt %s/%s already has a final outcome; skipping",
            metadata.run_id,
            metadata.attempt_number,
        )
        return False

    return True


def run_bronze(
    metadata: RunMetadata,
    extraction: Extraction,
    started_at: datetime,
) -> tuple[PipelineAttempt, Extraction]:

    succeeded_attempt = PipelineAttempt(
        run_id=metadata.run_id,
        attempt_number=metadata.attempt_number,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc),
        attempt_status=AttemptStatus.SUCCEEDED,
    )

    return succeeded_attempt, extraction
