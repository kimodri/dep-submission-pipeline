WITH milestone_total AS (
    SELECT COUNT(*) AS total_milestones
    FROM gold.dim_milestone
),

builder_completion AS (
    SELECT
        f.extracted_at,
        i.issue_author,

        COUNT(DISTINCT f.milestone_key)
            FILTER (WHERE s.status = 'Passed')
            AS passed_milestones,

        mt.total_milestones,

        COUNT(DISTINCT f.milestone_key)
            FILTER (WHERE s.status = 'Passed')
            * 1.0
            / NULLIF(mt.total_milestones, 0)
            AS completion_rate

    FROM gold.fact_submission_snapshot AS f

    JOIN gold.dim_issue AS i
        USING (issue_key)

    LEFT JOIN gold.dim_status AS s
        USING (status_key)

    CROSS JOIN milestone_total AS mt

    WHERE i.issue_author IS NOT NULL

    GROUP BY
        f.extracted_at,
        i.issue_author,
        mt.total_milestones
)

SELECT
    extracted_at,
    CAST(
        extracted_at AT TIME ZONE 'Asia/Manila'
        AS DATE
    ) AS extraction_date,

    ROUND(
        AVG(completion_rate) * 100,
        2
    ) AS average_completion_percentage,

    COUNT(*) AS observed_builder_count

FROM builder_completion

GROUP BY
    extracted_at

ORDER BY
    extracted_at;