from fastapi import HTTPException

from app.clients.google_drive_client import (
    get_file_by_id,
    find_file_in_folder,
    download_file_bytes,
)


def resolve_drive_file(
    drive_file_id: str | None,
    drive_folder_id: str | None,
    expected_pdf_name: str | None,
) -> dict:
    """
    Resolution order:
      1. direct file ID
      2. folder + exact filename
      3. fail safely
    """
    if drive_file_id:
        meta = get_file_by_id(drive_file_id)
        return {
            "resolved": True,
            "method": "drive_file_id",
            "file_id": drive_file_id,
            "file_name": meta.get("name"),
            "meta": meta,
        }

    if drive_folder_id and expected_pdf_name:
        meta = find_file_in_folder(drive_folder_id, expected_pdf_name)
        return {
            "resolved": True,
            "method": "folder_exact_filename",
            "file_id": meta.get("file_id"),
            "file_name": meta.get("name") or expected_pdf_name,
            "meta": meta,
        }

    raise HTTPException(
        status_code=400,
        detail=(
            "Could not resolve Drive file. Provide either drive_file_id, "
            "or drive_folder_id + expected_pdf_name."
        ),
    )


def fetch_drive_pdf_bytes(resolved_file: dict) -> bytes:
    file_id = resolved_file.get("file_id")
    if not file_id:
        raise HTTPException(
            status_code=400,
            detail="Resolved Drive file does not include a downloadable file_id yet."
        )

    return download_file_bytes(file_id)