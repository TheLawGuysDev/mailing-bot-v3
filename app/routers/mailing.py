from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.services.auth_service import get_current_active_user, require_manager_or_admin
from app.services.mailing_service import create_letter_jobs_from_pdf_bytes
from app.services.pdf_service import extract_addresses_from_pdf
from app.services.job_service import run_12_day_check_logic

router = APIRouter(tags=["Mailing"])


@router.post("/preview_addresses")
async def preview_addresses(
    pdf: UploadFile = File(...),
    current_user=Depends(get_current_active_user),
):
    if pdf.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")

    pdf_bytes = await pdf.read()
    info = extract_addresses_from_pdf(pdf_bytes)
    addresses = info["addresses"]

    if not addresses:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "user_message": (
                    "⚠️ I couldn't find any valid mailing addresses in this PDF.\n\n"
                    "Please make sure each address is in this format and separated by a blank line:\n"
                    "Name\nStreet Address\n(optional extra lines)\nCity, ST ZIP"
                ),
                "technical_message": (
                    "No valid address blocks were found in the PDF. "
                    "Each address should follow 'Name / Street / (Optional extra lines) / City, ST ZIP'."
                ),
                "total_pages": info["total_pages"],
                "address_pages": info["address_pages"],
                "body_page_start": info["body_page_start"],
                "body_page_end": info["body_page_end"],
            },
        )

    results = []
    for idx, addr in enumerate(addresses, start=1):
        results.append(
            {
                "index": idx,
                "address": addr.as_dict(),
                "status": "preview",
                "prompt": "👀 Review this address carefully before sending.",
            }
        )

    total = len(addresses)
    user_message = (
        f"👀 Preview only: I found {total} address(es) in this PDF. "
        "The legal document pages after the address section will be sent."
    )

    return {
        "status": "ok",
        "file_name": pdf.filename,
        "total_addresses_found": total,
        "results": results,
        "user_message": user_message,
        "total_pages": info["total_pages"],
        "address_pages": info["address_pages"],
        "body_page_start": info["body_page_start"],
        "body_page_end": info["body_page_end"],
    }


@router.post("/send_letters_with_prompts")
async def send_letters_with_prompts(
    pdf: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    if pdf.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")

    pdf_bytes = await pdf.read()
    original_file_name = pdf.filename or "uploaded.pdf"

    return create_letter_jobs_from_pdf_bytes(
        pdf_bytes=pdf_bytes,
        original_file_name=original_file_name,
        db=db,
        current_user=current_user,
        save_pdf=True,
    )


@router.post("/send_letters")
async def send_letters(
    pdf: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    if pdf.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")

    pdf_bytes = await pdf.read()
    original_file_name = pdf.filename or "uploaded.pdf"

    return create_letter_jobs_from_pdf_bytes(
        pdf_bytes=pdf_bytes,
        original_file_name=original_file_name,
        db=db,
        current_user=current_user,
        save_pdf=False,
    )


@router.post("/run_12_day_check_with_prompts")
def run_12_day_check_with_prompts(
    db: Session = Depends(get_db),
    auto_resend: bool = False,
    # Batched 13-day check: use after_id from response.next_after_id while has_more is true.
    batch_size: int = Query(75, ge=1, le=200),
    after_id: int = Query(0, ge=0),
    current_user=Depends(require_manager_or_admin),
):
    base_result = run_12_day_check_logic(
        db=db,
        auto_resend=auto_resend,
        batch_size=batch_size,
        after_id=after_id,
    )

    checked = base_result.get("checked", 0)
    marked = base_result.get("marked_needs_resend", 0)
    auto_success = base_result.get("auto_resend_success", 0)
    auto_failed = base_result.get("auto_resend_failed", 0)
    sync_errors = base_result.get("sync_errors", 0)
    has_more = base_result.get("has_more", False)

    if checked == 0:
        user_message = "ℹ️ There were no previously sent letters to check in this batch (or nothing left after this cursor)."
    elif not auto_resend:
        if marked == 0:
            user_message = f"✅ This batch: checked {checked} letter(s). None newly marked as 'needs_resend'."
        else:
            user_message = (
                f"⏰ This batch: checked {checked} letter(s). "
                f"{marked} are 12+ days old and are now marked as 'needs_resend'. "
                "You can review and manually resend them from the dashboard."
            )
    else:
        if auto_success == 0 and auto_failed == 0:
            user_message = f"ℹ️ This batch: checked {checked} letter(s); none required auto-resend."
        else:
            user_message = (
                f"⏰ This batch: checked {checked} letter(s). "
                f"{auto_success} were automatically resent using the stored PDFs. "
            )
            if auto_failed > 0:
                user_message += (
                    f"{auto_failed} could not be resent automatically and are "
                    "marked as 'needs_resend' for manual review."
                )

    # Surface per-batch Stannp failures so operators can retry without guessing.
    if sync_errors:
        user_message += (
            f" ⚠️ {sync_errors} job(s) in this batch could not be reached on Stannp "
            "(left unchanged; try again later)."
        )
    if has_more:
        user_message += " More batches remain — run again (the dashboard continues automatically)."

    base_result["user_message"] = user_message
    return base_result