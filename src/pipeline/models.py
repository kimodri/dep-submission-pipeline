from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from pathlib import Path


class AttemptStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"

@dataclass(frozen=True)
class RunMetadata:
    run_id: str
    attempt_number: int

@dataclass(frozen=True)
class SourceConfig:
    token: str
    owner_name: str
    owner_type: str
    project_number: int


@dataclass(frozen=True)
class LocalConfig:
    duckdb_path: Path
    sample_data_path: Path


@dataclass(frozen=True)
class MotherDuckConfig:
    database_path: str
    token: str

@dataclass(frozen=True)
class PipelineAttempt:
    run_id: str
    attempt_number: int
    started_at: datetime
    completed_at: datetime
    attempt_status: AttemptStatus
    error_stage: str | None = None
    error_type: str | None = None
    error_message: str | None = None

@dataclass(frozen=True)
class Extraction:
    run_id: str
    attempt_number: int
    extracted_at: datetime
    payload: dict[str, Any]
