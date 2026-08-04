from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import pandas as pd

import requests

@dataclass
class Extraction:
  run_id: str
  extracted_at: datetime
  payload: dict[str, Any]


def extract_submissions(
  owner_name: str,
  owner_type: str,
  project_number: int,
  token: str,
  run_id: str
  ) -> Extraction:
    query = """
          query($owner: String!, $number: Int!) {
            viewer {
              id
            }
            %s(login: $owner) {
              projectV2(number: $number) {
                items(first: 100) {
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
                        assignees(first: 10) {
                          nodes {
                            login
                          }
                        }
                        labels(first: 10) {
                          nodes {
                            name
                          }
                        }
                      }
                    }
                    fieldValues(first: 10) {
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
                }
              }
            }
          }
          """ % owner_type
    headers = {"Authorization": f"Bearer {token}"}
    variables = {"owner": owner_name, "number": project_number}
    response = requests.post(
        "https://api.github.com/graphql",
        headers=headers,
        json={"query": query, "variables": variables},
        timeout=(10, 30)
    )

    response.raise_for_status()
    data = response.json()
    
    return Extraction(
        run_id=run_id,
        extracted_at=datetime.now(timezone.utc),
        payload=data
    )

def extract_bronze_submission(conn, run_id) -> pd.DataFrame:
  bronze_df = conn.execute(
    """
      SELECT *
      FROM bronze.raw_issue_extractions
      WHERE run_id = ?
    """,
    [run_id]
  ).df()
  
  return bronze_df
  
def _extract_all(conn):
  return (
    conn.execute(
      """
      SELECT *
      FROM bronze.raw_issue_extractions;
      """
    ).df()
  )