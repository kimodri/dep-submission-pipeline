WITH latest_extraction AS (
    SELECT *
    FROM gold.fact_submission_snapshot
    WHERE extracted_at = (
        SELECT MAX(extracted_at)
        FROM gold.fact_submission_snapshot
    )
),

ranked_builder_submissions AS (
    SELECT
        f.submission_snapshot_key,
        f.state_key,
        f.status_key,
        ROW_NUMBER() OVER (
            PARTITION BY i.issue_author
            ORDER BY
                m.milestone_number DESC,
                f.updated_at DESC,
                f.created_at DESC,
                f.issue_key DESC,
                f.submission_snapshot_key DESC
        ) AS builder_row_number
    FROM latest_extraction AS f
    JOIN gold.dim_issue AS i
        USING (issue_key)
    JOIN gold.dim_milestone AS m
        USING (milestone_key)
    WHERE i.issue_author IS NOT NULL
),

current_builder_submissions AS (
    SELECT
        submission_snapshot_key,
        state_key,
        status_key
    FROM ranked_builder_submissions
    WHERE builder_row_number = 1
),

unresolved_submissions AS (
    SELECT f.submission_snapshot_key
    FROM current_builder_submissions AS f
    JOIN gold.dim_state AS st
        USING (state_key)
    LEFT JOIN gold.dim_status AS s
        USING (status_key)
    WHERE UPPER(st.state) = 'OPEN'
      AND (s.status IS NULL OR s.status <> 'Passed')
),

reviewer_assignments AS (
    SELECT
        u.submission_snapshot_key,
        COALESCE(r.reviewer, 'Unassigned') AS reviewer
    FROM unresolved_submissions AS u
    LEFT JOIN gold.bridge_submission_reviewer AS b
        USING (submission_snapshot_key)
    LEFT JOIN gold.dim_reviewer AS r
        USING (reviewer_key)
)

SELECT
    reviewer,
    COUNT(DISTINCT submission_snapshot_key) AS unresolved_count
FROM reviewer_assignments
GROUP BY reviewer
ORDER BY
    unresolved_count DESC,
    reviewer;
