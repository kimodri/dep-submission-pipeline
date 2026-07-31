import requests, os, json
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TOKEN")
OWNER_TYPE = "organization"
OWNER_NAME = os.getenv("OWNER_NAME")
PROJECT_NUMBER = int(os.getenv("PROJECT_NUMBER"))

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
""" % OWNER_TYPE

headers = {"Authorization": f"Bearer {TOKEN}"}
variables = {"owner": OWNER_NAME, "number": PROJECT_NUMBER}

# Execute the request
response = requests.post(
    "https://api.github.com/graphql",
    headers=headers,
    json={"query": query, "variables": variables},
    timeout=(10, 30)
)

response.raise_for_status()
data = response.json()

