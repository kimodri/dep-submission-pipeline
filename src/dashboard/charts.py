import pandas as pd
import plotly.graph_objects as go


STATUS_COLORS = {
    "Passed": "#10b981",
    "In review": "#2563eb",
    "Needs Improvement": "#f59e0b",
    "Unchecked/Unassigned": "#ef4444",
    # Fixture aliases retained until the demo data uses the Gold vocabulary.
    "Accepted": "#10b981",
    "Needs changes": "#f59e0b",
    "Not submitted": "#ef4444",
    "Unknown": "#6b7280",
}
MILESTONES = tuple(f"M{number}" for number in range(7))
PLOT_FONT_FAMILY = "Roboto, Noto Sans, sans-serif"
def _base_layout(title: str, height: int) -> dict:
    return {
        "title": None,
        "height": height,
        "margin": {"l": 48, "r": 18, "t": 24, "b": 48},
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"family": PLOT_FONT_FAMILY, "color": "#6b7280"},
        "hoverlabel": {"font": {"family": PLOT_FONT_FAMILY}},
        "hovermode": "closest",
        "showlegend": True,
        "legend": {"orientation": "h", "y": 1.12, "x": 0},
        "uirevision": title,
    }


def _empty_figure(message: str, height: int = 360) -> go.Figure:
    figure = go.Figure()
    figure.update_layout(**{**_base_layout("empty", height), "showlegend": False})
    figure.add_annotation(
        text=message,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font={"size": 14, "color": "#6b7280"},
    )
    figure.update_xaxes(visible=False)
    figure.update_yaxes(visible=False)
    return figure


def build_submission_status_chart(data: pd.DataFrame) -> go.Figure:
    if data.empty:
        return _empty_figure("Submission status data is not available yet.", 380)

    frame = data.copy()
    milestones = list(MILESTONES)
    observed = list(dict.fromkeys(frame["status"].tolist()))
    preferred = [name for name in STATUS_COLORS if name in observed]
    statuses = preferred + sorted(set(observed) - set(preferred))

    figure = go.Figure()
    for status in statuses:
        values = (
            frame.loc[frame["status"] == status]
            .set_index("milestone")["submission_count"]
            .reindex(milestones, fill_value=0)
        )
        figure.add_bar(
            name=status,
            x=milestones,
            y=values,
            marker_color=STATUS_COLORS.get(status, STATUS_COLORS["Unknown"]),
            hovertemplate="%{x}<br>%{y} submissions<extra>" + status + "</extra>",
        )

    figure.update_layout(
        **_base_layout("submission-status", 380), barmode="stack", bargap=0.3
    )
    figure.update_xaxes(title=None, gridcolor="rgba(107,114,128,0.10)")
    figure.update_yaxes(
        title="Submissions", rangemode="tozero", gridcolor="rgba(107,114,128,0.14)"
    )
    return figure


def build_progress_chart(data: pd.DataFrame) -> go.Figure:
    if data.empty:
        return _empty_figure("Progress history is not available yet.", 340)

    frame = data.sort_values("extraction_date")
    figure = go.Figure(
        go.Scatter(
            x=frame["extraction_date"],
            y=frame["completion_rate"],
            mode="lines+markers",
            name="Completion rate",
            line={"color": "#2563eb", "width": 3},
            marker={"color": "#2563eb", "size": 7},
            fill="tozeroy",
            fillcolor="rgba(37,99,235,0.08)",
            hovertemplate="%{x|%b %d, %Y}<br>%{y:.0f}% complete<extra></extra>",
        )
    )
    figure.update_layout(
        **{**_base_layout("progress-trend", 340), "showlegend": False}
    )
    figure.update_xaxes(title=None, gridcolor="rgba(107,114,128,0.10)")
    figure.update_yaxes(
        title="Average completion",
        ticksuffix="%",
        range=[0, max(100, float(frame["completion_rate"].max()) + 10)],
        gridcolor="rgba(107,114,128,0.14)",
    )
    return figure


def build_reviewer_workload_chart(data: pd.DataFrame) -> go.Figure:
    if data.empty:
        return _empty_figure("Reviewer workload data is not available yet.", 420)

    frame = data.sort_values(["unresolved_count", "reviewer"], ascending=[True, True])
    colors = [
        "#f59e0b" if reviewer == "Unassigned" else "#2563eb"
        for reviewer in frame["reviewer"]
    ]
    figure = go.Figure(
        go.Bar(
            x=frame["unresolved_count"],
            y=frame["reviewer"],
            orientation="h",
            marker={"color": colors},
            text=frame["unresolved_count"],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{y}<br>%{x} unresolved<extra></extra>",
        )
    )
    figure.update_layout(
        **{
            **_base_layout("reviewer-workload", max(360, len(frame) * 58 + 130)),
            "showlegend": False,
            "margin": {"l": 150, "r": 42, "t": 24, "b": 48},
        }
    )
    figure.update_xaxes(
        title="Unresolved submissions",
        rangemode="tozero",
        dtick=1,
        zeroline=False,
        gridcolor="rgba(107,114,128,0.14)",
    )
    figure.update_yaxes(
        title=None,
        automargin=True,
        ticklabelstandoff=14,
        gridcolor="rgba(0,0,0,0)",
    )
    return figure
