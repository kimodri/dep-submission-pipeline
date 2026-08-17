WITH extraction_as_of AS (
    SELECT
        MAX(extracted_at) AS extracted_at,
        CAST(MAX(extracted_at) AT TIME ZONE 'Asia/Manila' AS DATE) AS as_of_date
    FROM gold.fact_submission_snapshot
),

latest_extraction AS (
    SELECT f.*
    FROM gold.fact_submission_snapshot AS f
    CROSS JOIN extraction_as_of AS a
    WHERE f.extracted_at = a.extracted_at
),

expected_milestone AS (
    SELECT
        COALESCE(
            MIN(m.milestone_number)
                FILTER (WHERE m.deadline_date >= a.as_of_date),
            MAX(m.milestone_number)
        ) AS milestone_number
    FROM gold.dim_milestone AS m
    CROSS JOIN extraction_as_of AS a
),

final_milestone AS (
    SELECT MAX(milestone_number) AS milestone_number
    FROM gold.dim_milestone
),

ranked_submissions AS (
    SELECT
        f.submission_snapshot_key,
        i.issue_author AS builder,
        i.issue_url,
        m.milestone AS current_milestone,
        m.milestone_number,
        s.status AS raw_status,
        st.state AS issue_state,
        f.submission_age_days,
        f.days_since_update,
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
    JOIN gold.dim_state AS st
        USING (state_key)
    LEFT JOIN gold.dim_status AS s
        USING (status_key)
    WHERE i.issue_author IS NOT NULL
),

current_submissions AS (
    SELECT *
    FROM ranked_submissions
    WHERE builder_row_number = 1
),

submission_reviewers AS (
    SELECT
        b.submission_snapshot_key,
        STRING_AGG(DISTINCT r.reviewer, ', ' ORDER BY r.reviewer) AS reviewer,
        COUNT(DISTINCT r.reviewer_key) AS reviewer_count
    FROM gold.bridge_submission_reviewer AS b
    JOIN gold.dim_reviewer AS r
        USING (reviewer_key)
    GROUP BY b.submission_snapshot_key
),

classified_interventions AS (
    SELECT
        c.builder,
        c.current_milestone,
        COALESCE(c.raw_status, 'Unknown') AS status,
        CASE
            WHEN c.milestone_number >= e.milestone_number - 1 THEN 'On track'
            ELSE 'Delayed'
        END AS schedule_status,
        COALESCE(r.reviewer, 'Unassigned') AS reviewer,
        c.issue_state,
        c.submission_age_days,
        c.days_since_update,
        CASE
            WHEN c.raw_status IS NULL
                OR c.raw_status NOT IN (
                    'Unchecked/Unassigned', 'In review',
                    'Needs Improvement', 'Passed'
                ) THEN 'Program admin'
            WHEN UPPER(c.issue_state) = 'CLOSED'
                AND c.raw_status <> 'Passed' THEN 'Program admin'
            WHEN c.raw_status = 'Unchecked/Unassigned'
                AND COALESCE(r.reviewer_count, 0) = 0 THEN 'Program admin'
            WHEN c.raw_status IN ('Unchecked/Unassigned', 'In review') THEN 'Reviewer'
            WHEN c.raw_status = 'Needs Improvement' THEN 'Builder'
            WHEN c.raw_status = 'Passed'
                AND c.milestone_number < fm.milestone_number THEN 'Builder'
            ELSE 'None'
        END AS next_actor,
        CASE
            WHEN c.raw_status IS NULL
                OR c.raw_status NOT IN (
                    'Unchecked/Unassigned', 'In review',
                    'Needs Improvement', 'Passed'
                ) THEN 'Verify submission status'
            WHEN UPPER(c.issue_state) = 'CLOSED'
                AND c.raw_status <> 'Passed' THEN 'Verify or reopen unresolved issue'
            WHEN c.raw_status = 'Unchecked/Unassigned'
                AND COALESCE(r.reviewer_count, 0) = 0 THEN 'Assign a reviewer'
            WHEN c.raw_status = 'Unchecked/Unassigned' THEN 'Start review'
            WHEN c.raw_status = 'In review' THEN 'Complete review'
            WHEN c.raw_status = 'Needs Improvement' THEN 'Revise and resubmit'
            WHEN c.raw_status = 'Passed'
                AND c.milestone_number < fm.milestone_number THEN 'Begin next milestone'
            ELSE 'Program complete'
        END AS next_action,
        c.issue_url,
        CASE
            WHEN c.raw_status IS NULL
                OR c.raw_status NOT IN (
                    'Unchecked/Unassigned', 'In review',
                    'Needs Improvement', 'Passed'
                )
                OR (
                    UPPER(c.issue_state) = 'CLOSED'
                    AND c.raw_status <> 'Passed'
                ) THEN 0
            WHEN c.raw_status <> 'Passed' THEN 1
            WHEN c.milestone_number < fm.milestone_number THEN 2
            ELSE 3
        END AS sort_priority
    FROM current_submissions AS c
    LEFT JOIN submission_reviewers AS r
        USING (submission_snapshot_key)
    CROSS JOIN expected_milestone AS e
    CROSS JOIN final_milestone AS fm
)

SELECT
    builder,
    current_milestone,
    status,
    schedule_status,
    reviewer,
    issue_state,
    submission_age_days,
    days_since_update,
    next_actor,
    next_action,
    issue_url
FROM classified_interventions
ORDER BY
    sort_priority,
    days_since_update DESC,
    builder;
