from datetime import datetime, timezone
import logging

from pipeline import get_database_connection, get_dev_database_connection, init_config
from pipeline.etl.extract import extract_submissions
from pipeline.etl.load import (
    create_pipeline_tables,
    load_successful_extraction_to_bronze,
    record_failure_safely
)
from pipeline.etl import run_bronze
from pipeline.run_metadata import resolve_run_metadata

logger = logging.getLogger(__name__)

def _run(connection_factory) -> None:
    config = init_config()
    metadata = resolve_run_metadata()

    logging.info(
        "Starting Bronze run_id=%s attempt_number=%s",
        metadata.run_id,
        metadata.attempt_number,
    )
        
    with connection_factory() as conn:
        create_pipeline_tables(conn)
        
        started_at = datetime.now(timezone.utc).isoformat
        try:
            extraction = extract_submissions(
                config.owner_name,
                config.owner_type,
                config.project_number,
                config.token,
                metadata.run_id,
                metadata.attempt_number
            )
        except Exception as extraction_error:
            record_failure_safely(
                conn,
                config,
                metadata,
                started_at=started_at,
                stage="extract_bronze",
                error=extraction_error
            )
            raise
        try:
            pipeline_attempt_row, extraction_row = run_bronze(conn, extraction, started_at)
        except Exception as transform_error:
            record_failure_safely(
                conn,
                config,
                metadata,
                started_at=started_at,
                stage="transform_bronze",
                error=transform_error
            )
        
        try:
            load_successful_extraction_to_bronze(
                conn,
                extraction_row,
                pipeline_attempt_row
            )
        except Exception as load_error:
            record_failure_safely(
                conn,
                config,
                metadata,
                started_at=started_at,
                stage="bronze_load",
                error=load_error,
            )
            raise
        
        
        # Log here when starting silver
        # Log here when starting gold


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    _run(get_database_connection)


def dev() -> None:
    logging.basicConfig(level=logging.INFO)
    _run(get_dev_database_connection)
