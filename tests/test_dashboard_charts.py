import unittest

import pandas as pd

from dashboard.charts import (
    MILESTONES,
    STATUS_COLORS,
    build_progress_chart,
    build_reviewer_workload_chart,
    build_submission_status_chart,
)


class DashboardChartTests(unittest.TestCase):
    def test_submission_chart_uses_original_palette_for_gold_statuses(self):
        frame = pd.DataFrame(
            [
                {"milestone": "M0", "status": "Passed", "submission_count": 4},
                {"milestone": "M0", "status": "In review", "submission_count": 3},
                {
                    "milestone": "M0",
                    "status": "Needs Improvement",
                    "submission_count": 2,
                },
                {
                    "milestone": "M0",
                    "status": "Unchecked/Unassigned",
                    "submission_count": 1,
                },
            ]
        )

        figure = build_submission_status_chart(frame)
        colors = {trace.name: trace.marker.color for trace in figure.data}

        self.assertEqual(
            colors,
            {
                "Passed": "#10b981",
                "In review": "#2563eb",
                "Needs Improvement": "#f59e0b",
                "Unchecked/Unassigned": "#ef4444",
            },
        )

    def test_submission_chart_orders_milestones_and_uses_status_colors(self):
        frame = pd.DataFrame(
            [
                {"milestone": "M2", "status": "Accepted", "submission_count": 3},
                {"milestone": "M1", "status": "In review", "submission_count": 2},
            ]
        )

        figure = build_submission_status_chart(frame)
        accepted_trace = next(trace for trace in figure.data if trace.name == "Accepted")

        self.assertEqual(list(accepted_trace.x), list(MILESTONES))
        self.assertEqual(list(accepted_trace.y), [0, 0, 3, 0, 0, 0, 0])
        self.assertEqual(figure.layout.barmode, "stack")
        self.assertEqual(accepted_trace.marker.color, STATUS_COLORS["Accepted"])

    def test_progress_chart_orders_extraction_dates(self):
        frame = pd.DataFrame(
            {
                "extraction_date": pd.to_datetime(["2026-08-10", "2026-08-03"]),
                "completion_rate": [60, 50],
            }
        )

        figure = build_progress_chart(frame)

        self.assertEqual(list(figure.data[0].y), [50, 60])
        self.assertEqual(figure.data[0].mode, "lines+markers")

    def test_reviewer_chart_highlights_unassigned_work(self):
        frame = pd.DataFrame(
            {"reviewer": ["Reviewer A", "Unassigned"], "unresolved_count": [4, 7]}
        )

        figure = build_reviewer_workload_chart(frame)

        colors = dict(zip(figure.data[0].y, figure.data[0].marker.color, strict=True))
        self.assertEqual(colors["Unassigned"], "#f59e0b")
        self.assertEqual(figure.data[0].orientation, "h")
        self.assertTrue(figure.layout.yaxis.automargin)
        self.assertEqual(figure.layout.yaxis.ticklabelstandoff, 14)
        self.assertFalse(figure.layout.xaxis.zeroline)

    def test_chart_builders_render_empty_states(self):
        empty_status = pd.DataFrame(columns=["milestone", "status", "submission_count"])

        figure = build_submission_status_chart(empty_status)

        self.assertEqual(len(figure.data), 0)
        self.assertIn("not available", figure.layout.annotations[0].text)
