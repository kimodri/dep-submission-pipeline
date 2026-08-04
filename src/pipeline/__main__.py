from uuid import uuid4

from pipeline import init_config, get_database_connection
from pipeline.etl import (
    extract_submissions, 
    transform_raw_to_bronze,
    load_to_bronze,
    extract_bronze_submission
)


def main():
    
    config = init_config()
    run_id = str(uuid4())
    
    # Extraction
    extraction = extract_submissions(
        owner_name=config.owner_name,
        owner_type=config.owner_type,
        project_number=config.project_number,
        token=config.token,
        run_id=run_id
    )
 
    # Transformation
    bronze_df = transform_raw_to_bronze(extraction)
    
    # Load
    with get_database_connection() as conn:
        load_to_bronze(conn, bronze_df)
        bronze_df = extract_bronze_submission(conn, run_id)
        
        # Proceed with silver
        
def dev():
    import json
    import pandas as pd
    from datetime import datetime, timezone
    from pipeline import get_dev_database_connection
    from pipeline.etl.extract import Extraction, extract_bronze_submission, _extract_all
    
    config = init_config()
    run_id = str(uuid4())
    
    with open(config.sample_data_path, "r") as fp:
            data = json.load(fp)
            
    extraction = Extraction(
        run_id=run_id,
        extracted_at=pd.Timestamp.now(timezone.utc),
        payload=json.dumps(data)
    )
    
    # Transformation
    bronze_df = transform_raw_to_bronze(extraction)
    
    # Load
    with get_dev_database_connection() as conn:
        conn.execute("BEGIN")
        try:
            load_to_bronze(conn, bronze_df)
            bronze_df = extract_bronze_submission(conn, run_id)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLL BACK")
        print(bronze_df)
        print(_extract_all(conn))