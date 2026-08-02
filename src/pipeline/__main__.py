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
        bronze_df = extract_bronze_submission(conn)
        print(bronze_df)
        
def dev():
    import json
    import pandas as pd
    from datetime import datetime, timezone
    from pipeline import get_dev_database_connection
    from pipeline.etl.extract import Extraction 
    
    config = init_config()
    run_id = str(uuid4())
    
    with open(config.sample_data_path, "r") as fp:
            data = json.load(fp)
            
    extraction = Extraction(
        run_id="example_run_id",
        extracted_at=pd.Timestamp.now(timezone.utc),
        payload=json.dumps(data)
    )
    
    # Transformation
    bronze_df = transform_raw_to_bronze(extraction)
    
    # Load
    with get_dev_database_connection() as conn:
        load_to_bronze(conn, bronze_df)
        bronze_df = extract_bronze_submission(conn)
        print(bronze_df)