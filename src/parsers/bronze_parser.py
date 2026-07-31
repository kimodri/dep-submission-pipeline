import re
import pandas as pd
from etl import OWNER_TYPE
from datetime import datetime
from collections import defaultdict

def _add_status_to_df(status: str, df: pd.DataFrame):
    df['status'] = status.lower()
    return df

def _get_df(data, status):
    df = pd.DataFrame(data.get(status))
    df = _add_status_to_df(status, df)
    return df

def transform_raw_to_bronze(self, data: dict, extracted_at: datetime = None):

    if extracted_at is None:
        extracted_at = datetime.utcnow()

    columns = defaultdict(list)

    items = data.get("data", {}).get(OWNER_TYPE, {}).get("projectV2", {}).get("items", {}).get("nodes", [])

    for item in items:

        if not item.get("content") or "url" not in item["content"]:
            continue

        issue_url = item["content"]["url"]
        issue_id = item["content"]["id"] 
        issue_title = item["content"].get("title", "Untitled")

        author_data = item["content"].get("author")
        username = author_data.get("login") if author_data else "Unknown User"

        created_at = item["content"].get("createdAt", "Unknown")
        updated_at = item["content"].get("updatedAt", "Unknown")
        state = item["content"].get("state", "Unknown")

        assignees_data = item["content"].get("assignees", {}).get("nodes", [])
        assignees = [user.get("login") for user in assignees_data if user]

        labels_data = item["content"].get("labels", {}).get("nodes", [])
        labels_data = [label.get("name") for label in labels_data if label]

        labels = item["content"].get("labels", {}).get("nodes", [])
        
        milestone = None
        if labels:
            for label in labels:
                label = label.get("name")
                if label.startswith("M") and label[1:].isdigit():
                    milestone = label
    
        if milestone == None:
            re.search(r"\[(M\d+)\]", issue_title)        
    
        status = "No Status"
    
        for field in item.get("fieldValues", {}).get("nodes", []):
            if not field:
                continue
            if field.get("field", {}).get("name") == "Status":
                status = field["name"]
                break
    
        columns[status].append({
            "id": issue_id,
            "title": issue_title,
            "url": issue_url,
            "author": username,
            "created_at": created_at,
            "updated_at": updated_at,
            "state": state,
            "assignees": assignees,
            "labels": labels_data,
            "extracted_at": extracted_at,
            "milestone": milestone
        })
    
    ni_df = _get_df(columns, 'Needs Improvement')
    p_df = _get_df(columns, 'Passed')
    ir_df = _get_df(columns, 'In review')
    u_df = _get_df(columns, 'Unchecked/Unsigned')
    
    bronze_table = pd.concat([ni_df, p_df, ir_df, u_df], ignore_index=True)
    bronze_table.rename(
        columns={
            "id": "issue_id"
        }, inplace=True
    )
    
    bronze_table = bronze_table[bronze_table["title"].str.match(r"\[M\d+\]")]

    return bronze_table

