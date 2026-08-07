from dataclasses import replace
from datetime import datetime, timezone
import json
import logging
from pathlib import Path

from pipeline import get_database_connection, get_dev_database_connection, init_config
from pipeline.models import Extraction
from pipeline.etl.extract import extract_submissions
from pipeline.etl.load import (
    create_pipeline_tables,
    load_successful_extraction_to_bronze,
    record_failure_safely
)
from pipeline.etl import run_bronze
from pipeline.run_metadata import resolve_run_metadata

logger = logging.getLogger(__name__)

def _run(connection_factory, local: bool = False) -> None:
    config = init_config()
    metadata = resolve_run_metadata()

    logging.info(
        "Starting Bronze run_id=%s attempt_number=%s",
        metadata.run_id,
        metadata.attempt_number,
    )
        
    with connection_factory() as conn:
        create_pipeline_tables(conn)

        started_at = datetime.now(timezone.utc)

        try:
            if local:
                project_root = Path(__file__).resolve().parents[2]
                raw_payload_path = project_root / "data" / "rawpayload.json"
                with raw_payload_path.open(encoding="utf-8") as raw_payload_file:
                    payload = json.load(raw_payload_file)

                extraction = Extraction(
                    run_id=metadata.run_id,
                    attempt_number=metadata.attempt_number,
                    extracted_at=datetime.now(timezone.utc),
                    payload=payload,
                )
            else:
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
                stage="extraction",
                error=extraction_error,
                logger=logger
            )
            raise

        try:
            bronze_rows = run_bronze(
                conn,
                metadata,
                extraction,
                logger,
                started_at,
            )
            if bronze_rows is None:
                return
            pipeline_attempt_row, extraction_row = bronze_rows
            pipeline_attempt_row = replace(
                pipeline_attempt_row,
                completed_at=datetime.now(timezone.utc),
            )
        except Exception as bronze_error:
            record_failure_safely(
                conn,
                config,
                metadata,
                started_at=started_at,
                stage="bronze_load",
                error=bronze_error,
                logger=logger
            )
            raise
        
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
                logger=logger
            )
            raise
        
        
        # Log here when starting silver
        # Log here when starting gold


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    _run(get_database_connection)


def dev() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--local",
        action="store_true",
        help="Load data/rawpayload.json instead of extracting from GitHub",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    _run(get_dev_database_connection, local=args.local)
