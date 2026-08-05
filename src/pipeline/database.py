import duckdb
from pipeline.config import init_config

def get_database_connection()-> duckdb.DuckDBPyConnection:
    config = init_config()
    return duckdb.connect(config.duckdb_path, read_only=False)

def get_dev_database_connection()-> duckdb.DuckDBPyConnection:
    return duckdb.connect(read_only=False)