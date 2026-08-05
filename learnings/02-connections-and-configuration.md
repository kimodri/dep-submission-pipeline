# Lesson 2: Connection Ownership and Configuration

## Why this matters

A database connection is not just another configuration value. It is a live
runtime resource with a beginning, a useful lifetime, and an end.

If those boundaries are hidden, importing an unrelated constant can open a
database, different commands can silently use different database files, and no
part of the program clearly owns cleanup.

This lesson records how to separate four concerns:

```text
Database target
Connection creation
Connection ownership
Connection usage
```

## Starting point in the code

The initial structure was similar to:

```text
src/
└── pipeline/
    ├── config.py
    └── etl/
        ├── extract.py
        ├── bronze.py
        └── load.py
```

The configuration module contained both ordinary settings and a live
connection:

```python
# config.py

SOURCE_TYPE = "some_source_type"

connection = duckdb.connect(
    "../data/warehouse.duckdb",
    read_only=False,
)
```

A transformation module imported only one setting:

```python
# bronze.py

from pipeline.config import SOURCE_TYPE
```

The loading module already accepted a connection from its caller:

```python
# load.py

def create_schemas(conn):
    conn.execute("CREATE SCHEMA IF NOT EXISTS bronze")
    conn.execute("CREATE SCHEMA IF NOT EXISTS silver")
    conn.execute("CREATE SCHEMA IF NOT EXISTS gold")
```

That last decision was worth keeping. The loader did not need to choose its own
database.

## Realization 1: Importing a module executes its top-level code

### Initial belief

> Importing one name from a module only retrieves that name.

This made the following import appear harmless:

```python
from pipeline.config import SOURCE_TYPE
```

### Why it seemed reasonable

The syntax names only `SOURCE_TYPE`, so it is natural to imagine Python opening
the file, finding that variable, and returning it.

### What Python actually does

The first time a module is imported, Python executes its top-level statements.
Only after the module has been initialized does Python retrieve the requested
name.

The execution was therefore closer to:

```text
Import SOURCE_TYPE from config.py
    ↓
Execute config.py from top to bottom
    ├── import dependencies
    ├── load environment values
    ├── define SOURCE_TYPE
    └── open warehouse.duckdb
    ↓
Return SOURCE_TYPE to the importing module
```

The importing module did not request `connection`, but the database still
opened.

### Evidence

The connection was created by a top-level expression:

```python
connection = duckdb.connect(...)
```

That expression executes while the module is being initialized. Merely
importing an unrelated configuration value therefore performs database I/O.

### Revised mental model

> An imported module is executable code, not a passive dictionary of names.

Top-level statements should usually define inexpensive values, classes, and
functions. Runtime work such as opening databases or calling remote services
should begin through an explicit application operation.

This is not an absolute ban on top-level work. A small immutable constant is
normally harmless:

```python
SOURCE_TYPE = "some_source_type"
```

The concern is top-level work that creates resources, performs I/O, depends on
external state, or can fail for reasons unrelated to the requested import.

## Realization 2: A database target is not a live connection

### Initial belief

> The database connection is related to database configuration, so it belongs
> in `config.py`.

### Why it seemed reasonable

A configuration module is the natural place to centralize database-related
information. The missing distinction was between information about a resource
and the live resource itself.

These three values represent different ideas:

```python
"data/warehouse.duckdb"  # Which database to use

duckdb.connect(...)       # How to open it

conn                      # An open session being used now
```

### Revised mental model

Configuration should describe the database target:

```python
DATABASE_URL = "data/warehouse.duckdb"
```

A database infrastructure module can define how to connect:

```python
# database.py

import duckdb


def connect_database(database_url: str):
    return duckdb.connect(database_url)
```

Importing `connect_database` only defines a function. The database opens when
the function is called.

The application entry point should own the resulting live connection:

```python
# __main__.py

def main() -> None:
    with connect_database(DATABASE_URL) as conn:
        create_schemas(conn)
        load_bronze(conn, bronze_data)
```

The loader only borrows it:

```python
# load.py

def load_bronze(conn, bronze_data) -> None:
    conn.execute(...)
```

### Responsibility map

```text
config.py
└── Which database target should be used?

database.py
└── How is that target opened?

__main__.py
└── When is the live connection opened and closed?

load.py
└── What database operation should use the borrowed connection?
```

A tiny script or disposable notebook may reasonably use one convenient global
connection. Explicit ownership becomes more valuable when an application has
multiple stages, needs reliable cleanup, or may target different environments.

## Realization 3: Relative paths use the working directory

### Initial belief

> A relative path written in `config.py` is relative to `config.py`.

Consider:

```python
duckdb.connect("../data/warehouse.duckdb")
```

Because the string appears in `config.py`, it is easy to imagine that Python
uses that file's directory as the starting point.

### What actually happens

A plain relative path is normally resolved from the process's current working
directory. Importing a module does not change that directory.

Suppose the repository is:

```text
project/
├── data/
└── src/
    └── pipeline/
        └── config.py
```

The same relative string can resolve differently:

| Launch directory | Resolved target |
|---|---|
| `project/` | the `data/` directory beside `project/` |
| `project/src/` | `project/data/warehouse.duckdb` |

Both paths may be valid. DuckDB can therefore open or create two different
database files without reporting a path error.

### Evidence and consequence

One run may create tables in the intended database. A later run from another
working directory may open an empty database and report that those tables do
not exist.

The first conclusion might be:

> DuckDB did not persist the tables.

The more accurate diagnosis may be:

> The two runs opened different database files.

### Revised mental model

> A persistent database must have an intentional identity. Construct its path
> from a known anchor or provide its location explicitly.

For a repository-local development database, the source file can provide a
stable anchor:

```python
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "warehouse.duckdb"
```

The resulting path no longer depends on where the command was launched.

For an installed or deployed application, an explicit setting may be more
appropriate:

```python
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    str(DEFAULT_DATABASE_PATH),
)
```

The general name `DATABASE_URL` can represent several targets:

```text
/absolute/path/warehouse.duckdb
:memory:
md:analytics
```

The correct anchor depends on the application. The reusable rule is to choose
that anchor intentionally rather than relying accidentally on the launch
directory.

## Realization 4: The opener owns the connection lifetime

### Initial belief

> The application needs a database, so keeping a connection globally available
> is convenient.

Another plausible belief is:

> A function that uses the connection can close it when that function is done.

Both beliefs focus on a single operation. A multi-stage pipeline must instead
consider the complete period during which the resource is needed.

### Starting from the pipeline flow

A typical run performs work in this order:

```text
Call source API
    ↓
Transform the response
    ↓
Create database schemas
    ↓
Load Bronze data
    ↓
Build later models
```

The database is not needed while waiting for the API or performing a small
in-memory transformation. A useful initial boundary is therefore:

```python
raw_data = extract_data()
bronze_data = transform_to_bronze(raw_data)

with connect_database(DATABASE_URL) as conn:
    create_schemas(conn)
    load_bronze(conn, bronze_data)
    build_silver(conn)
```

### Why the loader should not close the connection

Suppose `load_bronze()` closes a connection that it received:

```python
def load_bronze(conn, bronze_data) -> None:
    conn.execute(...)
    conn.close()
```

The caller may still need it:

```python
load_bronze(conn, bronze_data)
build_silver(conn)  # conn has already been closed
```

`load_bronze()` knows when its own operation ends, but it does not know when the
complete database workflow ends.

### Revised mental model

> The component that opens a resource normally owns its cleanup. Functions that
> receive the resource borrow it and should not decide its lifetime.

In this pipeline:

```text
main()
├── opens conn
├── lends conn to create_schemas()
├── lends conn to load_bronze()
├── lends conn to build_silver()
└── closes conn
```

A context manager makes the boundary visible and closes the connection even if
an operation raises an exception:

```python
with connect_database(DATABASE_URL) as conn:
    run_database_work(conn)
```

Resource cleanup and transaction atomicity are related but distinct concerns.
A later lesson can decide which writes should commit or roll back together.

## A related observation: extraction at import time

The same import-side-effect reasoning applies outside the database layer.

An extraction module initially performed its request at the top level:

```python
# extract.py

response = requests.post(...)
response.raise_for_status()
data = response.json()
```

Importing that module therefore called the remote service.

The useful part of the original belief was correct: extraction behavior belongs
in `extract.py`. The execution timing was the problem.

Define the operation instead:

```python
def extract_data() -> dict:
    response = requests.post(...)
    response.raise_for_status()
    return response.json()
```

Then let the application entry point choose when to call it. A module owns the
definition of its operation; the pipeline coordinator owns the order in which
operations run.

## Resulting architecture

The revised design introduces an explicit coordination layer:

```text
src/
└── pipeline/
    ├── __main__.py
    ├── config.py
    ├── database.py
    └── etl/
        ├── extract.py
        ├── bronze.py
        └── load.py
```

### `config.py`

Describes application settings and the selected database target. It does not
open a live connection.

```python
def load_settings() -> Settings:
    ...
```

### `database.py`

Defines how to create a connection for a supplied target. Importing the module
does not open one.

```python
def connect_database(database_url: str):
    return duckdb.connect(database_url)
```

### `extract.py`

Defines how to request source data. Importing the module does not make the
request.

```python
def extract_data(...) -> dict:
    ...
```

### `bronze.py`

Transforms supplied source data and returns Bronze-shaped data.

```python
def transform_to_bronze(raw_data: dict):
    ...
```

### `load.py`

Performs database operations using a connection supplied by its caller.

```python
def create_schemas(conn) -> None:
    ...


def load_bronze(conn, bronze_data) -> None:
    ...
```

### `__main__.py`

Coordinates one complete pipeline run and owns runtime-resource lifetimes.

```python
def main() -> None:
    settings = load_settings()

    raw_data = extract_data(...)
    bronze_data = transform_to_bronze(raw_data)

    with connect_database(settings.database_url) as conn:
        create_schemas(conn)
        load_bronze(conn, bronze_data)
```

## Execution trace after the redesign

```text
Import application modules
    └── define settings, connection, extraction, transformation,
        and loading behavior

Call main()
    ↓
Load settings
    ↓
Call the source API
    ↓
Transform the response
    ↓
Open the selected database
    ↓
Create schemas and load data
    ↓
Close the connection
```

Importing the modules alone does not call the source API or open the database.
Runtime work begins through the entry point.

## Reusable decision rules

- Treat module imports as code execution, not passive name lookup.
- Keep the description of a resource separate from the live resource.
- Give every live resource an obvious owner and lifetime.
- Let the function that opens a resource close it.
- Let lower-level functions borrow resources instead of finding them through
  globals.
- Anchor persistent paths deliberately.
- Put orchestration in an entry point that can see the complete workflow.
- Preserve correct partial decisions; accepting `conn` in a loader was already
  the right direction even when connection creation was misplaced.

## Questions to ask in a future project

1. Does importing this module perform I/O or create a resource?
2. Is this value configuration, a factory, or a live runtime object?
3. Which function understands the resource's complete required lifetime?
4. If this function receives a resource, does it own it or only borrow it?
5. What directory anchors this relative path?
6. Could two launch locations silently open different persistent files?
7. Which module defines an operation, and which module decides when it runs?

## References

- [Python import system](https://docs.python.org/3/reference/import.html)
- [Python `pathlib`](https://docs.python.org/3/library/pathlib.html)
- [DuckDB Python API overview](https://duckdb.org/docs/stable/clients/python/overview)

