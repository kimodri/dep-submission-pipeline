import re, json
import pandas as pd
from datetime import datetime

DATE_COLS = [
    "extracted_at",
    "created_at",
    "updated_at"
]

def _get_reviewers(reviewer_list: list[dict]) -> list[str]:
    if not reviewer_list:
        return []
    return [reviewer.get("login") for reviewer in reviewer_list if reviewer]

def _get_milestone(title: str, labels: list[dict]) -> str | None:
    milestone = None
    if labels:
        for label in labels:
            if label.get("name", "").startswith("M") and label.get("name", "")[1:].isdigit():
                milestone = label.get("name")
                break

    if milestone is None and title:
        match = re.search(r"\[(M\d+)\]", title)
        if match:
            milestone = match.group(1)

    return milestone

def _get_status(field_values: list[dict]) -> str:
    for field in field_values:
        if not field:
            continue
        if field.get("field", {}).get("name") == "Status":
            status = field.get("name")
            break
    return status

def _standardize_date_cols(table: pd.DataFrame, date_cols: list[str])-> pd.DataFrame:
    for date_col in date_cols:
        table[date_col] = (
            pd.to_datetime(table[date_col], utc=True)
            .dt.tz_convert("Asia/Manila")
            .dt.floor("s")
        )
    return table


def transform_bronze_to_silver(run_id: str, extracted_at: datetime, data: pd.DataFrame) -> pd.DataFrame:

    list_of_contents = data["data"].get("data").get("organization").get("projectV2").get("items").get("nodes")
     
    silver_df = pd.json_normalize(list_of_contents, sep="_")
    silver_df.rename(
        columns={
            "content_id": "issue_id",
            "content_title": "issue_title",
            "content_url": "issue_url",
            "content_author_login": "issue_author",
            "content_createdAt": "created_at",
            "content_updatedAt": "updated_at",
            "content_state": "state",
            "content_assignees_nodes": "reviewer",
            "content_labels_nodes": "milestone",
            "fieldValues_nodes": "status"
        },
        inplace=True
    )
    
    silver_df["extracted_at"] = extracted_at
    
    silver_df["reviewer"] = silver_df["reviewer"].apply(_get_reviewers)
    silver_df["milestone"] = silver_df.apply(lambda row: _get_milestone(row["issue_title"], row["milestone"]), axis=1)
    silver_df["status"] = silver_df["status"].apply(_get_status)

    silver_df = _standardize_date_cols(silver_df, DATE_COLS)
    
    # Feature engineer measure columns
    silver_df["is_assigned"] = (silver_df["reviewer"].notna().astype("int8"))
    silver_df["days_since_update"] = (silver_df["updated_at"] - silver_df["created_at"]).dt.days
    silver_df["submission_age_days"] = (silver_df["extracted_at"] - silver_df["created_at"]).dt.days
    
    return silver_df[silver_df["issue_title"].str.match(r"\[M\d+\]")]
    
if __name__ == "__main__":
    from pipeline import init_local_config
    from datetime import datetime, timezone
    from pipeline.etl import transform_raw_to_bronze
    from pipeline.etl.extract import Extraction
    
    config = init_local_config()
    
    with open(config.sample_data_path, "r") as fp:
            data = json.load(fp)
            
    extraction = Extraction(
        run_id="example_run_id",
        extracted_at=datetime.now(timezone.utc),
        payload=data
    )
    
    bronze_df = transform_raw_to_bronze(extraction)

    silver_df = transform_bronze_to_silver(
        run_id=extraction.run_id,
        extracted_at=extraction.extracted_at,
        data=bronze_df
    )
    
    print(silver_df.head())
