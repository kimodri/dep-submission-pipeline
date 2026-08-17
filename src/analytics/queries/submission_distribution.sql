WITH latest_extraction AS (
    SELECT *
    FROM gold.fact_submission_snapshot
    WHERE extracted_at = (
        SELECT MAX(extracted_at)
        FROM gold.fact_submission_snapshot
    )
)
SELECT
    m.milestone,
    s.status,
    COUNT(le.submission_snapshot_key) AS submission_count
FROM gold.dim_milestone AS m
CROSS JOIN gold.dim_status AS s
LEFT JOIN latest_extraction AS le
    ON le.milestone_key = m.milestone_key
   AND le.status_key = s.status_key
GROUP BY
    m.milestone,
    m.milestone_number,
    s.status
ORDER BY
    m.milestone_number,
    s.status;