import os
from pathlib import Path
from dataclasses import dataclass

from dotenv import load_dotenv

from pipeline.models import Config 

def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value

def init_config() -> Config:
    load_dotenv()

    token = _required_env("TOKEN")
    owner_name = _required_env("OWNER_NAME")
    owner_type = _required_env("OWNER_TYPE")
    project_number = int(_required_env("PROJECT_NUMBER"))

    project_root = Path(__file__).resolve().parents[2]
    database_path = project_root / "data" / "warehouse.duckdb"
    duckdb_path = os.getenv("DUCKDB_PATH", str(database_path))
    motherduckdb_path = _required_env("MOTHERDUCKDB_PATH")
    sample_data_path = os.getenv(
        "SAMPLE_DATA_PATH",
        str(project_root / "data" / "raw" / "v2-response.json"),  # This path maybe nonexistent
    )

    if not motherduckdb_path.startswith("md:"):
        raise ValueError("MOTHERDUCKDB_PATH must start with 'md:'")
    _required_env("MOTHERDUCK_TOKEN")
    
    max_error_mesage = 2000

    return Config(
        token=token,
        owner_name=owner_name,
        owner_type=owner_type,
        project_number=project_number,
        database_path=database_path,
        duckdb_path=duckdb_path,
        motherduckdb_path=motherduckdb_path,
        sample_data_path=sample_data_path,
        max_error_message=max_error_mesage
    )
