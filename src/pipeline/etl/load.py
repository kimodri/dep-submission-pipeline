import pandas as pd

def load_to_bronze(conn, bronze_df: pd.DataFrame):
    conn.execute(
        """
        CREATE SCHEMA IF NOT EXISTS bronze;

        CREATE TABLE IF NOT EXISTS bronze.raw_issue_extractions (
            run_id VARCHAR PRIMARY KEY,
            extracted_at TIMESTAMPTZ NOT NULL,
            payload JSON NOT NULL
        );
        """
    )

    conn.register("incoming_bronze_df", bronze_df)

    try:
        conn.execute(
            """
            INSERT INTO bronze.raw_issue_extractions BY NAME
            SELECT * FROM incoming_bronze_df
            """
        )
    finally:
        conn.unregister("incoming_bronze_df")
