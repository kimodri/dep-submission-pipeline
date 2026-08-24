# DEP Open Track Submission Pipeline
### Background
This year the Data Engineering Pilipinas has held its Open Track Program where they have accepted 50 builders to learn the basics of data engineering. 

The tracking of the builders, however, poses a challenge where it is difficult to see where milestones a builder is in or how they are doing which inspires this data pipeline.

---
### Data Model/Architecture
This pipeline follows the medallion architecture with:
- **Bronze**: raw data
- **Silver**: cleaned and validated data
- **Gold**: Modeled data

```mermaid
flowchart LR
    subgraph bronze["Bronze"]
        raw["bronze.raw_issue_extractions"]
    end

    subgraph silver["Silver"]
        submissions["silver.issue_submissions"]
    end

    subgraph gold["Gold"]
        fact["gold.fact_submission_snapshot"]
        issue["gold.dim_issue"]
        reviewer["gold.dim_reviewer"]
        state["gold.dim_state"]
        status["gold.dim_status"]
        milestone["gold.dim_milestone"]
        date["gold.dim_date"]
        bridge["gold.bridge_submission_reviewer"]

        issue --> fact
        state --> fact
        status --> fact
        milestone --> fact
        date --> fact
        fact --> bridge
        reviewer --> bridge
    end

    raw --> submissions --> fact
```

**Bronze** contains the raw extractions and the metadata needed to be true to the source and allow reruns:

```mermaid
flowchart TB
    subgraph raw["bronze.raw_issue_extractions"]
        direction TB
        key["Composite primary key<br/><b>run_id</b>: VARCHAR<br/><b>attempt_number</b>: INTEGER"]
        metadata["Extraction metadata<br/><b>extracted_at</b>: TIMESTAMPTZ"]
        payload["Source data<br/><b>payload</b>: JSON"]
        key --- metadata --- payload
    end
```

**Silver** contains the cleaned, validated, and derived data needed for analysis:

```mermaid
flowchart TB
    subgraph silver["silver.issue_submissions"]
        direction TB
        identity["Composite primary key<br/><b>run_id</b>: VARCHAR<br/><b>issue_id</b>: VARCHAR"]
        source["Issue attributes<br/><b>issue_title</b>: VARCHAR<br/><b>issue_url</b>: VARCHAR<br/><b>issue_author</b>: VARCHAR (nullable)"]
        workflow["Workflow state<br/><b>state</b>: VARCHAR<br/><b>reviewer</b>: VARCHAR[]<br/><b>milestone</b>: VARCHAR<br/><b>status</b>: VARCHAR (nullable)<br/><b>is_assigned</b>: BOOLEAN"]
        timing["Timestamps and derived metrics<br/><b>created_at</b>: TIMESTAMPTZ<br/><b>updated_at</b>: TIMESTAMPTZ<br/><b>extracted_at</b>: TIMESTAMPTZ<br/><b>days_since_update</b>: BIGINT<br/><b>submission_age_days</b>: BIGINT"]
        identity --- source --- workflow --- timing
    end
```


**Gold** contains a modeled schema for easier query. In addition this Gold architecture follows the **Kimball Model**.


- **Grain**
In Kimball architecture, after business alignment with the project's goals, the developer should go right into definition of the grain and that is what a row in a table represents.

For this project:
> One row represents the state of one submission as observed during one pipeline extraction.

Given the grain the uniqueness rule should be:

- `UNIQUE(issue_key, extracted_at)`
- The fact table also falls under the `periodic snapshot fact table`

Only after this definition, the developer should go after `dimensions` and `measurements/facts`:

```mermaid
flowchart TB
    issue["<b>gold.dim_issue</b><br/>PK issue_key: BIGINT<br/>UK issue_id: VARCHAR<br/>issue_title: VARCHAR<br/>issue_url: VARCHAR<br/>issue_author: VARCHAR (nullable)"]
    state["<b>gold.dim_state</b><br/>PK state_key: BIGINT<br/>UK state: VARCHAR"]
    status["<b>gold.dim_status</b><br/>PK status_key: BIGINT<br/>UK status: VARCHAR"]
    milestone["<b>gold.dim_milestone</b><br/>PK milestone_key: BIGINT<br/>UK milestone: VARCHAR<br/>milestone_number: INTEGER (nullable)<br/>deadline_date: DATE (nullable)"]
    date["<b>gold.dim_date</b><br/>PK date_key: BIGINT<br/>UK date: DATE<br/>year: INTEGER<br/>month: INTEGER<br/>month_name: VARCHAR<br/>day: INTEGER<br/>day_name: VARCHAR"]
    reviewer["<b>gold.dim_reviewer</b><br/>PK reviewer_key: BIGINT<br/>UK reviewer: VARCHAR"]

    fact["<b>gold.fact_submission_snapshot</b><br/>PK submission_snapshot_key: BIGINT<br/>run_id: VARCHAR<br/>FK issue_key: BIGINT<br/>FK state_key: BIGINT<br/>FK status_key: BIGINT (nullable)<br/>FK milestone_key: BIGINT<br/>FK created_at_key: BIGINT<br/>FK updated_at_key: BIGINT<br/>FK extracted_at_key: BIGINT<br/>created_at: TIMESTAMPTZ<br/>updated_at: TIMESTAMPTZ<br/>extracted_at: TIMESTAMPTZ<br/>is_assigned: BOOLEAN<br/>days_since_update: BIGINT<br/>submission_age_days: BIGINT<br/>UNIQUE issue_key + extracted_at"]

    bridge["<b>gold.bridge_submission_reviewer</b><br/>PK/FK submission_snapshot_key: BIGINT<br/>PK/FK reviewer_key: BIGINT"]

    issue -->|"1 to many"| fact
    state -->|"1 to many"| fact
    status -.->|"0..1 status per snapshot"| fact
    milestone -->|"1 to many"| fact
    date -->|"1 to many via created / updated / extracted dates"| fact
    fact -->|"1 to many"| bridge
    reviewer -->|"1 to many"| bridge
```

---
### Analysis
I am interested in answering the following questions which will be translated to visualizations:

1. How are submissions distributed across milestones and statuses?
   - A stacked bar chart with milestones on the x-axis, submission count on the y-axis, and submission status as the stacks.
2. How many builders are on track or delayed?
   - KPI cards showing the count and percentage of unique builders in each group.
3. How does builder progress change over time?
   - A line chart with extraction date on the x-axis and average milestone completion rate on the y-axis.
   - A churn-risk metric can later represent builders with no milestone progress or submission activity for an agreed period.
4. Which builders need intervention?
   - A table showing each builder's current milestone, status, reviewer, issue state, submission age, and next action.
5. How much unresolved work does each reviewer have?
   - A horizontal bar chart showing the number of unresolved submissions assigned to each reviewer.
