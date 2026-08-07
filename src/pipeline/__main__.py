from datetime import datetime, timezone
import json
import logging
from pathlib import Path

from pipeline import (
    get_database_connection,
    get_dev_database_connection,
    init_local_config,
    init_motherduck_config,
    init_source_config,
)
from pipeline.models import Extraction, SourceConfig
from pipeline.etl.extract import extract_submissions
from pipeline.etl.load import (
    create_pipeline_tables,
    load_successful_extraction_to_bronze,
    record_failure_safely
)
from pipeline.etl import run_bronze, should_run_bronze
from pipeline.run_metadata import resolve_run_metadata

logger = logging.getLogger(__name__)
_MAX_ERROR_MESSAGE_LENGTH = 2_000


def _run(
    connection_factory,
    source_config: SourceConfig | None,
    *,
    sample_data_path: Path | None = None,
    error_secrets: list[str | None] | None = None,
) -> None:
    metadata = resolve_run_metadata()
    secrets = error_secrets or []

    if source_config is None and sample_data_path is None:
        raise ValueError("A source configuration or local sample path is required")

    logging.info(
        "Starting Bronze run_id=%s attempt_number=%s",
        metadata.run_id,
        metadata.attempt_number,
    )
        
    with connection_factory() as conn:
        create_pipeline_tables(conn)

        if not should_run_bronze(conn, metadata, logger):
            return

        started_at = datetime.now(timezone.utc)

        try:
            if sample_data_path is not None:
                with sample_data_path.open(encoding="utf-8") as raw_payload_file:
                    payload = json.load(raw_payload_file)

                extraction = Extraction(
                    run_id=metadata.run_id,
                    attempt_number=metadata.attempt_number,
                    extracted_at=datetime.now(timezone.utc),
                    payload=payload,
                )
            else:
                if source_config is None:
                    raise ValueError("GitHub extraction requires source configuration")
                extraction = extract_submissions(
                    source_config.owner_name,
                    source_config.owner_type,
                    source_config.project_number,
                    source_config.token,
                    metadata.run_id,
                    metadata.attempt_number
                )
        except Exception as extraction_error:
            record_failure_safely(
                conn,
                metadata,
                started_at=started_at,
                stage="extraction",
                error=extraction_error,
                secrets=secrets,
                max_error_message=_MAX_ERROR_MESSAGE_LENGTH,
                logger=logger
            )
            raise

        try:
            pipeline_attempt_row, extraction_row = run_bronze(
                metadata,
                extraction,
                started_at,
            )
        except Exception as bronze_error:
            record_failure_safely(
                conn,
                metadata,
                started_at=started_at,
                stage="bronze_load",
                error=bronze_error,
                secrets=secrets,
                max_error_message=_MAX_ERROR_MESSAGE_LENGTH,
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
                metadata,
                started_at=started_at,
                stage="bronze_load",
                error=load_error,
                secrets=secrets,
                max_error_message=_MAX_ERROR_MESSAGE_LENGTH,
                logger=logger
            )
            raise
        
        
        # Log here when starting silver
        # Log here when starting gold


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    source_config = init_source_config()
    motherduck_config = init_motherduck_config()
    _run(
        lambda: get_database_connection(motherduck_config),
        source_config,
        error_secrets=[source_config.token, motherduck_config.token],
    )


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
    local_config = init_local_config()
    connection_factory = lambda: get_dev_database_connection(local_config)

    if args.local:
        _run(
            connection_factory,
            None,
            sample_data_path=local_config.sample_data_path,
        )
    else:
        source_config = init_source_config()
        _run(
            connection_factory,
            source_config,
            error_secrets=[source_config.token],
        )
