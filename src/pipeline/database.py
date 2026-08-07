import duckdb
from pipeline.models import LocalConfig, MotherDuckConfig


def get_database_connection(
    config: MotherDuckConfig,
) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(config.database_path, read_only=False)


def get_dev_database_connection(
    config: LocalConfig,
) -> duckdb.DuckDBPyConnection:
    config.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(config.duckdb_path), read_only=False)
