import re
import pandas as pd
from datetime import datetime

from pipeline.models import Extraction

DATE_COLS = [
    "extracted_at",
    "created_at",
    "updated_at"
]

NAMES_TO_DROP = [
    "smmariquit", 
    "gkate78", 
    "Zeraphim", 
    "cancinoray", 
    "CardinalSeen"
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

def _get_status(field_values: list[dict]) -> str | None:
    status = None
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

def _transform_page_to_silver(
    run_id: str,
    extracted_at: datetime,
    page: dict,
) -> pd.DataFrame:

    list_of_contents = (
        page["data"]
        .get("organization")
        .get("projectV2")
        .get("items")
        .get("nodes")
    )
     
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
    if "issue_author" not in silver_df.columns:
        silver_df["issue_author"] = pd.NA
    
    silver_df["run_id"] = run_id
    silver_df["extracted_at"] = extracted_at
    
    silver_df["reviewer"] = silver_df["reviewer"].apply(_get_reviewers)
    silver_df["milestone"] = silver_df.apply(lambda row: _get_milestone(row["issue_title"], row["milestone"]), axis=1)
    silver_df["status"] = silver_df["status"].apply(_get_status)
    silver_df = silver_df[~silver_df["issue_author"].isin(NAMES_TO_DROP)]
    silver_df = silver_df[
        silver_df["issue_title"].str.match(r"\[M\d+\]", na=False)
    ].copy()

    silver_df = _standardize_date_cols(silver_df, DATE_COLS)
    
    # Feature engineer measure columns
    silver_df["is_assigned"] = silver_df["reviewer"].str.len().gt(0)
    # GitHub's updated_at represents any issue update; it does not identify
    # whether the latest activity came from a builder or a reviewer.
    silver_df["days_since_update"] = (silver_df["extracted_at"] - silver_df["updated_at"]).dt.days
    silver_df["submission_age_days"] = (silver_df["extracted_at"] - silver_df["created_at"]).dt.days
    
    return silver_df


def transform_bronze_to_silver(
    run_id: str,
    extracted_at: datetime,
    payload: dict,
) -> pd.DataFrame:
 
    pages = payload.get("pages")
    if not isinstance(pages, list):
        raise ValueError("Bronze payload must contain a 'pages' list")

    if not pages:
        return pd.DataFrame()

    page_frames = [
        _transform_page_to_silver(run_id, extracted_at, page)
        for page in pages
    ]
    silver_df = (
        pd.concat(page_frames, ignore_index=True)
        .sort_values("created_at", ascending=False)
        .drop_duplicates(
            subset=["issue_author", "milestone"],
            keep="first",
        )
        .reset_index(drop=True)
    )
    return silver_df


def transform_extraction_to_silver(extraction: Extraction) -> pd.DataFrame:
    return transform_bronze_to_silver(
        run_id=extraction.run_id,
        extracted_at=extraction.extracted_at,
        payload=extraction.payload,
    )
