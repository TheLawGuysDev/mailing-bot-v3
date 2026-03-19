from fastapi import HTTPException

from app.config import GCS_BUCKET, APP_ENV


def _storage_module():
    try:
        from google.cloud import storage
        return storage
    except ModuleNotFoundError as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "google-cloud-storage is not installed. "
                "Run: pip install google-cloud-storage"
            ),
        ) from e


def _client():
    storage = _storage_module()
    return storage.Client()


def _bucket():
    if not GCS_BUCKET:
        raise HTTPException(
            status_code=500,
            detail=(
                "GCS_BUCKET is not configured. "
                "Set it in production, or add it locally if you want to test GCS."
            ),
        )

    client = _client()
    return client.bucket(GCS_BUCKET)


def upload_pdf_bytes(pdf_bytes: bytes, blob_name: str, content_type: str = "application/pdf") -> str:
    try:
        bucket = _bucket()
        blob = bucket.blob(blob_name)
        blob.upload_from_string(pdf_bytes, content_type=content_type)
        return blob_name
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload PDF to GCS: {e}")


def download_pdf_bytes(blob_name: str) -> bytes:
    try:
        bucket = _bucket()
        blob = bucket.blob(blob_name)

        if not blob.exists():
            raise HTTPException(status_code=404, detail=f"GCS blob not found: {blob_name}")

        return blob.download_as_bytes()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download PDF from GCS: {e}")


def delete_blob_if_exists(blob_name: str) -> bool:
    try:
        bucket = _bucket()
        blob = bucket.blob(blob_name)

        if blob.exists():
            blob.delete()
            return True

        return False
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete blob from GCS: {e}")