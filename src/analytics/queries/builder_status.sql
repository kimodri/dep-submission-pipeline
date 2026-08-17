WITH extraction_as_of AS (
    SELECT
        MAX(extracted_at) AS extracted_at,
        CAST(
            MAX(extracted_at) AT TIME ZONE 'Asia/Manila'
            AS DATE
        ) AS as_of_date
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

builder_highest_milestone AS (
    SELECT
        i.issue_author,
        MAX(m.milestone_number) AS milestone_number
    FROM latest_extraction AS f
    JOIN gold.dim_issue AS i
        USING (issue_key)
    JOIN gold.dim_milestone AS m
        USING (milestone_key)
    WHERE i.issue_author IS NOT NULL
    GROUP BY i.issue_author
),

builder_schedule AS (
    SELECT
        b.issue_author,
        b.milestone_number AS builder_milestone_number,
        e.milestone_number AS expected_milestone_number,

        GREATEST(
            e.milestone_number - b.milestone_number,
            0
        ) AS milestones_behind,

        CASE
            WHEN b.milestone_number >= e.milestone_number - 1
                THEN 'on_track'
            ELSE 'delayed'
        END AS schedule_status
    FROM builder_highest_milestone AS b
    CROSS JOIN expected_milestone AS e
)

SELECT
    schedule_status,
    COUNT(*) AS builder_count,
    ROUND(
        100.0 * COUNT(*) / SUM(COUNT(*)) OVER (),
        2
    ) AS builder_percentage
FROM builder_schedule
GROUP BY schedule_status
ORDER BY schedule_status;