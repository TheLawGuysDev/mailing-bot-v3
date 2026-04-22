import json

import requests
from fastapi import HTTPException
from app.config import MONDAY_API_TOKEN, MONDAY_API_URL


def _collect_asset_ids_from_file_value(raw_value: str) -> set[str]:
    parsed_value = json.loads(raw_value)
    asset_ids: set[str] = set()

    # Some accounts return arrays under "files", others under "assets".
    groups = []
    if isinstance(parsed_value, dict):
        groups.extend(
            [
                parsed_value.get("files"),
                parsed_value.get("assets"),
                parsed_value.get("asset_ids"),
                parsed_value.get("ids"),
            ]
        )
        groups.append([parsed_value])

    for group in groups:
        if not isinstance(group, list):
            continue
        for f in group:
            if isinstance(f, (str, int)):
                asset_ids.add(str(f))
                continue
            if not isinstance(f, dict):
                continue

            # Monday file payloads can vary by API version/account shape.
            candidate_ids = [
                f.get("assetId"),
                f.get("asset_id"),
                f.get("id"),
                (f.get("asset") or {}).get("id") if isinstance(f.get("asset"), dict) else None,
            ]
            for cid in candidate_ids:
                if cid is not None:
                    asset_ids.add(str(cid))

    return asset_ids


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
    """
    Finds a column ID based on its display title.
    """
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
    Retrieves a file asset from a specific file column.
    """
    
    query = """
    query ($itemId: [ID!], $colId: [String!]) {
      items (ids: $itemId) {
        assets {
          id
          name
          public_url
          file_extension
        }
        column_values(ids: $colId) {
          id
          value
        }
      }
    }
    """
    
    variables = {"itemId": [str(item_id)], "colId": [column_id]}
    headers = {
        "Authorization": MONDAY_API_TOKEN,
        "Content-Type": "application/json",
        "API-Version": "2024-01" 
    }

    response = requests.post(MONDAY_API_URL, json={"query": query, "variables": variables}, headers=headers)
    data = response.json()
    
    if "errors" in data:
        return None
    
    try:
        item = data["data"]["items"][0]
        assets = item.get("assets", [])
        column_values = item.get("column_values", [])
        if not assets:
            return None

        if not column_values:
            return None

        raw_value = column_values[0].get("value")
        if not raw_value:
            return None

        target_asset_ids = _collect_asset_ids_from_file_value(raw_value)
        if not target_asset_ids:
            return None

        target_asset = next(
            (asset for asset in assets if str(asset.get("id")) in target_asset_ids),
            None,
        )
        if not target_asset:
            return None

        file_name = target_asset["name"]
        download_url = target_asset["public_url"]

        file_response = requests.get(download_url)
        return {
            "name": file_name,
            "file_extension": target_asset.get("file_extension"),
            "bytes": file_response.content
        }

    except (KeyError, IndexError, json.JSONDecodeError) as e:
        return None


def clear_file_column(board_id: int, item_id: int, column_id: str) -> dict:
    """
    Clears all files from a specific Monday file column.
    """
    query = """
    mutation ($boardId: ID!, $itemId: ID!, $columnId: String!, $value: JSON!) {
      change_column_value(
        board_id: $boardId,
        item_id: $itemId,
        column_id: $columnId,
        value: $value
      ) {
        id
      }
    }
    """

    variables = {
        "boardId": str(board_id),
        "itemId": str(item_id),
        "columnId": column_id,
        "value": "{\"clear_all\": true}",
    }
    headers = {
        "Authorization": MONDAY_API_TOKEN,
        "Content-Type": "application/json",
        "API-Version": "2024-01",
    }

    response = requests.post(
        MONDAY_API_URL,
        json={"query": query, "variables": variables},
        headers=headers,
    )
    response.raise_for_status()
    data = response.json()
    if "errors" in data:
        raise RuntimeError(str(data["errors"]))
    return data