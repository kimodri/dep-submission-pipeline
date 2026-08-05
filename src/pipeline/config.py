import os
from pathlib import Path
from dotenv import load_dotenv
from dataclasses import dataclass

@dataclass(frozen=True)
class Config:
    token: str
    owner_name: str
    owner_type: str
    project_number: int
    database_path: Path
    duckdb_path: str
    sample_data_path: str
    

def init_config()-> Config:
    load_dotenv()
    token = os.getenv("TOKEN")
    owner_name = os.getenv("OWNER_NAME")
    owner_type = os.getenv("OWNER_TYPE")
    project_number = int(os.getenv("PROJECT_NUMBER"))
    
    project_root = Path(__file__).resolve().parents[2]
    database_path = project_root / "data" / "warehouse.duckdb"
    duckdb_path = os.getenv("DUCKDB_PATH", str(database_path)),
    sample_data_path = os.getenv("SAMPLE_DATA_PATH", str(project_root / "data" / "raw" / "v2-response.json"))
    
    return Config(
        token=token,
        owner_name=owner_name,
        owner_type=owner_type,
        project_number=project_number,
        database_path=database_path,
        duckdb_path=duckdb_path,
        sample_data_path=sample_data_path
    )
