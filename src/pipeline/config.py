import os
from pathlib import Path

from dotenv import load_dotenv

from pipeline.models import LocalConfig, MotherDuckConfig, SourceConfig

def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value

def init_source_config() -> SourceConfig:
    load_dotenv()

    return SourceConfig(
        token=_required_env("TOKEN"),
        owner_name=_required_env("OWNER_NAME"),
        owner_type=_required_env("OWNER_TYPE"),
        project_number=int(_required_env("PROJECT_NUMBER")),
    )


def init_local_config() -> LocalConfig:
    load_dotenv()

    project_root = Path(__file__).resolve().parents[2]
    database_path = project_root / "data" / "warehouse.duckdb"
    return LocalConfig(
        duckdb_path=Path(os.getenv("DUCKDB_PATH", str(database_path))),
        sample_data_path=Path(
            os.getenv(
                "SAMPLE_DATA_PATH",
                str(project_root / "data" / "rawpayload.json"),
            )
        ),
    )


def init_motherduck_config() -> MotherDuckConfig:
    load_dotenv()

    motherduckdb_path = _required_env("MOTHERDUCKDB_PATH")
    if not motherduckdb_path.startswith("md:"):
        raise ValueError("MOTHERDUCKDB_PATH must start with 'md:'")

    return MotherDuckConfig(
        database_path=motherduckdb_path,
        token=_required_env("MOTHERDUCK_TOKEN"),
    )
