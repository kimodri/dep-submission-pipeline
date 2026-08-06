from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import time
from typing import Any

import requests

from pipeline.etl.errors import ExtractionError
from pipeline.models import Extraction

_ALLOWED_OWNER_TYPES = {"organization", "user"}
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_DEFAULT_RETRY_DELAYS = (5.0, 30.0, 120.0)
_MAX_RETRY_DELAY_SECONDS = 120.0


def _rate_limited(response: requests.Response) -> bool:
  return (
    response.status_code == 403
    and response.headers.get("X-RateLimit-Remaining") == "0"
  )

def _retry_delay(response: requests.Response | None, retry_index: int) -> float:
  if response is not None:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
      try:
        return min(max(float(retry_after), 0.0), _MAX_RETRY_DELAY_SECONDS)
      except ValueError:
        try:
          retry_at = parsedate_to_datetime(retry_after)
          seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()
          return min(max(seconds, 0.0), _MAX_RETRY_DELAY_SECONDS)
        except (TypeError, ValueError, OverflowError):
          pass

    reset_at = response.headers.get("X-RateLimit-Reset")
    if reset_at:
      try:
        seconds = float(reset_at) - time.time()
        return min(max(seconds, 0.0), _MAX_RETRY_DELAY_SECONDS)
      except ValueError:
        pass

  return _DEFAULT_RETRY_DELAYS[retry_index]

def _post_graphql(
  *,
  headers: dict[str, str],
  query: str,
  variables: dict[str, Any],
) -> requests.Response:
  """POST one read-only GraphQL page with three bounded transient retries."""
  for retry_index in range(len(_DEFAULT_RETRY_DELAYS) + 1):
    response: requests.Response | None = None
    try:
      response = requests.post(
        "https://api.github.com/graphql",
        headers=headers,
        json={"query": query, "variables": variables},
        timeout=(10, 30),
      )
    except (requests.ConnectionError, requests.Timeout):
      if retry_index == len(_DEFAULT_RETRY_DELAYS):
        raise
      time.sleep(_DEFAULT_RETRY_DELAYS[retry_index])
      continue

    is_retryable = (
      response.status_code in _RETRYABLE_STATUS_CODES
      or _rate_limited(response)
    )
    if is_retryable and retry_index < len(_DEFAULT_RETRY_DELAYS):
      time.sleep(_retry_delay(response, retry_index))
      continue

    response.raise_for_status()
    return response

  raise AssertionError("GraphQL retry loop ended unexpectedly")

def extract_submissions(
  owner_name: str,
  owner_type: str,
  project_number: int,
  token: str,
  run_id: str,
  attempt_number: int,
  ) -> Extraction:
    if owner_type not in _ALLOWED_OWNER_TYPES:
      allowed_types = ", ".join(sorted(_ALLOWED_OWNER_TYPES))
      raise ValueError(f"OWNER_TYPE must be one of: {allowed_types}")

    query = """
          query($owner: String!, $number: Int!, $cursor: String) {
            viewer {
              id
            }
            %s(login: $owner) {
              projectV2(number: $number) {
                items(first: 100, after: $cursor) {
                  nodes {
                    content {
                      ... on Issue {
                        id
                        title
                        url
                        author {
                          login
                        }
                        createdAt
                        updatedAt
                        state
                        assignees(first: 100) {
                          nodes {
                            login
                          }
                        }
                        labels(first: 100) {
                          nodes {
                            name
                          }
                        }
                      }
                    }
                    fieldValues(first: 100) {
                      nodes {
                        ... on ProjectV2ItemFieldSingleSelectValue {
                          name
                          field {
                            ... on ProjectV2FieldCommon {
                              name
                            }
                          }
                        }
                      }
                    }
                  }
                  pageInfo {
                    hasNextPage
                    endCursor
                  }
                }
              }
            }
          }
          """ % owner_type
    headers = {"Authorization": f"Bearer {token}"}
    pages: list[dict[str, Any]] = []
    cursor: str | None = None

    while True:
      variables = {
        "owner": owner_name,
        "number": project_number,
        "cursor": cursor,
      }
      response = _post_graphql(
          headers=headers,
          query=query,
          variables=variables,
      )

      try:
        page = response.json()
      except ValueError as exc:
        raise ExtractionError("GitHub returned a non-JSON response") from exc

      if not isinstance(page, dict):
        raise ExtractionError("GitHub returned an unexpected JSON response")

      errors = page.get("errors")
      if errors:
        messages = [
          error.get("message", str(error)) if isinstance(error, dict) else str(error)
          for error in errors
        ]
        raise ExtractionError(
          f"GitHub GraphQL returned errors: {'; '.join(messages)}"
        )

      try:
        project = page["data"][owner_type]["projectV2"]
        items = project["items"]
        page_info = items["pageInfo"]
      except (KeyError, TypeError) as exc:
        raise ExtractionError(
          "GitHub response did not contain the requested project items"
        ) from exc

      if not isinstance(items.get("nodes"), list):
        raise ExtractionError("GitHub project items were not returned as a list")

      pages.append(page)

      if not page_info.get("hasNextPage"):
        break

      next_cursor = page_info.get("endCursor")
      if not isinstance(next_cursor, str) or not next_cursor or next_cursor == cursor:
        raise ExtractionError("GitHub returned an invalid pagination cursor")
      cursor = next_cursor

    return Extraction(
        run_id=run_id,
        attempt_number=attempt_number,
        extracted_at=datetime.now(timezone.utc).isoformat(),
        payload={"pages": pages},
    )
