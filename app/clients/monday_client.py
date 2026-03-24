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


# def create_monday_update(item_id: int, body: str) -> dict:
#     """
#     Placeholder for posting an update/comment to a monday item.
#     """
#     if not item_id:
#         raise HTTPException(status_code=400, detail="Missing monday item ID")

#     return {
#         "created": False,
#         "item_id": item_id,
#         "body": body,
#         "note": "Monday update/comment stub only; GraphQL mutation not wired yet.",
#     }

def create_monday_update(item_id: int, body: str) -> dict:
    """
    Posts an update (comment) to a specific monday item.
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