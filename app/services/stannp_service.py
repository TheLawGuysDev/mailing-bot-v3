from datetime import datetime, timedelta, timezone
import requests
from fastapi import HTTPException

from app.config import (
    STANNP_API_KEY,
    STANNP_API_V1,
    STANNP_REPORTING_BASE_URL,
    STANNP_TEST_MODE,
)
from app.models.letter_job import LetterJob
from app.services.pdf_service import AddressBlock


LOCAL_LOCKED_STATUSES = {"needs_resend", "resent", "cancelled", "failed"}
STANNP_TERMINAL = {"delivered", "returned", "cancelled", "error"}

TOO_LATE_STANNP = {
    "handed_over",
    "in_transit",
    "local_delivery",
    "delivered",
    "returned",
    "cancelled",
    "error",
}

CANCELLABLE_STANNP = {"received", "producing"}


def ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def send_letter_via_stannp(
    address: AddressBlock,
    pdf_bytes: bytes,
    mailing_type: str | None = None,
    duplex: bool = False,
) -> dict:
    url = f"{STANNP_API_V1}/letters/create"

    headers = {
        "Accept": "application/json",
    }

    data = {
        "test": "true" if STANNP_TEST_MODE else "false",
        "size": "US-LETTER-XL-WINDOW",
        "duplex": "true" if duplex else "false",
        "addons": "first_class",
        "tags": mailing_type or "",
        "recipient[name]": address.name or "CURRENT OCCUPANT",
        "recipient[title]": address.title or "",
        "recipient[firstname]": address.first_name or "",
        "recipient[lastname]": address.last_name or "",
        "recipient[company]": address.company or "",
        "recipient[address_notes]": address.address_notes or "",
        "recipient[address1]": address.address1,
        "recipient[address2]": address.address2 or "",
        "recipient[address3]": address.address3 or "",
        "recipient[city]": address.city,
        "recipient[state]": address.state,
        "recipient[zipcode]": address.postcode,
        "recipient[country]": address.country,
    }

    files = {
        "file": ("letter.pdf", pdf_bytes, "application/pdf"),
    }

    resp = requests.post(
        url,
        headers=headers,
        data=data,
        files=files,
        auth=(STANNP_API_KEY, ""),
        timeout=60,
    )

    if resp.status_code >= 500:
        raise HTTPException(
            status_code=502,
            detail=f"Stannp server error ({resp.status_code})",
        )

    try:
        data = resp.json()
    except Exception:
        raise HTTPException(
            status_code=502,
            detail=f"Stannp non-JSON response: {resp.text[:200]}",
        )

    if not data.get("success", False):
        raise HTTPException(status_code=502, detail=f"Stannp error: {data}")

    return data


def stannp_get_letter_status(stannp_id: str) -> dict:
    if not stannp_id:
        raise HTTPException(status_code=400, detail="Missing Stannp letter ID")

    url = f"{STANNP_API_V1}/letters/get/{stannp_id}"
    resp = requests.get(
        url,
        auth=(STANNP_API_KEY, ""),
        headers={"Accept": "application/json"},
        timeout=30,
    )

    try:
        data = resp.json()
    except Exception:
        raise HTTPException(
            status_code=502,
            detail=f"Stannp status non-JSON response: {resp.text[:200]}",
        )

    if not data.get("success"):
        raise HTTPException(
            status_code=502,
            detail=f"Stannp status error: {data}",
        )

    return data


def cancel_letter_via_stannp(stannp_id: str | int) -> dict:
    url = f"{STANNP_API_V1}/letters/cancel"

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    payload = {"id": str(stannp_id)}

    resp = requests.post(
        url,
        headers=headers,
        json=payload,
        auth=(STANNP_API_KEY, ""),
        timeout=30,
    )

    try:
        data = resp.json()
    except Exception:
        raise HTTPException(
            status_code=502,
            detail=f"Stannp non-JSON response on cancel: {resp.text[:200]}",
        )

    if not data.get("success", False):
        raise HTTPException(
            status_code=400,
            detail=f"Stannp cancel failed: {data.get('error') or data}",
        )

    return data


def reconcile_job(job: LetterJob, remote_status: str | None) -> bool:
    changed = False
    rs_lower = (remote_status or "").strip().lower()

    if rs_lower and (job.stannp_status or "").lower() != rs_lower:
        job.stannp_status = rs_lower
        changed = True

    if getattr(job, "delivered_scan_at", None) is not None:
        if (job.status or "").lower() != "delivered":
            job.status = "delivered"
            changed = True
        return changed

    local = (job.status or "").lower()
    if local in LOCAL_LOCKED_STATUSES:
        return changed

    if rs_lower == "delivered":
        if (job.status or "").lower() != "delivered":
            job.status = "delivered"
            changed = True
        return changed

    if rs_lower and (job.status or "").lower() != rs_lower:
        job.status = rs_lower
        changed = True

    return changed


def _parse_stannp_dt(dt_str: str | None) -> datetime | None:
    if not dt_str:
        return None

    s = str(dt_str).strip()
    if not s:
        return None

    fmts = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
    ]
    for f in fmts:
        try:
            dt = datetime.strptime(s, f)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        except Exception:
            continue

    return None


def extract_tracking_stamps(stannp_detail_json: dict) -> dict:
    result = {
        "in_transit": {"at": None, "location": None},
        "local_delivery": {"at": None, "location": None},
        "delivered": {"at": None, "location": None},
    }

    data = (stannp_detail_json or {}).get("data") or {}
    events = data.get("tracking") or data.get("events") or []

    if not isinstance(events, list):
        events = []

    for ev in events:
        if not isinstance(ev, dict):
            continue

        status = (ev.get("status") or ev.get("event") or ev.get("name") or "").strip().lower()
        loc = (ev.get("location") or ev.get("scan_location") or ev.get("place") or "").strip() or None

        at = _parse_stannp_dt(
            ev.get("date") or ev.get("scan_date") or ev.get("datetime")
        )

        if "in transit" in status or status == "in_transit":
            if at and (result["in_transit"]["at"] is None or at > result["in_transit"]["at"]):
                result["in_transit"] = {"at": at, "location": loc}
        elif "local delivery" in status or status == "local_delivery":
            if at and (result["local_delivery"]["at"] is None or at > result["local_delivery"]["at"]):
                result["local_delivery"] = {"at": at, "location": loc}
        elif "delivered" in status or status == "delivered":
            if at and (result["delivered"]["at"] is None or at > result["delivered"]["at"]):
                result["delivered"] = {"at": at, "location": loc}

    if result["delivered"]["at"] is None:
        result["delivered"]["at"] = _parse_stannp_dt(data.get("delivered_at"))
    if result["delivered"]["location"] is None:
        result["delivered"]["location"] = (data.get("delivered_location") or "").strip() or None

    return result


def apply_tracking_stamps_to_job(job: LetterJob, stamps: dict) -> bool:
    changed = False

    def _set(attr: str, value):
        nonlocal changed
        if hasattr(job, attr):
            if getattr(job, attr) != value:
                setattr(job, attr, value)
                changed = True

    in_transit = stamps.get("in_transit") or {}
    local_delivery = stamps.get("local_delivery") or {}
    delivered = stamps.get("delivered") or {}

    _set("in_transit_scan_at", in_transit.get("at"))
    _set("in_transit_location", in_transit.get("location"))

    _set("local_delivery_scan_at", local_delivery.get("at"))
    _set("local_delivery_location", local_delivery.get("location"))

    _set("delivered_scan_at", delivered.get("at"))
    _set("delivered_location", delivered.get("location"))

    return changed


def sync_job_from_letters_get(job: LetterJob) -> bool:
    if not job.stannp_id:
        return False

    detail = stannp_get_letter_status(str(job.stannp_id))
    remote_status = ((detail.get("data") or {}).get("status") or "").strip()

    changed = reconcile_job(job, remote_status)

    stamps = extract_tracking_stamps(detail)
    if apply_tracking_stamps_to_job(job, stamps):
        changed = True

    if reconcile_job(job, remote_status):
        changed = True

    job.last_status_check = datetime.now(timezone.utc)
    return changed


def bulk_sync_jobs_via_letters_get(jobs: list[LetterJob]) -> bool:
    changed_any = False

    for job in jobs:
        try:
            if sync_job_from_letters_get(job):
                changed_any = True
        except Exception:
            continue

    return changed_any


def map_stannp_status(remote_status: str | None) -> str:
    s = (remote_status or "").lower()

    if s in {"delivered"}:
        return "delivered"
    if s in {"returned", "error"}:
        return "failed"
    if s in {"cancelled"}:
        return "cancelled"
    if s in {"queueing", "printing", "production", "mailed", "test"}:
        return "sent"

    return "sent"