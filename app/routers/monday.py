from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.dependencies import get_db
from app.schemas.monday import MondaySendFromDriveRequest
from app.services.auth_service import get_current_active_user
from app.services.monday_service import verify_monday_request
from app.services.mailing_service import process_send_from_drive
from app.services.monday_service import post_monday_comment

router = APIRouter(prefix="/integrations/monday", tags=["Monday"])


@router.post("/actions/send_from_drive")
def send_from_drive(
    payload: MondaySendFromDriveRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    verify_monday_request(authorization)

    result = process_send_from_drive(
        board_id=payload.board_id,
        item_id=payload.item_id,
        drive_folder_id=payload.drive_folder_id,
        drive_file_id=payload.drive_file_id,
        expected_pdf_name=payload.expected_pdf_name,
        db=db,
        current_user=current_user,
    )
    
    if result:
        message = f"Letter successfully sent via Stannp. Job ID: {result.get('job_id')}"
        post_monday_comment(item_id=payload.item_id, message=message)

    return {
        "status": "ok",
        "result": result,
    }
    
class CommentRequest(BaseModel):
    item_id: int
    
@router.post("/trigger-comment")
def trigger_monday_comment(payload: CommentRequest):
    # This calls the create_monday_update function in your client
    result = post_monday_comment(
        item_id=payload.item_id, 
        message="Process Complete: Letter has been sent via Stannp."
    )
    return {"status": "success", "details": result}