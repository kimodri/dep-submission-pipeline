import pandas as pd

DATE_COLUMNS = ["created_at", "updated_at", "extracted_at"]

DIMENSION_CONFIG = {
    "issue": {
        "natural_key": "issue_id",
        "surrogate_key": "issue_key",
        "attributes": ["issue_title", "issue_url", "issue_author"],
    },
    "reviewer": {
        "natural_key": "reviewer",
        "surrogate_key": "reviewer_key",
    },
    "state": {"natural_key": "state", "surrogate_key": "state_key"},
    "status": {"natural_key": "status", "surrogate_key": "status_key"},
    "milestone": {
        "natural_key": "milestone",
        "surrogate_key": "milestone_key",
    },
}

def _standardize_date_cols(
    table: pd.DataFrame, 
    date_cols: list[str]
)-> pd.DataFrame:
    for date_col in date_cols:
        table[date_col] = (
            pd.to_datetime(table[date_col], utc=True)
            .dt.tz_convert("Asia/Manila")
            .dt.floor("s")
        )
    return table

def _create_dim(
    df: pd.DataFrame,
    natural_key: str,
    surrogate_key: str,
    attributes: list[str] | None = None,
) -> pd.DataFrame:
    columns = [natural_key, *(attributes or [])]
    dim_df = (
        df.loc[df[natural_key].notna(), columns]
        .drop_duplicates(subset=[natural_key])
        .sort_values(natural_key, kind="stable")
        .reset_index(drop=True)
    )
    dim_df.insert(0, surrogate_key, range(1, len(dim_df) + 1))
    return dim_df

def _create_dim_date(df: pd.DataFrame, date_cols: list[str]) -> pd.DataFrame:
    dim_date = (
        pd.concat(
            [df[col] for col in date_cols], ignore_index=True
        )
        .dropna()
        .dt.date
        .drop_duplicates()
        .sort_values()
        .reset_index(drop=True)
        .to_frame(name="date")
    )
    dim_date["date_key"] = dim_date.index + 1
    return dim_date

def _filter_date_dim(df: pd.DataFrame) -> pd.DataFrame:
    df["year"] = df["date"].year
    df["month"] = df["date"].month
    df["month_name"] = df["date"].month_name()
    df["day"] = df["date"].day
    df["day_name"] = df["date"].day_name()

    return df

def _merge_date_keys_to_fact(
    fact_df: pd.DataFrame, 
    dim_date_df: pd.DataFrame, 
    date_cols: list[str]
) -> pd.DataFrame:
    if not dim_date_df["date"].is_unique:
        raise ValueError("dim_date must contain one row per date")

    fact_df = fact_df.copy()
    date_key_lookup = dim_date_df.set_index("date")["date_key"]

    for col in date_cols:
        fact_df[f"{col}_key"] = (
            fact_df[col]
            .dt.date
            .map(date_key_lookup)
            .astype("Int64")
        )
    return fact_df

def transform_silver_to_gold(df: pd.DataFrame) -> dict[str, dict[str, pd.DataFrame]]:
    # TODO: Derive current_milestone and schedule_status in a Gold builder
    # snapshot table, where one row represents one builder per extraction.
    gold_table = df.copy()
    gold_table = _standardize_date_cols(gold_table, DATE_COLUMNS)
    gold_table_exploded = gold_table.explode("assignees")\
    .drop(columns=["labels"])

    # Create dimensions
    dimensions = {
        name: _create_dim(gold_table_exploded, **config)
        for name, config in DIMENSION_CONFIG.items()
    }

    issue_attributes = DIMENSION_CONFIG["issue"]["attributes"]
    fact_submission_snapshot = gold_table_exploded.drop(
        columns=issue_attributes
    ).copy()

    for name, config in DIMENSION_CONFIG.items():
        natural_key = config["natural_key"]
        surrogate_key = config["surrogate_key"]
        key_mapping = dimensions[name][[surrogate_key, natural_key]]

        fact_submission_snapshot = (
            fact_submission_snapshot.merge(
                key_mapping,
                on=natural_key,
                how="left",
                sort=False,
                validate="many_to_one",
            )
            .drop(columns=natural_key)
        )
        fact_submission_snapshot[surrogate_key] = (
            fact_submission_snapshot[surrogate_key].astype("Int64")
        )

        # Create date dimension
        dim_date = _create_dim_date(fact_submission_snapshot, DATE_COLUMNS)
    
        fact_submission_snapshot = _merge_date_keys_to_fact(
            fact_submission_snapshot, dim_date, DATE_COLUMNS
        )
        
        dimensions["dim_date"] = _filter_date_dim(dim_date)
        
        tables = {}
        
        tables["dimensions"] = dimensions
        tables["fact_submission_snapshot"] = fact_submission_snapshot

    return tables

