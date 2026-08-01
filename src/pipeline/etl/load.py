import duckdb

def _create_schemas(conn):
    conn.execute("CREATE SCHEMA IF NOT EXISTS bronze;")
    conn.execute("CREATE SCHEMA IF NOT EXISTS silver;")
    conn.execute("CREATE SCHEMA IF NOT EXISTS gold;")
    

def _create_table(conn):
    pass

def load_to_bronze(conn):
    pass