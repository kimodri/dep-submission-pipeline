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

def run_bronze(
    conn: duckdb.DuckDBPyConnection,
    metadata: RunMetadata,
    extraction: Extraction,
    logger: logging,
    started_at: datetime
) -> tuple:
    
    if attempt_exists(conn, metadata.run_id, metadata.attempt_number):
        logger.info(
            "Bronze attempt %s/%s already has a final outcome; skipping",
            metadata.run_id,
            metadata.attempt_number,
        )
        return None

    succeeded_attempt = PipelineAttempt(
        run_id=metadata.run_id,
        attempt_number=metadata.attempt_number,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc).isoformat(),
        attempt_status=AttemptStatus.SUCCEEDED,
    )
    
    return (succeeded_attempt, extraction)
