from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session, joinedload

from app.dependencies import get_db
from app.models.letter_job import LetterJob
from app.schemas.jobs import JobsListResponse, JobsSummaryResponse
from app.services.auth_service import get_current_active_user, require_manager_or_admin
from app.services.job_service import (
    serialize_job,
    apply_jobs_filters,
    delivered_expr,
    get_accessible_job,
    auto_resend_job,
    run_12_day_check_logic,
)
from app.services.stannp_service import (
    sync_job_from_letters_get,
    map_stannp_status,
    stannp_get_letter_status,
    cancel_letter_via_stannp,
    extract_tracking_stamps,
    apply_tracking_stamps_to_job,
    TOO_LATE_STANNP,
    CANCELLABLE_STANNP,
    bulk_sync_jobs_via_letters_get,
)

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get("", response_model=JobsListResponse)
def list_jobs(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sync: bool = Query(False),
    sender: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    mailing_type: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
):
    now = datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(days=30)
    stale_cutoff = now - timedelta(minutes=10)

    base_query = db.query(LetterJob).options(joinedload(LetterJob.user))

    if current_user.role not in ("admin", "manager"):
        base_query = base_query.filter(LetterJob.user_id == current_user.id)

    parsed_from_date = None
    parsed_to_date = None

    if from_date:
        parsed_from_date = datetime.strptime(from_date, "%Y-%m-%d").replace(
            tzinfo=timezone.utc, hour=0, minute=0, second=0, microsecond=0
        )

    if to_date:
        parsed_to_date = datetime.strptime(to_date, "%Y-%m-%d").replace(
            tzinfo=timezone.utc, hour=23, minute=59, second=59, microsecond=999999
        )

    query = apply_jobs_filters(
        base_query,
        sender=sender,
        search=search,
        mailing_type=mailing_type,
        status_filter=status_filter,
        from_date=parsed_from_date,
        to_date=parsed_to_date,
    )

    total = query.count()

    jobs = (
        query.order_by(LetterJob.sent_at.desc(), LetterJob.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    if sync:
        page_candidates = []
        for job in jobs:
            sent_at_utc = job.sent_at.replace(tzinfo=timezone.utc) if job.sent_at and job.sent_at.tzinfo is None else job.sent_at
            last_checked_utc = job.last_status_check.replace(tzinfo=timezone.utc) if job.last_status_check and job.last_status_check.tzinfo is None else job.last_status_check

            if not job.stannp_id:
                continue
            if not sent_at_utc:
                continue
            if sent_at_utc < recent_cutoff:
                continue
            if (job.status or "").lower() in ["failed", "cancelled"]:
                continue
            if last_checked_utc is not None and last_checked_utc > stale_cutoff:
                continue

            page_candidates.append(job)

        changed_any = False
        if page_candidates:
            changed_any = bulk_sync_jobs_via_letters_get(page_candidates)

        if changed_any:
            db.commit()
            db.expire_all()
            jobs = (
                query.order_by(LetterJob.sent_at.desc(), LetterJob.id.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "days": 30,
        "items": [serialize_job(j) for j in jobs],
    }


@router.get("/summary", response_model=JobsSummaryResponse)
def jobs_summary(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
    recent_days: int = Query(30, ge=1, le=3650),
    sender: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    mailing_type: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
):
    now = datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(days=recent_days)

    base_query = db.query(LetterJob)

    if current_user.role not in ("admin", "manager"):
        base_query = base_query.filter(LetterJob.user_id == current_user.id)

    parsed_from_date = None
    parsed_to_date = None

    if from_date:
        parsed_from_date = datetime.strptime(from_date, "%Y-%m-%d").replace(
            tzinfo=timezone.utc, hour=0, minute=0, second=0, microsecond=0
        )

    if to_date:
        parsed_to_date = datetime.strptime(to_date, "%Y-%m-%d").replace(
            tzinfo=timezone.utc, hour=23, minute=59, second=59, microsecond=999999
        )

    base_query = apply_jobs_filters(
        base_query,
        sender=sender,
        search=search,
        mailing_type=mailing_type,
        status_filter=status_filter,
        from_date=parsed_from_date,
        to_date=parsed_to_date,
    )

    all_jobs = base_query
    recent_jobs = base_query.filter(LetterJob.sent_at >= recent_cutoff)

    def count_display_status(query, status_name: str) -> int:
        s = status_name.strip().lower()

        if s == "delivered":
            return query.filter(delivered_expr()).count()

        if s == "failed":
            return query.filter(
                LetterJob.status.in_(["failed", "returned"])
            ).count()

        if s == "cancelled":
            return query.filter(LetterJob.status == "cancelled").count()

        if s == "needs_resend":
            return query.filter(LetterJob.status == "needs_resend").count()

        if s == "resent":
            return query.filter(LetterJob.status == "resent").count()

        if s == "sent":
            return query.filter(
                ~delivered_expr(),
                ~LetterJob.status.in_(
                    ["failed", "returned", "cancelled", "needs_resend", "resent", "delivered"]
                ),
            ).count()

        return query.filter(LetterJob.status == s).count()

    return {
        "total_jobs_all_time": all_jobs.count(),
        "total_jobs_recent": recent_jobs.count(),
        "sent_all_time": count_display_status(all_jobs, "sent"),
        "sent_recent": count_display_status(recent_jobs, "sent"),
        "delivered_all_time": count_display_status(all_jobs, "delivered"),
        "delivered_recent": count_display_status(recent_jobs, "delivered"),
        "needs_resend_all_time": count_display_status(all_jobs, "needs_resend"),
        "needs_resend_recent": count_display_status(recent_jobs, "needs_resend"),
        "failed_all_time": count_display_status(all_jobs, "failed"),
        "failed_recent": count_display_status(recent_jobs, "failed"),
        "cancelled_all_time": count_display_status(all_jobs, "cancelled"),
        "cancelled_recent": count_display_status(recent_jobs, "cancelled"),
        "recent_days": recent_days,
    }


@router.post("/{job_id}/request_resend")
def request_resend(
    job_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    job = get_accessible_job(db, job_id, current_user)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    effective_delivered = (
        getattr(job, "delivered_scan_at", None) is not None
        or (job.status or "").lower() == "delivered"
        or (job.stannp_status or "").lower() == "delivered"
    )

    if effective_delivered:
        raise HTTPException(
            status_code=400,
            detail="This job is already delivered and cannot be marked for resend."
        )

    job.status = "needs_resend"
    job.last_status_check = datetime.now(timezone.utc)

    db.add(job)
    db.commit()
    db.refresh(job)

    return {
        "status": "ok",
        "job_id": job.id,
        "new_status": job.status,
        "user_message": "This job has been flagged as 'needs_resend'.",
    }


@router.post("/{job_id}/auto_resend")
def auto_resend_specific_job(
    job_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    job = get_accessible_job(db, job_id, current_user)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = auto_resend_job(job)

    db.add(job)
    db.commit()
    db.refresh(job)

    return {
        "status": "ok",
        "job_id": job.id,
        "stannp_id": job.stannp_id,
        "result": result,
        "user_message": "Letter resent successfully.",
    }


@router.post("/{job_id}/sync_status")
def sync_status_from_stannp(
    job_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    job = get_accessible_job(db, job_id, current_user)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if not job.stannp_id:
        raise HTTPException(
            status_code=400,
            detail="This job has no Stannp ID stored, so status cannot be synced.",
        )

    changed = sync_job_from_letters_get(job)

    db.add(job)
    db.commit()
    db.refresh(job)

    remote_status = (job.stannp_status or "").lower()
    bucket = map_stannp_status(remote_status)

    return {
        "status": "ok",
        "job_id": job.id,
        "stannp_id": job.stannp_id,
        "stannp_status": job.stannp_status,
        "stannp_status_display": (
            "delivered"
            if (
                (job.stannp_status or "").lower() == "delivered"
                or (job.status or "").lower() == "delivered"
                or getattr(job, "delivered_scan_at", None) is not None
            )
            else job.stannp_status
        ),
        "display_status": (
            "delivered"
            if (
                getattr(job, "delivered_scan_at", None) is not None
                or (job.status or "").lower() == "delivered"
                or (job.stannp_status or "").lower() == "delivered"
            )
            else (job.status or "sent")
        ),
        "local_status": job.status,
        "bucket": bucket,
        "changed": changed,
        "user_message": f"Stannp reports '{remote_status}'. Local workflow status is '{job.status}'.",
    }


@router.post("/{job_id}/cancel")
def cancel_job(
    job_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    job = get_accessible_job(db, job_id, current_user)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if not job.stannp_id:
        raise HTTPException(
            status_code=400,
            detail="This job has no Stannp ID and cannot be cancelled.",
        )

    detail = stannp_get_letter_status(str(job.stannp_id))
    remote_status = (((detail.get("data") or {}).get("status")) or "").strip().lower()

    stamps = extract_tracking_stamps(detail)
    apply_tracking_stamps_to_job(job, stamps)

    if not remote_status:
        raise HTTPException(
            status_code=502,
            detail="Could not determine Stannp status for this job; cannot cancel safely.",
        )

    job.stannp_status = remote_status
    job.last_status_check = datetime.now(timezone.utc)
    db.add(job)

    if remote_status in TOO_LATE_STANNP:
        db.commit()
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel because Stannp status is '{remote_status}'.",
        )

    if remote_status not in CANCELLABLE_STANNP:
        db.commit()
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel because Stannp status is '{remote_status}'. Only {sorted(CANCELLABLE_STANNP)} are cancellable.",
        )

    cancel_result = cancel_letter_via_stannp(job.stannp_id)

    job.status = "cancelled"
    job.stannp_status = "cancelled"
    job.last_status_check = datetime.now(timezone.utc)

    note = f"Cancelled via API at {job.last_status_check.isoformat()}."
    job.error_message = f"{job.error_message}\n{note}" if job.error_message else note

    db.add(job)
    db.commit()
    db.refresh(job)

    return {
        "status": "ok",
        "job_id": job.id,
        "stannp_id": job.stannp_id,
        "cancel_result": cancel_result,
        "new_status": job.status,
        "stannp_status": job.stannp_status,
        "user_message": "Cancellation requested and job marked cancelled locally.",
    }


@router.post("/sync_recent")
def sync_recent_jobs(
    db: Session = Depends(get_db),
    current_user=Depends(require_manager_or_admin),
    days: int = Query(30, ge=1, le=3650),
):
    now = datetime.now(timezone.utc)
    cutoff_check = now - timedelta(minutes=10)
    recent_cutoff = now - timedelta(days=days)

    sync_query = (
        db.query(LetterJob)
        .filter(LetterJob.stannp_id.isnot(None))
        .filter(LetterJob.sent_at.isnot(None))
        .filter(LetterJob.sent_at >= recent_cutoff)
        .filter(~LetterJob.status.in_(["failed", "cancelled"]))
        .filter((LetterJob.last_status_check.is_(None)) | (LetterJob.last_status_check <= cutoff_check))
        .order_by(LetterJob.last_status_check.asc().nullsfirst(), LetterJob.sent_at.asc())
        .limit(500)
    )

    to_refresh = sync_query.all()

    updated_any = False
    if to_refresh:
        updated_any = bulk_sync_jobs_via_letters_get(to_refresh)

    if updated_any:
        db.commit()

    return {
        "status": "ok",
        "synced": len(to_refresh),
        "updated_any": updated_any,
        "days": days,
    }


@router.post("/repair_delivered_statuses")
def repair_delivered_statuses(
    db: Session = Depends(get_db),
    current_user=Depends(require_manager_or_admin),
):
    jobs = db.query(LetterJob).filter(
        LetterJob.status == "needs_resend"
    ).all()

    repaired = 0

    for job in jobs:
        delivered_like = (
            job.delivered_scan_at is not None
            or (job.stannp_status or "").lower() == "delivered"
        )

        if delivered_like:
            job.status = "delivered"
            job.last_status_check = datetime.now(timezone.utc)
            db.add(job)
            repaired += 1

    db.commit()

    return {
        "status": "ok",
        "checked": len(jobs),
        "repaired": repaired,
    }