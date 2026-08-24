from datetime import date

import pandas as pd


DATE_COLUMNS = ["created_at", "updated_at", "extracted_at"]

MILESTONE_DEADLINES = {
    0: date(2026, 6, 28),
    1: date(2026, 7, 19),
    2: date(2026, 8, 2),
    3: date(2026, 9, 13),
    4: date(2026, 10, 11),
    5: date(2026, 11, 8),
    6: date(2026, 12, 6),
}

MILESTONE_WEEKS = {
    0: [1],
    1: [*range(2, 5)],
    2: [5, 6],
    3: [*range(7, 13)],
    4: [*range(13, 17)],
    5: [*range(17, 21)],
    6: [*range(21, 25)],
}

DIMENSION_CONFIG = {
    "dim_issue": {
        "natural_key": "issue_id",
        "surrogate_key": "issue_key",
        "attributes": ["issue_title", "issue_url", "issue_author"],
    },
    "dim_state": {"natural_key": "state", "surrogate_key": "state_key"},
    "dim_status": {"natural_key": "status", "surrogate_key": "status_key"},
    "dim_milestone": {
        "natural_key": "milestone",
        "surrogate_key": "milestone_key",
    },
}

FACT_SUBMISSION_COLUMNS = [
    "submission_snapshot_key",
    "run_id",
    "issue_key",
    "state_key",
    "status_key",
    "milestone_key",
    "created_at_key",
    "updated_at_key",
    "extracted_at_key",
    "created_at",
    "updated_at",
    "extracted_at",
    "is_assigned",
    "days_since_update",
    "submission_age_days",
]


def _standardize_date_cols(
    table: pd.DataFrame,
    date_cols: list[str],
) -> pd.DataFrame:
    table = table.copy()
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
        pd.concat([df[col] for col in date_cols], ignore_index=True)
        .dropna()
        .dt.date
        .drop_duplicates()
        .sort_values()
        .reset_index(drop=True)
        .to_frame(name="date")
    )
    dim_date.insert(0, "date_key", range(1, len(dim_date) + 1))
    return dim_date


def _add_date_attributes(df: pd.DataFrame) -> pd.DataFrame:
    dim_date = df.copy()
    dates = pd.to_datetime(dim_date["date"])
    dim_date["year"] = dates.dt.year
    dim_date["month"] = dates.dt.month
    dim_date["month_name"] = dates.dt.month_name()
    dim_date["day"] = dates.dt.day
    dim_date["day_name"] = dates.dt.day_name()
    return dim_date


def _add_milestone_attributes(df: pd.DataFrame) -> pd.DataFrame:
    dim_milestone = df.copy()
    dim_milestone["milestone_number"] = pd.to_numeric(
        dim_milestone["milestone"].str.extract(r"^M(\d+)$")[0],
        errors="coerce",
    ).astype("Int64")
    dim_milestone["deadline_date"] = dim_milestone["milestone_number"].map(
        MILESTONE_DEADLINES
    )
    return dim_milestone


def _create_dim_milestone(df: pd.DataFrame) -> pd.DataFrame:
    configured_milestones = pd.DataFrame(
        {
            "milestone": [
                f"M{milestone_number}"
                for milestone_number in MILESTONE_DEADLINES
            ]
        }
    )
    observed_milestones = df.loc[
        df["milestone"].notna(),
        ["milestone"],
    ]
    dim_milestone = (
        pd.concat(
            [configured_milestones, observed_milestones],
            ignore_index=True,
        )
        .drop_duplicates(subset=["milestone"])
        .reset_index(drop=True)
    )
    dim_milestone = _add_milestone_attributes(dim_milestone)
    dim_milestone = dim_milestone.sort_values(
        ["milestone_number", "milestone"],
        kind="stable",
        na_position="last",
    ).reset_index(drop=True)
    dim_milestone.insert(
        0,
        "milestone_key",
        range(1, len(dim_milestone) + 1),
    )
    return dim_milestone


def _merge_dimension_key_to_fact(
    fact_df: pd.DataFrame,
    dim_df: pd.DataFrame,
    natural_key: str,
    surrogate_key: str,
) -> pd.DataFrame:
    key_mapping = dim_df[[surrogate_key, natural_key]]
    fact_df = (
        fact_df.merge(
            key_mapping,
            on=natural_key,
            how="left",
            sort=False,
            validate="many_to_one",
        )
        .drop(columns=natural_key)
    )
    fact_df[surrogate_key] = fact_df[surrogate_key].astype("Int64")
    return fact_df


def _merge_date_keys_to_fact(
    fact_df: pd.DataFrame,
    dim_date_df: pd.DataFrame,
    date_cols: list[str],
) -> pd.DataFrame:
    if not dim_date_df["date"].is_unique:
        raise ValueError("dim_date must contain one row per date")

    fact_df = fact_df.copy()
    date_key_lookup = dim_date_df.set_index("date")["date_key"]

    for col in date_cols:
        fact_df[f"{col}_key"] = (
            fact_df[col].dt.date.map(date_key_lookup).astype("Int64")
        )
    return fact_df


def _create_reviewer_tables(
    snapshot_reviewers: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    reviewer_assignments = (
        snapshot_reviewers.explode("reviewer")
        .dropna(subset=["reviewer"])
        .drop_duplicates(subset=["submission_snapshot_key", "reviewer"])
        .reset_index(drop=True)
    )
    dim_reviewer = _create_dim(
        reviewer_assignments,
        natural_key="reviewer",
        surrogate_key="reviewer_key",
    )
    bridge = _merge_dimension_key_to_fact(
        reviewer_assignments,
        dim_reviewer,
        natural_key="reviewer",
        surrogate_key="reviewer_key",
    )
    bridge = bridge[["submission_snapshot_key", "reviewer_key"]]
    return dim_reviewer, bridge


def transform_silver_to_gold(
    df: pd.DataFrame,
) -> dict[str, dict[str, pd.DataFrame] | pd.DataFrame]:
    gold_table = _standardize_date_cols(df, DATE_COLUMNS)

    if gold_table.duplicated(subset=["issue_id", "extracted_at"]).any():
        raise ValueError(
            "Gold submission snapshots must be unique by issue_id and extracted_at"
        )

    gold_table.insert(
        0,
        "submission_snapshot_key",
        range(1, len(gold_table) + 1),
    )

    dimensions = {
        name: _create_dim(gold_table, **config)
        for name, config in DIMENSION_CONFIG.items()
        if name != "dim_milestone"
    }
    dimensions["dim_milestone"] = _create_dim_milestone(gold_table)

    dim_date = _add_date_attributes(_create_dim_date(gold_table, DATE_COLUMNS))
    dimensions["dim_date"] = dim_date

    dim_reviewer, bridge_submission_reviewer = _create_reviewer_tables(
        gold_table[["submission_snapshot_key", "reviewer"]]
    )
    dimensions["dim_reviewer"] = dim_reviewer

    fact_submission_snapshot = gold_table.drop(
        columns=[
            *DIMENSION_CONFIG["dim_issue"]["attributes"],
            "reviewer",
        ]
    )
    for name, config in DIMENSION_CONFIG.items():
        fact_submission_snapshot = _merge_dimension_key_to_fact(
            fact_submission_snapshot,
            dimensions[name],
            natural_key=config["natural_key"],
            surrogate_key=config["surrogate_key"],
        )

    fact_submission_snapshot = _merge_date_keys_to_fact(
        fact_submission_snapshot,
        dim_date,
        DATE_COLUMNS,
    )
    fact_submission_snapshot = fact_submission_snapshot[FACT_SUBMISSION_COLUMNS]

    return {
        "dimensions": dimensions,
        "fact_submission_snapshot": fact_submission_snapshot,
        "bridge_submission_reviewer": bridge_submission_reviewer,
    }
