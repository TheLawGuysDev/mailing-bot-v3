from fastapi import HTTPException

from app.clients.monday_client import update_monday_item, create_monday_update


def verify_monday_request(authorization_header: str | None):
    """
    Safe-first verification stub.

    Current behavior:
      - requires Authorization header
      - requires Bearer token format

    Later:
      - decode/verify monday JWT or webhook signature
      - validate issuer/audience/expiry as needed
    """
    if not authorization_header:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    if not authorization_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

    token = authorization_header.replace("Bearer ", "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty bearer token")

    return {"verified": True, "token_present": True}


def update_monday_send_result(
    item_id: int,
    *,
    bot_status: str,
    job_ids: list[int] | None = None,
    stannp_ids: list[str] | None = None,
    message: str | None = None,
) -> dict:
    values = {
        "bot_status": bot_status,
        "job_ids": job_ids or [],
        "stannp_ids": stannp_ids or [],
        "message": message or "",
    }

    return update_monday_item(item_id=item_id, values=values)


def post_monday_comment(item_id: int, message: str) -> dict:
    return create_monday_update(item_id=item_id, body=message)