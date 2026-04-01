from dotenv import load_dotenv
import os

load_dotenv(".env", override=False)

if os.path.exists(".env.local"):
    load_dotenv(".env.local", override=True)

APP_ENV = os.getenv("APP_ENV", "").lower() or "local"

_raw_db = (os.getenv("DATABASE_URL") or "").strip()
# Cloud Run / zero-config: ephemeral SQLite (no DATABASE_URL env needed).
DATABASE_URL = _raw_db or "sqlite:////tmp/mailing_bot.db"

STANNP_API_KEY = os.getenv("STANNP_API_KEY")
STANNP_BASE_URL = os.getenv("STANNP_BASE_URL", "https://us.stannp.com/api/v1")
STANNP_REPORTING_BASE_URL = os.getenv(
    "STANNP_REPORTING_BASE_URL",
    "https://api-us1.stannp.com/v1",
)
STANNP_TEST_MODE = os.getenv("STANNP_TEST_MODE", "true").lower() == "true"
STANNP_API_V1 = os.getenv("STANNP_API_V1", "https://api-us1.stannp.com/v1")

FROM_NAME = os.getenv("FROM_NAME", "The law guys")
FROM_ADDRESS1 = os.getenv("FROM_ADDRESS1", "4231 Balboa Avenue")
FROM_ADDRESS2 = os.getenv("FROM_ADDRESS2", "Suite 1261")
FROM_CITY = os.getenv("FROM_CITY", "San Diego")
FROM_STATE = os.getenv("FROM_STATE", "CA")
FROM_POSTCODE = os.getenv("FROM_POSTCODE", "92117")
FROM_COUNTRY = os.getenv("FROM_COUNTRY", "US")

PDF_RETENTION_DAYS_NORMAL = int(os.getenv("PDF_RETENTION_DAYS_NORMAL", "14"))
PDF_RETENTION_DAYS_RESEND = int(os.getenv("PDF_RETENTION_DAYS_RESEND", "28"))

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "240"))

MONDAY_SIGNING_SECRET = os.getenv("MONDAY_SIGNING_SECRET", "")
MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN", "")
MONDAY_API_URL = os.getenv("MONDAY_API_URL", "https://api.monday.com/v2")

GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")
GOOGLE_DRIVE_SHARED_DRIVE_ID = os.getenv("GOOGLE_DRIVE_SHARED_DRIVE_ID", "")
GCS_BUCKET = os.getenv("GCS_BUCKET", "")

if not STANNP_API_KEY:
    raise RuntimeError("STANNP_API_KEY is not set.")

# Only require bucket outside local/dev
if APP_ENV in ("production", "prod") and not GCS_BUCKET:
    raise RuntimeError("GCS_BUCKET is required in production.")