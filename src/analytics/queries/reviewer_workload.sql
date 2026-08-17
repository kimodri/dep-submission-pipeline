WITH latest_extraction AS (
    SELECT *
    FROM gold.fact_submission_snapshot
    WHERE extracted_at = (
        SELECT MAX(extracted_at)
        FROM gold.fact_submission_snapshot
    )
),

unresolved_submissions AS (
    SELECT f.submission_snapshot_key
    FROM latest_extraction AS f
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
