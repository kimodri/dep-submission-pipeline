from markupsafe import Markup
import pandas as pd
import plotly.io as pio

from analytics.datasets import DashboardDatasets
from dashboard.charts import (
    build_progress_chart,
    build_reviewer_workload_chart,
    build_submission_status_chart,
)


PLOT_CONFIG = {"displayModeBar": False, "responsive": True, "scrollZoom": False}


def _chart_html(figure, div_id: str) -> Markup:
    return Markup(
        pio.to_html(
            figure,
            full_html=False,
            include_plotlyjs=False,
            config=PLOT_CONFIG,
            div_id=div_id,
        )
    )


def _schedule_kpis(schedule: pd.DataFrame) -> list[dict]:
    records = {
        str(row.schedule_status).casefold(): row
        for row in schedule.itertuples(index=False)
    }
    cards = []
    for key, label, tone in (
        ("on track", "On track", "success"),
        ("delayed", "Delayed", "danger"),
    ):
        row = records.get(key)
        cards.append(
            {
                "label": label,
                "value": int(row.builder_count) if row is not None else 0,
                "detail": (
                    f"{float(row.builder_percentage):.0f}% of builders"
                    if row is not None
                    else "No builder data"
                ),
                "tone": tone,
            }
        )
    return cards


def overview_context(datasets: DashboardDatasets) -> dict:
    return {
        "schedule_kpis": _schedule_kpis(datasets.builder_schedule),
        "submission_chart": _chart_html(
            build_submission_status_chart(datasets.submission_status),
            "submission-status-chart",
        ),
        "progress_chart": _chart_html(
            build_progress_chart(datasets.progress_trend), "progress-trend-chart"
        ),
    }


def builders_context(datasets: DashboardDatasets) -> dict:
    interventions = datasets.interventions.copy()
    records = interventions.to_dict(orient="records")
    return {
        "interventions": records,
        "intervention_count": len(records),
        "statuses": (
            sorted(interventions["status"].unique()) if not interventions.empty else []
        ),
        "schedules": (
            sorted(interventions["schedule_status"].unique())
            if not interventions.empty
            else []
        ),
    }


def reviewers_context(datasets: DashboardDatasets) -> dict:
    workload = datasets.reviewer_workload
    unassigned = workload.loc[workload["reviewer"] == "Unassigned", "unresolved_count"]
    return {
        "reviewer_chart": _chart_html(
            build_reviewer_workload_chart(workload), "reviewer-workload-chart"
        ),
        "unresolved_total": int(workload["unresolved_count"].sum()),
        "unassigned_count": int(unassigned.sum()) if not unassigned.empty else 0,
        "reviewer_count": int((workload["reviewer"] != "Unassigned").sum()),
    }
