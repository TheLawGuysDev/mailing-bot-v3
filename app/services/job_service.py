import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload, Session

from app.config import PDF_RETENTION_DAYS_NORMAL, PDF_RETENTION_DAYS_RESEND
from app.models.letter_job import LetterJob
from app.models.user import User
from app.services.pdf_service import AddressBlock, count_pdf_pages
from app.services.stannp_service import (
    send_letter_via_stannp,
    stannp_get_letter_status,
    cancel_letter_via_stannp,
    reconcile_job,
    extract_tracking_stamps,
    apply_tracking_stamps_to_job,
    bulk_sync_jobs_via_letters_get,
    TOO_LATE_STANNP,
    CANCELLABLE_STANNP,
)


def ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def delivered_expr():
    return or_(
        LetterJob.delivered_scan_at.isnot(None),
        func.lower(func.coalesce(LetterJob.status, "")) == "delivered",
        func.lower(func.coalesce(LetterJob.stannp_status, "")) == "delivered",
    )


def serialize_job(j: LetterJob) -> dict:
    effective_delivered = (
        getattr(j, "delivered_scan_at", None) is not None
        or (getattr(j, "status", "") or "").lower() == "delivered"
        or (getattr(j, "stannp_status", "") or "").lower() == "delivered"
    )

    return {
        "id": j.id,
        "user_id": j.user_id,
        "sender_email": j.user.email if getattr(j, "user", None) else None,
        "stannp_id": j.stannp_id,
        "stannp_status": getattr(j, "stannp_status", None),
        "stannp_status_display": (
            "delivered" if effective_delivered else getattr(j, "stannp_status", None)
        ),
        "display_status": (
            "delivered" if effective_delivered else (j.status or "sent")
        ),
        "recipient_name": j.recipient_name,
        "address1": j.address1,
        "address2": j.address2,
        "city": j.city,
        "state": j.state,
        "postcode": j.postcode,
        "country": j.country,
        "file_name": getattr(j, "file_name", None),
        "pdf_path": getattr(j, "pdf_path", None),
        "status": j.status,
        "error_message": j.error_message,
        "sent_at": j.sent_at,
        "last_status_check": j.last_status_check,
        "mailing_type": getattr(j, "mailing_type", None),
        "in_transit_scan_at": getattr(j, "in_transit_scan_at", None),
        "in_transit_location": getattr(j, "in_transit_location", None),
        "local_delivery_scan_at": getattr(j, "local_delivery_scan_at", None),
        "local_delivery_location": getattr(j, "local_delivery_location", None),
        "delivered_scan_at": getattr(j, "delivered_scan_at", None),
        "delivered_location": getattr(j, "delivered_location", None),
        "resend_count": getattr(j, "resend_count", 0),
        "last_resend_at": getattr(j, "last_resend_at", None),
    }


def apply_jobs_filters(
    query,
    *,
    sender: Optional[str] = None,
    search: Optional[str] = None,
    mailing_type: Optional[str] = None,
    status_filter: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
):
    if sender:
        sender_value = f"%{sender.strip().lower()}%"
        query = query.join(LetterJob.user).filter(
            func.lower(User.email).like(sender_value)
        )

    if search:
        search_value = f"%{search.strip().lower()}%"
        query = query.filter(
            or_(
                func.lower(LetterJob.recipient_name).like(search_value),
                func.lower(LetterJob.file_name).like(search_value),
            )
        )

    if mailing_type and mailing_type.strip().lower() != "all":
        query = query.filter(
            func.lower(func.coalesce(LetterJob.mailing_type, "")) == mailing_type.strip().lower()
        )

    if status_filter and status_filter.strip().lower() != "all":
        s = status_filter.strip().lower()

        if s == "delivered":
            query = query.filter(delivered_expr())

        elif s == "failed":
            query = query.filter(
                func.lower(func.coalesce(LetterJob.status, "")).in_(["failed", "returned"])
            )

        elif s == "returned":
            query = query.filter(
                func.lower(func.coalesce(LetterJob.status, "")) == "returned"
            )

        elif s == "cancelled":
            query = query.filter(
                func.lower(func.coalesce(LetterJob.status, "")) == "cancelled"
            )

        elif s == "needs_resend":
            query = query.filter(
                func.lower(func.coalesce(LetterJob.status, "")) == "needs_resend"
            )

        elif s == "resent":
            query = query.filter(
                func.lower(func.coalesce(LetterJob.status, "")) == "resent"
            )

        elif s == "sent":
            query = query.filter(
                ~delivered_expr(),
                ~func.lower(func.coalesce(LetterJob.status, "")).in_(
                    ["failed", "returned", "cancelled", "needs_resend", "resent", "delivered"]
                ),
                ~func.lower(func.coalesce(LetterJob.stannp_status, "")).in_(
                    ["delivered", "returned", "cancelled", "error"]
                )
            )

        else:
            query = query.filter(
                func.lower(func.coalesce(LetterJob.stannp_status, "")) == s
            )

    if from_date is not None:
        query = query.filter(LetterJob.sent_at >= from_date)

    if to_date is not None:
        query = query.filter(LetterJob.sent_at <= to_date)

    return query


def get_accessible_job(db: Session, job_id: int, current_user: User) -> LetterJob | None:
    query = db.query(LetterJob).filter(LetterJob.id == job_id)

    if current_user.role in ("admin", "manager"):
        return query.first()

    return query.filter(LetterJob.user_id == current_user.id).first()


def auto_resend_job(job: LetterJob) -> dict:
    if not job.pdf_path:
        raise HTTPException(
            status_code=400,
            detail="No stored PDF is available for this job (pdf_path is empty).",
        )

    if not os.path.exists(job.pdf_path):
        raise HTTPException(
            status_code=410,
            detail="Stored PDF file no longer exists on disk for this job.",
        )

    with open(job.pdf_path, "rb") as f:
        pdf_bytes = f.read()

    body_pages = count_pdf_pages(pdf_bytes)
    duplex = body_pages >= 6

    addr = AddressBlock(
        name=job.recipient_name,
        address1=job.address1,
        address2=job.address2,
        address3=None,
        city=job.city,
        state=job.state,
        postcode=job.postcode,
        country=job.country or "US",
    )

    stannp_res = send_letter_via_stannp(
        addr, pdf_bytes, mailing_type=job.mailing_type, duplex=duplex
    )

    new_stannp_id = stannp_res.get("data", {}).get("id") or stannp_res.get("id")

    job.stannp_id = new_stannp_id
    job.status = "resent"
    job.sent_at = datetime.now(timezone.utc)
    job.last_status_check = datetime.now(timezone.utc)
    job.resend_count = (job.resend_count or 0) + 1
    job.last_resend_at = datetime.now(timezone.utc)

    note = f"Auto-resend at {job.sent_at.isoformat()} with Stannp ID {new_stannp_id}"
    if job.error_message:
        job.error_message = f"{job.error_message}\n{note}"
    else:
        job.error_message = note

    return {"stannp_id": new_stannp_id}


def run_12_day_check_logic(db: Session, auto_resend: bool = False) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=13)

    terminal_statuses = [
        "delivered",
        "returned",
        "cancelled",
        "failed",
        "needs_resend",
        "resent",
    ]

    overdue_jobs = (
        db.query(LetterJob)
        .filter(LetterJob.sent_at <= cutoff)
        .filter(~LetterJob.status.in_(terminal_statuses))
        .all()
    )

    marked_needs_resend = 0
    auto_resend_success = 0
    auto_resend_failed = 0

    for job in overdue_jobs:
        try:
            detail = stannp_get_letter_status(str(job.stannp_id))
            remote_status = ((detail.get("data") or {}).get("status") or "").strip()
            reconcile_job(job, remote_status)

            stamps = extract_tracking_stamps(detail)
            apply_tracking_stamps_to_job(job, stamps)

        except Exception:
            job.last_status_check = datetime.now(timezone.utc)
            db.add(job)
            continue

        st = (job.stannp_status or "").lower()
        local_status = (job.status or "").lower()

        if (
            st in {"delivered", "returned", "cancelled", "error"}
            or local_status == "delivered"
            or getattr(job, "delivered_scan_at", None) is not None
        ):
            job.last_status_check = datetime.now(timezone.utc)
            db.add(job)
            continue

        is_stuck_state = st in {"in_transit", "local_delivery"}
        should_resend = is_stuck_state and (not getattr(job, "delivered_scan_at", None))

        if getattr(job, "resend_count", 0) >= 1:
            should_resend = False

        if auto_resend and should_resend:
            try:
                auto_resend_job(job)
                auto_resend_success += 1
            except HTTPException as e:
                job.status = "needs_resend"
                note = f"Auto-resend failed at {datetime.now(timezone.utc).isoformat()}: {e.detail}"
                job.error_message = f"{job.error_message}\n{note}" if job.error_message else note
                marked_needs_resend += 1
                auto_resend_failed += 1

        elif (not auto_resend) and should_resend:
            job.status = "needs_resend"
            marked_needs_resend += 1

        job.last_status_check = datetime.now(timezone.utc)
        db.add(job)

    db.commit()

    return {
        "status": "ok",
        "checked": len(overdue_jobs),
        "marked_needs_resend": marked_needs_resend,
        "auto_resend": auto_resend,
        "auto_resend_success": auto_resend_success,
        "auto_resend_failed": auto_resend_failed,
    }