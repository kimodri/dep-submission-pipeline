import duckdb
from src.pipeline.config import DATABASE_URL

def get_database_connection(database_path: str)-> duckdb.DuckDBPyConnection:
    return duckdb.connect(database_path, read_only=False)