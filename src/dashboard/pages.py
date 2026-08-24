from datetime import date, timedelta

from markupsafe import Markup
import pandas as pd
import plotly.io as pio

from analytics.datasets import DashboardDatasets
from dashboard.charts import (
    build_progress_chart,
    build_reviewer_workload_chart,
    build_submission_status_chart,
)
from pipeline.etl.gold import MILESTONE_DEADLINES, MILESTONE_WEEKS


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


def _current_milestone_kpi(as_of_date: date) -> dict:
    ordered_deadlines = sorted(MILESTONE_DEADLINES.items())
    current_number = next(
        (
            milestone_number
            for milestone_number, deadline in ordered_deadlines
            if as_of_date <= deadline
        ),
        ordered_deadlines[-1][0],
    )

    first_week = min(week for weeks in MILESTONE_WEEKS.values() for week in weeks)
    last_week = max(week for weeks in MILESTONE_WEEKS.values() for week in weeks)
    program_start = MILESTONE_DEADLINES[0] - timedelta(days=(first_week * 7) - 1)
    current_week = ((as_of_date - program_start).days // 7) + 1
    current_week = min(max(current_week, first_week), last_week)

    milestone_weeks = MILESTONE_WEEKS[current_number]
    week_label = (
        f"week {milestone_weeks[0]}"
        if len(milestone_weeks) == 1
        else f"weeks {milestone_weeks[0]}–{milestone_weeks[-1]}"
    )
    return {
        "label": "Current milestone",
        "value": f"M{current_number}",
        "detail": (
            f"Week {current_week} of {last_week} · "
            f"M{current_number} spans {week_label}"
        ),
        "tone": "primary",
    }


def overview_context(
    datasets: DashboardDatasets,
    *,
    as_of_date: date | None = None,
) -> dict:
    as_of_date = as_of_date or date.today()
    return {
        "schedule_kpis": [
            _current_milestone_kpi(as_of_date),
            *_schedule_kpis(datasets.builder_schedule),
        ],
        "submission_chart": _chart_html(
            build_submission_status_chart(datasets.submission_status),
            "submission-status-chart",
        ),
        "progress_chart": _chart_html(
            build_progress_chart(datasets.progress_trend), "progress-trend-chart"
        ),
    }


def builders_context(
    datasets: DashboardDatasets,
    *,
    as_of_date: date | None = None,
) -> dict:
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


def reviewers_context(
    datasets: DashboardDatasets,
    *,
    as_of_date: date | None = None,
) -> dict:
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
