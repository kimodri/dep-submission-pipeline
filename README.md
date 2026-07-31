# DEP Open Track Submission Pipeline
This year the Data Engineering Pilipinas has held its Open Track Program where they have accepted 50 builders to learn data engineering. The tracking of the builders, however, poses a challenge where it is difficult to see where milestones a builder is in.

### Grain: One row represents the state of one submission as observed during one pipeline extraction.
Given the grain the uniqueness rule should be:

- `UNIQUE(issue_id, extracted_at)`
- The fact table also falls under the `periodic snapshot fact table`