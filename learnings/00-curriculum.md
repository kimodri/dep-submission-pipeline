# DuckDB and MotherDuck for Data Engineering

## Purpose

This course develops a reusable way to design analytical data pipelines with
DuckDB locally and MotherDuck in the cloud.

The lessons follow a common data engineering scenario:

1. Extract nested data from an API.
2. Preserve the source data and its types in a Bronze layer.
3. Transform the data into clean Silver models.
4. Build dimensional models for analysis.
5. Run the same pipeline against local DuckDB and MotherDuck.

The goal is not to memorize isolated commands. The goal is to learn how to
reason about storage, types, table grain, connection ownership, repeatable
loads, and deployment choices in future projects.

## Guiding questions

By the end of the course, it should feel natural to answer questions such as:

- Where does the data live at each stage of the pipeline?
- What is temporary, and what is persisted?
- Which component should open and close a database connection?
- Should a DataFrame be queried directly or stored in a table?
- When should a table be created explicitly rather than inferred from data?
- How are lists, timestamps, nulls, and nested objects preserved?
- What should happen when the same pipeline run is retried?
- What is the grain and uniqueness rule of every analytical table?
- Which transformations belong in Python, Pandas, or SQL?
- When is local DuckDB sufficient, and when is MotherDuck useful?

## Target architecture

The course works toward the following general architecture:

```text
API
 |
 v
Python objects / JSON
 |
 +--> immutable raw extraction record
 |
 v
Bronze typed source records
 - source identifiers
 - nested lists or structures
 - source timestamps
 - extraction metadata
 |
 v
Silver transformations
 - standardized types
 - dimensions
 - bridge tables
 - snapshot facts
 |
 v
Gold analytical models
```

The storage target can be selected through configuration:

```text
Development  -> local DuckDB file
Testing      -> in-memory or temporary DuckDB database
Shared use   -> MotherDuck database
```

## Learning method

Each lesson will contain four parts:

1. **Mental model** — the concepts and vocabulary needed to reason about the
   topic.
2. **Small experiment** — an isolated example that makes the behavior visible.
3. **Pipeline application** — applying the concept to a generic API ingestion
   pipeline.
4. **Reflection** — questions that test whether the design can be explained,
   not merely copied.

Future lesson files should be numbered so they can be read in order:

```text
learnings/
  00-curriculum.md
  01-database-mental-model.md
  02-connections-and-configuration.md
  03-data-types-and-boundaries.md
  ...
```

## Lesson 1: The DuckDB database mental model

### Topics

- What an analytical database is.
- How DuckDB differs from Pandas, SQLite, and a database server.
- In-memory databases versus persistent database files.
- Connections, catalogs, databases, schemas, tables, views, and relations.
- Lazy relations versus materialized results.
- What survives after a Python process exits.

### Exercise

- Open an in-memory DuckDB connection.
- Open a file-backed DuckDB connection.
- Create and query a table in each.
- Close and reconnect to both targets.
- Explain why only one table persists.

### Completion criteria

Be able to point to any object in a pipeline and explain whether it is an
in-memory Python value, a temporary database relation, or persistent data.

## Lesson 2: Connection ownership and configuration

### Topics

- The difference between configuration and runtime resources.
- Import side effects caused by module-level connections.
- Why relative database paths can depend on the working directory.
- Explicit connection ownership.
- Context managers and deterministic cleanup.
- Dependency injection for database connections.
- Using different database targets for development and testing.

### Design principle

Configuration should describe how to connect. It should not connect merely
because a configuration module was imported.

A typical ownership pattern is:

```python
with connect(settings.database_url) as connection:
    run_pipeline(connection)
```

The entry point owns the connection. Lower-level functions receive the
connection they need and do not silently create unrelated connections.

### Exercise

- Represent the database target as a setting.
- Open the connection at the application boundary.
- Pass it to schema and loading functions.
- Verify that a test can substitute an in-memory connection.

### Completion criteria

Be able to explain who opens the connection, who closes it, and why.

## Lesson 3: Data types across system boundaries

### Topics

- Type systems in JSON, Python, Pandas, CSV, Parquet, and DuckDB.
- Why a Pandas `object` column does not describe one precise logical type.
- DuckDB scalar and nested types.
- `LIST`, `STRUCT`, and `MAP` values.
- `NULL` versus an empty list.
- `TIMESTAMP` versus `TIMESTAMPTZ`.
- Type inference and its limits.
- Lossy and type-preserving serialization formats.

### Comparison

```text
JSON -> Python -> Pandas -> CSV -> Pandas -> database
                         ^
                         possible type loss
```

```text
JSON -> Python -> Pandas -> DuckDB
                         ^
                         typed ingestion
```

CSV is useful for human-readable interchange, but it has no native list,
struct, or timestamp-with-time-zone type. A value that looks like a list may be
read back as ordinary text.

### Exercise

- Create a small DataFrame containing strings, timezone-aware timestamps,
  lists, empty lists, and nulls.
- Store it in DuckDB without using CSV.
- Inspect the table schema.
- Retrieve the data and verify the behavior of list operations.
- Repeat the experiment through CSV and document the differences.

### Completion criteria

Be able to predict where type information can be lost before choosing a storage
or interchange format.

## Lesson 4: Designing the Bronze layer

### Topics

- The purpose of Bronze storage.
- Raw source fidelity versus convenient typed records.
- Append-only ingestion.
- Source metadata and extraction metadata.
- Run identifiers and extraction timestamps.
- Schema evolution.
- Auditability and replay.
- Choosing between raw JSON and typed Bronze tables.

### Candidate design

A robust small pipeline may keep both:

- A raw extraction table containing the original response and extraction
  metadata.
- A typed Bronze table containing minimally processed source records.

The raw copy makes replay and debugging possible. The typed table makes normal
downstream transformation easier.

### Exercise

- Write a grain statement for each Bronze table.
- Define its columns and DuckDB types.
- Identify which values came from the source and which were generated by the
  pipeline.
- Decide how a changed source schema should be detected.

### Completion criteria

Be able to define Bronze by its guarantees rather than by a folder name or file
format.

## Lesson 5: Creating tables and loading DataFrames

### Topics

- Querying a DataFrame directly.
- Registering a temporary relation or view.
- `CREATE TABLE AS SELECT` for exploration.
- Explicit `CREATE TABLE` statements as data contracts.
- `INSERT INTO ... BY NAME`.
- Appending through the Python API.
- Column order, missing columns, and incompatible types.
- Separating schema creation from data loading.

### Decision guide

Use inferred tables when exploring unfamiliar data quickly. Use explicit table
definitions when the pipeline depends on a stable schema, constraints, and
repeatable behavior.

### Exercise

- Create a schema for Bronze data.
- Define a typed table explicitly.
- Load a DataFrame into it without an intermediate CSV.
- Insert columns by name rather than relying on their physical order.
- Query the stored data and verify its types and row count.

### Completion criteria

Be able to explain the difference between making a DataFrame queryable and
persisting its contents in a database table.

## Lesson 6: Transactions, retries, and idempotency

### Topics

- Atomic database transactions.
- Commit and rollback behavior.
- Pipeline run boundaries.
- Duplicate delivery from APIs or orchestrators.
- Append, replace, merge, and upsert strategies.
- Natural uniqueness rules.
- Idempotent loads.
- Recovery from partial failure.

### Core question

For every load, ask:

> What should happen if this exact operation runs again?

### Exercise

- Load one extraction twice.
- Define whether the second load should be accepted, ignored, or rejected.
- Force a failure after one write in a multi-table operation.
- Verify that the transaction prevents a partial load.

### Completion criteria

Be able to state the retry behavior of the pipeline before writing its loader.

## Lesson 7: Transforming nested data with DuckDB SQL

### Topics

- SQL transformations over persistent tables and DataFrames.
- `UNNEST` and list functions.
- Working with structs and JSON.
- Timestamp conversion and date arithmetic.
- Views versus materialized tables.
- Choosing between Pandas and DuckDB SQL.
- Keeping transformations testable.

### Exercise

- Expand a list-valued column into multiple rows in SQL.
- Implement the same operation with Pandas.
- Compare schemas, null behavior, and results.
- Choose which implementation communicates the transformation more clearly.

### Completion criteria

Be able to choose Python, Pandas, or SQL based on the operation rather than
habit.

## Lesson 8: Grain-first dimensional modeling

### Topics

- Business processes and fact-table grain.
- Periodic snapshot facts.
- Natural and surrogate keys.
- Stable dimension keys across pipeline runs.
- Dimensions, facts, and bridge tables.
- Many-to-many relationships.
- Degenerate dimensions.
- Slowly changing attributes.
- Date dimensions and role-playing dates.

### Important modeling pattern

Suppose a snapshot fact must contain one row per source record per extraction,
while one source record can have several reviewers. Expanding reviewers inside
the fact would change its grain. A bridge table can preserve both facts:

```text
fact_record_snapshot
  one row per record per extraction

bridge_snapshot_reviewer
  one row per record, extraction, and reviewer
```

### Exercise

- Write one grain sentence for every proposed table.
- Write the corresponding uniqueness rule.
- Model a many-to-many relationship with a bridge.
- Confirm that joins do not accidentally multiply measures.

### Completion criteria

Be able to derive table structure from grain instead of grouping columns by
appearance or data type.

## Lesson 9: Testing analytical pipelines

### Topics

- Unit tests for pure transformations.
- Integration tests with in-memory DuckDB.
- Tests with temporary file-backed databases.
- Schema assertions.
- Row-count and uniqueness checks.
- Nullability and referential-integrity checks.
- Testing retries and rollback.
- Small representative fixtures for nested data.

### Exercise

- Test schema creation against an empty database.
- Test a Bronze load with nested lists and nulls.
- Test duplicate behavior.
- Test fact and dimension uniqueness rules.
- Test that every foreign key resolves to a dimension row.

### Completion criteria

Be able to prove the pipeline's contracts without requiring a shared cloud
database or live API call.

## Lesson 10: From local DuckDB to MotherDuck

### Topics

- What remains the same between DuckDB and MotherDuck.
- Connecting through the DuckDB client with an `md:` target.
- Authentication through environment-managed credentials.
- Local, remote, and hybrid query execution.
- Database, schema, and table qualification.
- Cloud persistence and sharing.
- Development and deployment environments.
- Operational and cost considerations.

### Design principle

The storage destination should be selected at the application boundary. Core
transformation logic should not need to know whether its connection points to a
local DuckDB file or a MotherDuck database.

### Exercise

- Run schema creation and loading against a local DuckDB file.
- Change only the configured database target.
- Run the same operations against a private MotherDuck database.
- Compare schemas, row counts, and query results.

### Completion criteria

Be able to treat MotherDuck as a deployment choice within a DuckDB-based design,
while recognizing where remote execution, authentication, and cost matter.

## Lesson 11: Production pipeline composition

### Topics

- Clear extract, validate, load, and transform boundaries.
- Dependency injection.
- Application entry points.
- Schema migrations.
- Structured logging.
- Data quality checks.
- Metrics for rows received, accepted, rejected, and written.
- Safe handling of secrets.
- Failure reporting and observability.

### Target composition

```python
raw_data = extract()
bronze_data = transform_to_bronze(raw_data)
validate_bronze(bronze_data)

with connect(settings.database_url) as connection:
    ensure_schema(connection)
    load_bronze(connection, bronze_data)
    build_silver(connection)
    validate_models(connection)
```

The exact function names may change. The important idea is that each boundary
has a clear responsibility and can be tested independently.

### Final exercise

Build one command that:

1. Extracts source data.
2. Preserves raw extraction metadata.
3. Loads typed Bronze records without CSV.
4. Builds Silver dimensional models.
5. Validates the declared grain and constraints.
6. Commits the complete run or rolls it back.
7. Closes the connection reliably.
8. Supports both local DuckDB and MotherDuck through configuration.

### Completion criteria

Be able to start a new analytical pipeline and justify its storage boundaries,
connection lifecycle, type choices, loading strategy, model grain, testing
approach, and deployment target.

## Topics intentionally deferred until their lesson

During implementation, it is common to notice several problems at once. The
course deliberately handles them in dependency order:

- Timestamp correctness belongs with data types and Bronze contracts.
- Duplicate handling belongs with transactions and idempotency.
- List expansion belongs with nested SQL transformations.
- Fact-row multiplication belongs with grain-first dimensional modeling.
- Stable surrogate keys belong with repeated dimensional loads.
- Pagination and API resilience belong with production pipeline composition.
- Cloud credentials and remote execution belong with MotherDuck deployment.

Deferring a topic does not mean ignoring it. It means learning the prerequisite
mental model before implementing the solution.

## Public-reference safety

The files in this directory are intended to be safe to commit and read as
general learning material. Examples should remain generic and must not contain:

- Access tokens, passwords, connection secrets, or copied environment values.
- Private API responses or production data.
- Organization, customer, or user identifiers.
- Confidential business rules or internal operational details.
- Machine-specific absolute paths.

When a lesson needs sample data, it should use a small synthetic fixture with
neutral names and invented values.

## Reference documentation

- [DuckDB Python API overview](https://duckdb.org/docs/stable/clients/python/overview)
- [DuckDB data types](https://duckdb.org/docs/stable/sql/data_types/overview)
- [DuckDB importing from Pandas](https://duckdb.org/docs/stable/guides/python/import_pandas)
- [MotherDuck documentation](https://motherduck.com/docs/)

