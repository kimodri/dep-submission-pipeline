import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TOKEN")
OWNER_TYPE = "organization"
OWNER_NAME = os.getenv("OWNER_NAME")
PROJECT_NUMBER = int(os.getenv("PROJECT_NUMBER"))

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = PROJECT_ROOT / "data" / "warehouse.duckdb"
DUCKDB_PATH = os.getenv("DUCKDB_PATH", DATABASE_PATH)