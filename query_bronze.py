#!/usr/bin/env python3
"""Temporarily inspect the local Bronze DuckDB tables."""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb


DATABASE_PATH = Path(__file__).resolve().parent / "data" / "warehouse.duckdb"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of recent rows to show (default: 10)",
    )
    parser.add_argument(
        "--payload",
        action="store_true",
        help="Also print the full JSON payload of the latest Bronze row",
    )
    args = parser.parse_args()

    if args.limit < 1:
        parser.error("--limit must be at least 1")
    if not DATABASE_PATH.exists():
        raise SystemExit(f"Database not found: {DATABASE_PATH}")

    with duckdb.connect(str(DATABASE_PATH), read_only=True) as conn:
        print(f"Database: {DATABASE_PATH}\n")

        print("Recent pipeline attempts")
        conn.sql(
            """
            SELECT
                run_id,
                attempt_number,
                started_at,
                completed_at,
                attempt_status,
                error_stage,
                error_type
            FROM ops.pipeline_attempts
            ORDER BY started_at DESC
            LIMIT ?
            """,
            params=[args.limit],
        ).show()

        print("\nRecent Bronze extractions")
        conn.sql(
            """
            SELECT
                run_id,
                attempt_number,
                extracted_at,
                length(payload) AS payload_characters
            FROM bronze.raw_issue_extractions
            ORDER BY extracted_at DESC
            LIMIT ?
            """,
            params=[args.limit],
        ).show()

        if args.payload:
            row = conn.execute(
                """
                SELECT payload
                FROM bronze.raw_issue_extractions
                ORDER BY extracted_at DESC
                LIMIT 1
                """
            ).fetchone()
            print("\nLatest Bronze payload")
            print(row[0] if row else "No Bronze rows found.")


if __name__ == "__main__":
    main()
