# DEP Open Track Submission Pipeline
This year the Data Engineering Pilipinas has held its Open Track Program where they have accepted 50 builders to learn data engineering. The tracking of the builders, however, poses a challenge where it is difficult to see where milestones a builder is in.

### Grain: One row represents the state of one submission as observed during one pipeline extraction.
Given the grain the uniqueness rule should be:

- `UNIQUE(issue_id, extracted_at)`
- The fact table also falls under the `periodic snapshot fact table`

## Bronze deployment

The Bronze workflow stores pipeline execution state separately from complete
source payloads:

- `ops.pipeline_attempts` records one immutable final outcome for each GitHub
  Actions attempt: `succeeded` or `failed`. Failed rows identify whether the
  error occurred during extraction or Bronze loading.
- `bronze.raw_issue_extractions` stores only complete successful GraphQL
  payloads.

GitHub Actions supplies `GITHUB_RUN_ID` and `GITHUB_RUN_ATTEMPT` automatically.
Local runs use a generated `local-<uuid>` run ID and attempt number `1`.

Configure these GitHub repository secrets:

- `DEP_GITHUB_TOKEN`
- `MOTHERDUCK_TOKEN`

Configure these GitHub repository variables:

- `OWNER_NAME`
- `OWNER_TYPE`
- `PROJECT_NUMBER`
- `MOTHERDUCKDB_PATH` (for example, `md:dep_submission_db`)

Run **Bronze ingestion** manually once from the repository's Actions tab before
relying on its schedule. The workflow then runs every three hours at minute 17,
using the Manila cycle `00:17, 03:17, ..., 21:17`.
