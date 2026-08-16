import unittest
from datetime import date
from unittest.mock import MagicMock, Mock, patch

import duckdb
import pandas as pd

import pipeline.__main__ as entrypoint
from pipeline.etl.gold import transform_silver_to_gold
from pipeline.etl.load import (
    create_pipeline_tables,
    extract_pending_silver,
    load_gold,
    load_silver,
)
from pipeline.models import MotherDuckConfig


def _silver_row(
    issue_id: str,
    *,
    author: str | None = "builder",
    milestone: str = "M2",
    status: str | None = "In review",
    reviewers: list[str] | None = None,
    extracted_at: str = "2026-08-03T00:00:00Z",
    run_id: str = "run-1",
) -> dict:
    reviewer_list = reviewers or []
    return {
        "issue_id": issue_id,
        "issue_title": f"[{milestone}] Example submission",
        "issue_url": f"https://example.com/{issue_id}",
        "issue_author": author,
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-02T00:00:00Z",
        "state": "OPEN",
        "reviewer": reviewer_list,
        "milestone": milestone,
        "status": status,
        "run_id": run_id,
        "extracted_at": extracted_at,
        "is_assigned": bool(reviewer_list),
        "days_since_update": 1,
        "submission_age_days": 2,
    }


class TransformSilverToGoldTests(unittest.TestCase):
    def test_creates_star_dimensions_and_one_submission_fact(self):
        result = transform_silver_to_gold(
            pd.DataFrame([_silver_row("issue-1", reviewers=["reviewer"])])
        )

        self.assertEqual(
            set(result["dimensions"]),
            {
                "dim_issue",
                "dim_reviewer",
                "dim_state",
                "dim_status",
                "dim_milestone",
                "dim_date",
            },
        )
        fact = result["fact_submission_snapshot"]
        self.assertEqual(len(fact), 1)
        self.assertEqual(fact["submission_snapshot_key"].tolist(), [1])
        for column in (
            "issue_key",
            "state_key",
            "status_key",
            "milestone_key",
            "created_at_key",
            "updated_at_key",
            "extracted_at_key",
        ):
            self.assertFalse(fact[column].isna().any())

    def test_explodes_reviewers_only_in_the_bridge(self):
        result = transform_silver_to_gold(
            pd.DataFrame(
                [
                    _silver_row(
                        "assigned",
                        reviewers=["alice", "bob", "alice"],
                    ),
                    _silver_row("unassigned"),
                ]
            )
        )

        fact = result["fact_submission_snapshot"]
        bridge = result["bridge_submission_reviewer"]
        dim_reviewer = result["dimensions"]["dim_reviewer"]

        self.assertEqual(len(fact), 2)
        self.assertNotIn("reviewer", fact.columns)
        self.assertEqual(len(bridge), 2)
        self.assertEqual(set(dim_reviewer["reviewer"]), {"alice", "bob"})
        assigned_key = fact.loc[
            fact["is_assigned"], "submission_snapshot_key"
        ].item()
        self.assertEqual(set(bridge["submission_snapshot_key"]), {assigned_key})

    def test_adds_milestone_numbers_and_deadlines(self):
        result = transform_silver_to_gold(
            pd.DataFrame(
                [
                    _silver_row("issue-m0", milestone="M0"),
                    _silver_row("issue-m6", milestone="M6"),
                ]
            )
        )
        milestones = result["dimensions"]["dim_milestone"].set_index(
            "milestone"
        )

        self.assertEqual(milestones.loc["M0", "milestone_number"], 0)
        self.assertEqual(
            milestones.loc["M0", "deadline_date"], date(2026, 6, 28)
        )
        self.assertEqual(milestones.loc["M6", "milestone_number"], 6)
        self.assertEqual(
            milestones.loc["M6", "deadline_date"], date(2026, 12, 6)
        )

    def test_preserves_multiple_extractions_of_the_same_issue(self):
        result = transform_silver_to_gold(
            pd.DataFrame(
                [
                    _silver_row("issue-1"),
                    _silver_row(
                        "issue-1",
                        extracted_at="2026-08-04T00:00:00Z",
                        run_id="run-2",
                    ),
                ]
            )
        )

        self.assertEqual(len(result["dimensions"]["dim_issue"]), 1)
        self.assertEqual(len(result["fact_submission_snapshot"]), 2)

    def test_handles_nullable_status_and_author_without_mutating_input(self):
        silver = pd.DataFrame(
            [_silver_row("issue-1", author=None, status=None)]
        )
        original = silver.copy(deep=True)

        result = transform_silver_to_gold(silver)

        pd.testing.assert_frame_equal(silver, original)
        fact = result["fact_submission_snapshot"]
        self.assertTrue(fact["status_key"].isna().all())
        self.assertTrue(
            result["dimensions"]["dim_issue"]["issue_author"].isna().all()
        )

    def test_rejects_duplicate_submission_snapshots(self):
        silver = pd.DataFrame(
            [_silver_row("issue-1"), _silver_row("issue-1")]
        )

        with self.assertRaisesRegex(
            ValueError,
            "unique by issue_id and extracted_at",
        ):
            transform_silver_to_gold(silver)

    def test_excludes_legacy_builder_columns_from_the_fact(self):
        silver = pd.DataFrame([_silver_row("issue-1")]).assign(
            current_milestone="M3",
            builder_status="on_track",
            schedule_status="on_track",
        )

        fact = transform_silver_to_gold(silver)["fact_submission_snapshot"]

        self.assertFalse(
            {
                "current_milestone",
                "builder_status",
                "schedule_status",
            }
            & set(fact.columns)
        )


class GoldLoadingTests(unittest.TestCase):
    def setUp(self):
        self.conn = duckdb.connect(":memory:")
        create_pipeline_tables(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_creates_gold_tables_and_completion_tracking(self):
        tables = set(
            row[0]
            for row in self.conn.execute(
                """
                SELECT table_schema || '.' || table_name AS qualified_name
                FROM information_schema.tables
                WHERE table_schema IN ('gold', 'ops')
                """
            ).fetchall()
        )

        self.assertTrue(
            {
                "gold.dim_issue",
                "gold.dim_reviewer",
                "gold.dim_state",
                "gold.dim_status",
                "gold.dim_milestone",
                "gold.dim_date",
                "gold.fact_submission_snapshot",
                "gold.bridge_submission_reviewer",
                "ops.gold_loads",
            }.issubset(tables)
        )

    def test_extracts_pending_silver_by_run_and_ignores_legacy_columns(self):
        load_silver(
            self.conn,
            pd.DataFrame(
                [
                    _silver_row("issue-1", run_id="run-1"),
                    _silver_row(
                        "issue-2",
                        run_id="run-2",
                        extracted_at="2026-08-04T00:00:00Z",
                    ),
                ]
            ),
        )
        self.conn.execute(
            "ALTER TABLE silver.issue_submissions ADD COLUMN builder_status VARCHAR"
        )
        self.conn.execute(
            """
            INSERT INTO ops.gold_loads (run_id, extracted_at)
            VALUES ('run-1', TIMESTAMPTZ '2026-08-03 00:00:00+00')
            """
        )

        pending = extract_pending_silver(self.conn)

        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["run_id"].unique().tolist(), ["run-2"])
        self.assertNotIn("builder_status", pending[0].columns)

    def test_reuses_dimension_keys_and_updates_issue_attributes(self):
        first_silver = pd.DataFrame(
            [_silver_row("issue-1", reviewers=["alice"])]
        )
        load_gold(self.conn, transform_silver_to_gold(first_silver))
        first_issue_key = self.conn.execute(
            "SELECT issue_key FROM gold.dim_issue WHERE issue_id = 'issue-1'"
        ).fetchone()[0]

        second_silver = pd.DataFrame(
            [
                _silver_row(
                    "issue-1",
                    author="renamed-builder",
                    reviewers=["alice", "bob"],
                    status="Passed",
                    run_id="run-2",
                    extracted_at="2026-08-04T00:00:00Z",
                )
            ]
        )
        second_silver.loc[0, "issue_title"] = "Updated title"
        second_silver.loc[0, "issue_url"] = "https://example.com/updated"
        load_gold(self.conn, transform_silver_to_gold(second_silver))

        issue = self.conn.execute(
            """
            SELECT issue_key, issue_title, issue_url, issue_author
            FROM gold.dim_issue
            WHERE issue_id = 'issue-1'
            """
        ).fetchone()
        fact_issue_keys = self.conn.execute(
            "SELECT DISTINCT issue_key FROM gold.fact_submission_snapshot"
        ).fetchall()

        self.assertEqual(
            issue,
            (
                first_issue_key,
                "Updated title",
                "https://example.com/updated",
                "renamed-builder",
            ),
        )
        self.assertEqual(fact_issue_keys, [(first_issue_key,)])
        self.assertEqual(
            self.conn.execute("SELECT count(*) FROM gold.dim_reviewer").fetchone()[0],
            2,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT count(*) FROM gold.bridge_submission_reviewer"
            ).fetchone()[0],
            3,
        )
        self.assertEqual(
            self.conn.execute("SELECT count(*) FROM ops.gold_loads").fetchone()[0],
            2,
        )

    def test_rolls_back_all_gold_changes_when_fact_insert_fails(self):
        first_silver = pd.DataFrame(
            [_silver_row("issue-1", reviewers=["alice"])]
        )
        load_gold(self.conn, transform_silver_to_gold(first_silver))

        conflicting_silver = pd.DataFrame(
            [
                _silver_row(
                    "issue-1",
                    reviewers=["new-reviewer"],
                    run_id="run-2",
                )
            ]
        )
        conflicting_silver.loc[0, "issue_title"] = "Should roll back"

        with self.assertRaises(duckdb.ConstraintException):
            load_gold(
                self.conn,
                transform_silver_to_gold(conflicting_silver),
            )

        self.assertEqual(
            self.conn.execute(
                "SELECT issue_title FROM gold.dim_issue WHERE issue_id = 'issue-1'"
            ).fetchone()[0],
            "[M2] Example submission",
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT count(*) FROM gold.dim_reviewer WHERE reviewer = 'new-reviewer'"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT count(*) FROM gold.fact_submission_snapshot"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT count(*) FROM ops.gold_loads WHERE run_id = 'run-2'"
            ).fetchone()[0],
            0,
        )

    def test_completed_gold_run_is_not_pending_again(self):
        silver = pd.DataFrame([_silver_row("issue-1")])
        load_silver(self.conn, silver)
        load_gold(self.conn, transform_silver_to_gold(silver))

        self.assertEqual(extract_pending_silver(self.conn), [])


class GoldOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.conn = Mock()
        self.connection_context = MagicMock()
        self.connection_context.__enter__.return_value = self.conn
        self.connection_factory = Mock(return_value=self.connection_context)
        self.first = pd.DataFrame({"run_id": ["run-1"]})
        self.second = pd.DataFrame({"run_id": ["run-2"]})

    @staticmethod
    def _gold_tables(run_id: str) -> dict:
        return {
            "dimensions": {},
            "fact_submission_snapshot": pd.DataFrame({"run_id": [run_id]}),
            "bridge_submission_reviewer": pd.DataFrame(),
        }

    def test_pending_runs_transform_and_load_in_order(self):
        events = []

        with (
            patch.object(
                entrypoint,
                "create_pipeline_tables",
                side_effect=lambda conn: events.append("create_tables"),
            ),
            patch.object(
                entrypoint,
                "extract_pending_silver",
                side_effect=lambda conn: (
                    events.append("extract_pending") or [self.first, self.second]
                ),
            ),
            patch.object(
                entrypoint,
                "transform_silver_to_gold",
                side_effect=lambda df: (
                    events.append(f"transform:{df['run_id'].iloc[0]}")
                    or self._gold_tables(df["run_id"].iloc[0])
                ),
            ),
            patch.object(
                entrypoint,
                "load_gold",
                side_effect=lambda conn, tables: events.append(
                    f"load:{tables['fact_submission_snapshot']['run_id'].iloc[0]}"
                ),
            ),
        ):
            entrypoint._run_pending_gold(self.connection_factory)

        self.assertEqual(
            events,
            [
                "create_tables",
                "extract_pending",
                "transform:run-1",
                "load:run-1",
                "transform:run-2",
                "load:run-2",
            ],
        )

    def test_no_pending_runs_exits_without_transforming(self):
        with (
            patch.object(entrypoint, "create_pipeline_tables"),
            patch.object(entrypoint, "extract_pending_silver", return_value=[]),
            patch.object(entrypoint, "transform_silver_to_gold") as transform,
            patch.object(entrypoint, "load_gold") as load,
            patch.object(entrypoint.logger, "info") as log,
        ):
            entrypoint._run_pending_gold(self.connection_factory)

        transform.assert_not_called()
        load.assert_not_called()
        log.assert_called_once_with("No pending Silver runs to load into Gold")

    def test_transform_or_load_error_is_logged_and_reraised(self):
        error = ValueError("invalid Gold batch")
        with (
            patch.object(entrypoint, "create_pipeline_tables"),
            patch.object(
                entrypoint,
                "extract_pending_silver",
                return_value=[self.first],
            ),
            patch.object(
                entrypoint,
                "transform_silver_to_gold",
                side_effect=error,
            ),
            patch.object(entrypoint, "load_gold") as load,
            patch.object(entrypoint.logger, "exception") as log,
        ):
            with self.assertRaises(ValueError):
                entrypoint._run_pending_gold(self.connection_factory)

        load.assert_not_called()
        log.assert_called_once_with("Gold failed run_id=%s", "run-1")

    def test_load_error_is_logged_and_reraised(self):
        error = duckdb.ConstraintException("invalid Gold rows")
        gold_tables = self._gold_tables("run-1")
        with (
            patch.object(entrypoint, "create_pipeline_tables"),
            patch.object(
                entrypoint,
                "extract_pending_silver",
                return_value=[self.first],
            ),
            patch.object(
                entrypoint,
                "transform_silver_to_gold",
                return_value=gold_tables,
            ),
            patch.object(entrypoint, "load_gold", side_effect=error) as load,
            patch.object(entrypoint.logger, "exception") as log,
        ):
            with self.assertRaises(duckdb.ConstraintException):
                entrypoint._run_pending_gold(self.connection_factory)

        load.assert_called_once_with(self.conn, gold_tables)
        log.assert_called_once_with("Gold failed run_id=%s", "run-1")

    def test_gold_command_uses_motherduck_connection(self):
        config = MotherDuckConfig(
            database_path="md:example",
            token="motherduck-secret",
        )
        connection = Mock()

        with (
            patch.object(
                entrypoint,
                "init_motherduck_config",
                return_value=config,
            ) as init_config,
            patch.object(
                entrypoint,
                "get_database_connection",
                return_value=connection,
            ) as get_connection,
            patch.object(entrypoint, "_run_pending_gold") as run,
        ):
            entrypoint.gold_manual()
            connection_factory = run.call_args.args[0]
            self.assertIs(connection_factory(), connection)
            init_config.assert_called_once_with()
            get_connection.assert_called_once_with(config)


if __name__ == "__main__":
    unittest.main()
