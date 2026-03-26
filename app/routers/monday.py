from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.monday import MondaySendFromDriveRequest
from app.models.user import User
from app.services.auth_service import get_current_active_user
from app.services.mailing_service import process_send_from_drive
from app.services.mailing_service import create_letter_jobs_from_pdf_bytes
from app.clients.monday_client import get_file_from_column
from app.clients.monday_client import get_column_id_by_title
from app.services.monday_service import verify_monday_request
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
        
@router.post("/webhooks/status-change")
async def handle_status_webhook(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    
    # Required for Monday webhook verification
    if "challenge" in data:
        return {"challenge": data["challenge"]}

    event = data.get("event", {})
    item_id = event.get("pulseId")
    board_id = event.get("boardId")
    print(f"DEBUG: Received webhook for Item ID: {item_id}")
    
    col_id = get_column_id_by_title(board_id, "Stannp Files")
    
    if not col_id:
        print(f"DEBUG: Could not find a column named 'Stannp Files' on board {board_id}")
        return {"status": "error", "message": "Column not found"}
    
    # 'files' should be the ID of your column in Monday
    file_data = get_file_from_column(item_id, column_id=col_id)
    
    if not file_data:
        print(f"DEBUG: No file found in column file_mm1gnvza for item {item_id}")
        return {"status": "no_file_found"}

    print(f"DEBUG: Found file {file_data['name']}, starting Stannp process...")

    if file_data:
        # Fetch default user for database record
        default_user = db.query(User).first()
        
        # Process the mailing via your existing service
        result = create_letter_jobs_from_pdf_bytes(
            pdf_bytes=file_data["bytes"],
            original_file_name=file_data["name"],
            db=db,
            current_user=default_user,
            save_pdf=False
        )
        
        # Post the result as a comment
        post_monday_comment(item_id, result.get("user_message", "Mailing processed."))
        
    else:
        print(f"DEBUG: Column {col_id} is empty for item {item_id}")

    return {"status": "success"}