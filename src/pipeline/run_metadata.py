import os
from uuid import uuid4

from pipeline.models import RunMetadata


def resolve_run_metadata() -> RunMetadata:
    """Resolve stable workflow metadata, with a local-development fallback."""
    is_github_actions = os.getenv("GITHUB_ACTIONS", "").lower() == "true"

    if not is_github_actions:
        return RunMetadata(run_id=f"local-{uuid4()}", attempt_number=1)

    run_id = os.getenv("GITHUB_RUN_ID")
    attempt_value = os.getenv("GITHUB_RUN_ATTEMPT")

    if not run_id:
        raise ValueError("GITHUB_RUN_ID is required in GitHub Actions")
    if not attempt_value:
        raise ValueError("GITHUB_RUN_ATTEMPT is required in GitHub Actions")

    try:
        attempt_number = int(attempt_value)
    except ValueError as exc:
        raise ValueError("GITHUB_RUN_ATTEMPT must be an integer") from exc

    if attempt_number < 1:
        raise ValueError("GITHUB_RUN_ATTEMPT must be at least 1")

    return RunMetadata(run_id=run_id, attempt_number=attempt_number)
