import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.monday_job_link import MondayJobLink
from app.services.drive_service import resolve_drive_file, fetch_drive_pdf_bytes
from app.services.monday_service import update_monday_send_result, post_monday_comment


from app.config import PDF_STORAGE_DIR
from app.models.letter_job import LetterJob
from app.models.user import User
from app.services.pdf_service import (
    detect_mailing_type,
    extract_addresses_from_pdf,
    count_pdf_pages,
    insert_blank_after_first_page,
)
from app.services.stannp_service import send_letter_via_stannp


def create_letter_jobs_from_pdf_bytes(
    pdf_bytes: bytes,
    original_file_name: str,
    db: Session,
    current_user: User,
    save_pdf: bool = True,
):
    mailing_type = detect_mailing_type(original_file_name)

    info = extract_addresses_from_pdf(pdf_bytes)
    addresses = info["addresses"]
    body_pdf_bytes = info.get("body_pdf_bytes") or pdf_bytes

    body_pages = count_pdf_pages(body_pdf_bytes)
    duplex = body_pages >= 6

    if duplex:
        body_pdf_bytes = insert_blank_after_first_page(body_pdf_bytes)

    if not addresses:
        raise HTTPException(
            status_code=400,
            detail=(
                "No valid address blocks were found in the PDF. "
                "Make sure each address follows this format and is separated by a blank line:\n"
                "Name\nStreet Address\n(optional extra lines)\nCity, ST ZIP"
            ),
        )

    pdf_path: Optional[str] = None
    if save_pdf:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        safe_name = f"{timestamp}_{original_file_name}"
        pdf_path = os.path.join(PDF_STORAGE_DIR, safe_name)
        with open(pdf_path, "wb") as f:
            f.write(body_pdf_bytes)

    results = []

    for idx, addr in enumerate(addresses, start=1):
        merged_address2 = " ".join(part for part in [addr.address2, addr.address3] if part)

        try:
            stannp_res = send_letter_via_stannp(
                addr, body_pdf_bytes, mailing_type=mailing_type, duplex=duplex
            )

            stannp_id = stannp_res.get("data", {}).get("id") or stannp_res.get("id")

            job = LetterJob(
                stannp_id=stannp_id,
                user_id=current_user.id,
                recipient_name=addr.name,
                address1=addr.address1,
                address2=merged_address2,
                city=addr.city,
                state=addr.state,
                postcode=addr.postcode,
                country=addr.country,
                status="sent",
                sent_at=datetime.now(timezone.utc),
                last_status_check=None,
                file_name=original_file_name,
                pdf_path=pdf_path,
                mailing_type=mailing_type,
            )
            db.add(job)
            db.commit()
            db.refresh(job)

            results.append(
                {
                    "index": idx,
                    "address": addr.as_dict(),
                    "status": "sent",
                    "job_id": job.id,
                    "stannp_id": stannp_id,
                    "prompt": "✅ Letter queued successfully for this address via Stannp.",
                }
            )

        except HTTPException as e:
            job = LetterJob(
                stannp_id=None,
                user_id=current_user.id,
                recipient_name=addr.name,
                address1=addr.address1,
                address2=merged_address2,
                city=addr.city,
                state=addr.state,
                postcode=addr.postcode,
                country=addr.country,
                status="failed",
                sent_at=datetime.now(timezone.utc),
                last_status_check=None,
                error_message=str(e.detail),
                file_name=original_file_name,
                pdf_path=pdf_path,
                mailing_type=mailing_type,
            )
            db.add(job)
            db.commit()
            db.refresh(job)

            results.append(
                {
                    "index": idx,
                    "address": addr.as_dict(),
                    "status": "failed",
                    "job_id": job.id,
                    "error": str(e.detail),
                    "prompt": "❌ This letter failed to send. Please check the address or PDF and try again.",
                }
            )

    total = len(addresses)
    sent_count = sum(1 for r in results if r["status"] == "sent")
    failed_count = sum(1 for r in results if r["status"] == "failed")

    if sent_count == total and failed_count == 0:
        user_message = f"✅ I found {total} address(es) in this PDF and successfully queued all of them with Stannp."
    elif sent_count > 0 and failed_count > 0:
        user_message = f"⚠️ I found {total} address(es). I sent {sent_count}, but {failed_count} failed. Please review the failed ones."
    else:
        user_message = f"❌ I found {total} address(es), but all of them failed to send. Please verify the addresses and PDF formatting, then try again."

    return {
        "status": "ok",
        "file_name": original_file_name,
        "total_addresses_found": total,
        "results": results,
        "user_message": user_message,
        "total_pages": info["total_pages"],
        "address_pages": info["address_pages"],
        "body_page_start": info["body_page_start"],
        "body_page_end": info["body_page_end"],
        "body_pages": body_pages,
        "duplex": duplex,
    }

def link_monday_jobs(
    db: Session,
    *,
    monday_board_id: int,
    monday_item_id: int,
    drive_folder_id: str | None,
    drive_file_id: str | None,
    expected_file_name: str | None,
    source_action: str,
    created_job_ids: list[int],
):
    for job_id in created_job_ids:
        link = MondayJobLink(
            job_id=job_id,
            monday_board_id=str(monday_board_id),
            monday_item_id=str(monday_item_id),
            drive_folder_id=drive_folder_id,
            drive_file_id=drive_file_id,
            expected_file_name=expected_file_name,
            source_action=source_action,
        )
        db.add(link)

    db.commit()


def process_send_from_drive(
    *,
    board_id: int,
    item_id: int,
    drive_folder_id: str | None,
    drive_file_id: str | None,
    expected_pdf_name: str | None,
    db: Session,
    current_user: User,
):
    resolved_file = resolve_drive_file(
        drive_file_id=drive_file_id,
        drive_folder_id=drive_folder_id,
        expected_pdf_name=expected_pdf_name,
    )

    file_name = resolved_file.get("file_name") or expected_pdf_name or "monday_uploaded.pdf"

    pdf_bytes = fetch_drive_pdf_bytes(resolved_file)

    result = create_letter_jobs_from_pdf_bytes(
        pdf_bytes=pdf_bytes,
        original_file_name=file_name,
        db=db,
        current_user=current_user,
        save_pdf=True,
    )

    created_job_ids = []
    created_stannp_ids = []

    for item in result.get("results", []):
        if item.get("job_id"):
            created_job_ids.append(item["job_id"])
        if item.get("stannp_id"):
            created_stannp_ids.append(item["stannp_id"])

    link_monday_jobs(
        db=db,
        monday_board_id=board_id,
        monday_item_id=item_id,
        drive_folder_id=drive_folder_id,
        drive_file_id=drive_file_id or resolved_file.get("file_id"),
        expected_file_name=expected_pdf_name or file_name,
        source_action="send_from_drive",
        created_job_ids=created_job_ids,
    )

    update_monday_send_result(
        item_id=item_id,
        bot_status="sent" if created_job_ids else "failed",
        job_ids=created_job_ids,
        stannp_ids=created_stannp_ids,
        message=result.get("user_message"),
    )

    post_monday_comment(
        item_id=item_id,
        message=result.get("user_message", "Mailing bot processed this item."),
    )

    return {
        "board_id": board_id,
        "item_id": item_id,
        "resolved_file": resolved_file,
        "send_result": result,
        "created_job_ids": created_job_ids,
        "created_stannp_ids": created_stannp_ids,
    }