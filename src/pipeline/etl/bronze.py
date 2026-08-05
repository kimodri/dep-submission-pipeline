import json
import pandas as pd
from pipeline.etl.extract import Extraction


def transform_raw_to_bronze(extraction: Extraction) -> pd.DataFrame:
    payload = extraction.payload
    df = pd.DataFrame(
        [{
            "run_id": extraction.run_id,
            "payload": payload,
            "extracted_at": extraction.extracted_at
        }]
    )
    
    return df


if __name__ == "__main__":
    from pipeline import init_config
    
    config = init_config()
    
    with open(config.sample_data_path, "r") as fp:
        data = json.load(fp)
    extraction = Extraction(
        run_id="example_run_id",
        extracted_at=pd.Timestamp.now(),
        payload=data
    )
    bronze_df = transform_raw_to_bronze(extraction)
    print(bronze_df)
    print(bronze_df.dtypes)
