import unittest
from pathlib import Path

import duckdb


QUERY_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "analytics"
    / "queries"
    / "builder_interventions.sql"
)
REVIEWER_WORKLOAD_QUERY_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "analytics"
    / "queries"
    / "reviewer_workload.sql"
)


class BuilderInterventionsQueryTests(unittest.TestCase):
    def setUp(self):
        self.conn = duckdb.connect(":memory:")
        self.conn.execute(
            """
            CREATE SCHEMA gold;

            CREATE TABLE gold.dim_issue (
                issue_key BIGINT,
                issue_url VARCHAR,
                issue_author VARCHAR
            );
            CREATE TABLE gold.dim_state (state_key BIGINT, state VARCHAR);
            CREATE TABLE gold.dim_status (status_key BIGINT, status VARCHAR);
            CREATE TABLE gold.dim_milestone (
                milestone_key BIGINT,
                milestone VARCHAR,
                milestone_number INTEGER,
                deadline_date DATE
            );
            CREATE TABLE gold.dim_reviewer (
                reviewer_key BIGINT,
                reviewer VARCHAR
            );
            CREATE TABLE gold.fact_submission_snapshot (
                submission_snapshot_key BIGINT,
                issue_key BIGINT,
                state_key BIGINT,
                status_key BIGINT,
                milestone_key BIGINT,
                created_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ,
                extracted_at TIMESTAMPTZ,
                is_assigned BOOLEAN,
                days_since_update BIGINT,
                submission_age_days BIGINT
            );
            CREATE TABLE gold.bridge_submission_reviewer (
                submission_snapshot_key BIGINT,
                reviewer_key BIGINT
            );
            """
        )
        self._insert_dimensions()
        self._insert_snapshots()
        self.query = QUERY_PATH.read_text(encoding="utf-8")
        self.reviewer_workload_query = REVIEWER_WORKLOAD_QUERY_PATH.read_text(
            encoding="utf-8"
        )

    def tearDown(self):
        self.conn.close()

    def _insert_dimensions(self):
        self.conn.executemany(
            "INSERT INTO gold.dim_state VALUES (?, ?)",
            [(1, "OPEN"), (2, "CLOSED")],
        )
        self.conn.executemany(
            "INSERT INTO gold.dim_status VALUES (?, ?)",
            [
                (1, "Unchecked/Unassigned"),
                (2, "In review"),
                (3, "Needs Improvement"),
                (4, "Passed"),
                (5, "Mystery"),
            ],
        )
        deadlines = (
            "2026-06-28",
            "2026-07-19",
            "2026-08-02",
            "2026-09-13",
            "2026-10-11",
            "2026-11-08",
            "2026-12-06",
        )
        self.conn.executemany(
            "INSERT INTO gold.dim_milestone VALUES (?, ?, ?, ?)",
            [(number + 1, f"M{number}", number, deadline) for number, deadline in enumerate(deadlines)],
        )
        self.conn.executemany(
            "INSERT INTO gold.dim_reviewer VALUES (?, ?)",
            [(1, "alpha-reviewer"), (2, "zeta-reviewer")],
        )

    def _insert_snapshots(self):
        issues = [
            (1, "unassigned", "unassigned"),
            (2, "assigned", "assigned"),
            (3, "review", "review"),
            (4, "revise", "revise"),
            (5, "advance", "advance"),
            (6, "complete", "complete"),
            (7, "missing", "missing"),
            (8, "contradiction", "contradiction"),
            (9, "mystery", "mystery"),
            (10, "tie-old", "tie"),
            (11, "tie-new", "tie"),
            (12, "old-only", "old-only"),
            (13, "null-author", None),
        ]
        self.conn.executemany(
            "INSERT INTO gold.dim_issue VALUES (?, ?, ?)",
            [(key, f"https://example.test/{url}", author) for key, url, author in issues],
        )

        latest = "2026-08-17 10:00:00+08"
        older = "2026-08-10 10:00:00+08"
        facts = [
            # key, issue, state, status, milestone, updated, extraction, days, age
            (1, 1, 1, 1, 3, "2026-08-08 10:00:00+08", latest, 9, 20),
            (2, 2, 1, 1, 4, "2026-08-16 10:00:00+08", latest, 1, 10),
            (3, 3, 1, 2, 4, "2026-08-12 10:00:00+08", latest, 5, 12),
            (4, 4, 1, 3, 3, "2026-08-11 10:00:00+08", latest, 6, 18),
            (5, 5, 2, 4, 5, "2026-08-16 10:00:00+08", latest, 1, 4),
            (6, 6, 2, 4, 7, "2026-08-16 10:00:00+08", latest, 1, 3),
            (7, 7, 1, None, 2, "2026-08-13 10:00:00+08", latest, 4, 14),
            (8, 8, 2, 2, 4, "2026-08-05 10:00:00+08", latest, 12, 22),
            (9, 9, 1, 5, 3, "2026-08-02 10:00:00+08", latest, 15, 24),
            (10, 10, 1, 4, 5, "2026-08-15 10:00:00+08", latest, 2, 8),
            (11, 11, 1, 3, 5, "2026-08-16 10:00:00+08", latest, 1, 7),
            (12, 12, 1, 1, 2, "2026-08-09 10:00:00+08", older, 1, 3),
            (13, 13, 1, 1, 2, "2026-08-16 10:00:00+08", latest, 1, 3),
        ]
        self.conn.executemany(
            """
            INSERT INTO gold.fact_submission_snapshot VALUES (
                ?, ?, ?, ?, ?,
                '2026-07-01 10:00:00+08', ?, ?,
                FALSE, ?, ?
            )
            """,
            facts,
        )
        self.conn.executemany(
            "INSERT INTO gold.bridge_submission_reviewer VALUES (?, ?)",
            [(2, 2), (2, 1), (3, 1), (4, 1), (11, 1)],
        )

    def _result(self):
        return self.conn.execute(self.query).fetchdf()

    def test_returns_one_latest_highest_submission_per_builder(self):
        result = self._result()

        self.assertEqual(len(result), 10)
        self.assertEqual(result["builder"].nunique(), 10)
        self.assertNotIn("old-only", result["builder"].tolist())
        self.assertFalse(result["builder"].isna().any())

        tie = result.set_index("builder").loc["tie"]
        self.assertEqual(tie["status"], "Needs Improvement")
        self.assertEqual(tie["issue_url"], "https://example.test/tie-new")

    def test_derives_every_workflow_action_with_abnormal_precedence(self):
        rows = self._result().set_index("builder")
        expected = {
            "unassigned": ("Program admin", "Assign a reviewer"),
            "assigned": ("Reviewer", "Start review"),
            "review": ("Reviewer", "Complete review"),
            "revise": ("Builder", "Revise and resubmit"),
            "advance": ("Builder", "Begin next milestone"),
            "complete": ("None", "Program complete"),
            "missing": ("Program admin", "Verify submission status"),
            "contradiction": (
                "Program admin",
                "Verify or reopen unresolved issue",
            ),
            "mystery": ("Program admin", "Verify submission status"),
        }

        for builder, (actor, action) in expected.items():
            with self.subTest(builder=builder):
                self.assertEqual(rows.loc[builder, "next_actor"], actor)
                self.assertEqual(rows.loc[builder, "next_action"], action)

    def test_aggregates_reviewers_without_duplicate_builders(self):
        result = self._result()
        assigned = result.set_index("builder").loc["assigned"]

        self.assertEqual(assigned["reviewer"], "alpha-reviewer, zeta-reviewer")
        self.assertEqual((result["builder"] == "assigned").sum(), 1)
        self.assertEqual(
            result.set_index("builder").loc["unassigned", "reviewer"],
            "Unassigned",
        )

    def test_sorts_abnormal_records_first_by_staleness(self):
        result = self._result()

        self.assertEqual(
            result.head(3)["builder"].tolist(),
            ["mystery", "contradiction", "missing"],
        )
        self.assertEqual(result.head(3)["days_since_update"].tolist(), [15, 12, 4])

    def test_counts_latest_open_unresolved_work_per_reviewer(self):
        result = self.conn.execute(self.reviewer_workload_query).fetchdf()
        workload = dict(zip(result["reviewer"], result["unresolved_count"], strict=True))

        self.assertEqual(
            workload,
            {
                "Unassigned": 4,
                "alpha-reviewer": 4,
                "zeta-reviewer": 1,
            },
        )

    def test_reviewer_workload_excludes_closed_passed_and_old_snapshots(self):
        result = self.conn.execute(self.reviewer_workload_query).fetchdf()

        self.assertEqual(result["unresolved_count"].sum(), 9)
        self.assertNotIn("old-only", result["reviewer"].tolist())


if __name__ == "__main__":
    unittest.main()
