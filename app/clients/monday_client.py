import requests
from fastapi import HTTPException
from app.config import MONDAY_API_TOKEN, MONDAY_API_URL


def update_monday_item(item_id: int, values: dict) -> dict:
    """
    Placeholder monday updater.
    Later:
      - implement GraphQL mutation
      - map board column IDs
    """
    if not item_id:
        raise HTTPException(status_code=400, detail="Missing monday item ID")

    return {
        "updated": False,
        "item_id": item_id,
        "values": values,
        "note": "Monday update stub only; GraphQL mutation not wired yet.",
    }

def create_monday_update(item_id: int, body: str) -> dict:
    """
    Posts an update in the item.
    """
    if not item_id:
        raise HTTPException(status_code=400, detail="Missing monday item ID")

    # The GraphQL query to create a comment (update)
    query = """
    mutation ($itemId: ID!, $body: String!) {
      create_update (item_id: $itemId, body: $body) {
        id
      }
    }
    """
    variables = {
        "itemId": str(item_id),
        "body": body
    }

    headers = {
        "Authorization": MONDAY_API_TOKEN,
        "Content-Type": "application/json",
        "API-Version": "2023-10"
    }

    response = requests.post(
        MONDAY_API_URL, 
        json={"query": query, "variables": variables}, 
        headers=headers
    )

    if response.status_code != 200:
        return {"created": False, "error": response.text}

    return response.json()

def get_column_id_by_title(board_id: int, title: str) -> str:
    """Finds a column ID based on its display title."""
    query = """
    query ($boardId: [ID!]) {
      boards (ids: $boardId) {
        columns {
          id
          title
        }
      }
    }
    """
    vars = {"boardId": [str(board_id)]}
    headers = {"Authorization": MONDAY_API_TOKEN, "API-Version": "2023-10"}
    
    response = requests.post(MONDAY_API_URL, json={"query": query, "variables": vars}, headers=headers)
    columns = response.json().get("data", {}).get("boards", [{}])[0].get("columns", [])
    
    for col in columns:
        if col["title"].lower() == title.lower():
            return col["id"]
    return None

def get_file_from_column(item_id: int, column_id: str) -> dict:
    """
    Retrieves the file asset directly from the item's assets list.
    """
    # This query gets all assets for the item and filters by the specific column ID
    query = """
    query ($itemId: [ID!]) {
      items (ids: $itemId) {
        assets {
          id
          name
          public_url
          file_extension
        }
      }
    }
    """
    
    variables = {"itemId": [str(item_id)], "colId": [column_id]}
    headers = {
        "Authorization": MONDAY_API_TOKEN,
        "Content-Type": "application/json",
        "API-Version": "2024-01" # Updated to a more recent version
    }

    response = requests.post(MONDAY_API_URL, json={"query": query, "variables": variables}, headers=headers)
    data = response.json()
    
    if "errors" in data:
        print(f"DEBUG: GraphQL Errors: {data['errors']}")
        return None
    
    try:
        # Fetch all assets for the item
        assets = data["data"]["items"][0]["assets"]
        if not assets:
            print(f"DEBUG: No assets found for item {item_id}")
            return None

        # In many cases, you want the most recently uploaded asset
        # For simplicity, we grab the first one, but you could filter by name/extension
        target_asset = assets[0] 
        file_name = target_asset["name"]
        download_url = target_asset["public_url"]

        # Download the file bytes into local memory (cache)
        file_response = requests.get(download_url)
        return {
            "name": file_name,
            "bytes": file_response.content
        }

    except (KeyError, IndexError) as e:
        print(f"DEBUG: Error parsing assets: {str(e)}")
        return None