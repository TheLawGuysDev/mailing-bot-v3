from fastapi import HTTPException


def get_file_by_id(file_id: str) -> dict:
    """
    Placeholder for Google Drive API lookup by file ID.
    Later:
      - use service account credentials
      - fetch metadata + downloadable content
    """
    if not file_id:
        raise HTTPException(status_code=400, detail="Missing drive file ID")

    return {
        "file_id": file_id,
        "name": None,
        "mime_type": "application/pdf",
        "bytes": None,
        "found": True,
        "source": "file_id_stub",
    }


def find_file_in_folder(folder_id: str, filename: str) -> dict:
    """
    Placeholder for exact filename lookup inside a folder.
    Later:
      - search only within the given folder
      - require exact filename match
    """
    if not folder_id:
        raise HTTPException(status_code=400, detail="Missing drive folder ID")
    if not filename:
        raise HTTPException(status_code=400, detail="Missing expected filename")

    return {
        "file_id": None,
        "folder_id": folder_id,
        "name": filename,
        "mime_type": "application/pdf",
        "bytes": None,
        "found": True,
        "source": "folder_filename_stub",
    }


def download_file_bytes(file_id: str) -> bytes:
    """
    Placeholder for actual file content download.
    """
    if not file_id:
        raise HTTPException(status_code=400, detail="Missing drive file ID for download")

    raise HTTPException(
        status_code=501,
        detail="Google Drive download is not wired yet. Stub client in place."
    )