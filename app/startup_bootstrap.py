"""One-shot bootstrap when the users table is empty (e.g. fresh SQLite on Cloud Run)."""
import logging
import os

from sqlalchemy.orm import Session

from app.models.user import User
from app.services.auth_service import get_password_hash, get_user_by_email, normalize_email

logger = logging.getLogger(__name__)


def ensure_initial_admin_if_empty(db: Session) -> None:
    if db.query(User).first() is not None:
        return

    if os.getenv("SKIP_AUTO_BOOTSTRAP_ADMIN", "").lower() in ("1", "true", "yes"):
        logger.warning("Users table empty and SKIP_AUTO_BOOTSTRAP_ADMIN is set; skipping default admin.")
        return

    email = normalize_email(os.getenv("BOOTSTRAP_ADMIN_EMAIL", "admin@thelawguys.com"))
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "Admin.123!")

    user = User(
        email=email,
        hashed_password=get_password_hash(password),
        role="admin",
        is_active=True,
        must_change_password=False,
        can_change_password=True,
    )
    db.add(user)
    db.commit()
    logger.info("Created initial admin user %s (table was empty).", email)


def upsert_bootstrap_admin(db: Session) -> None:
    """CLI/script: create or update admin (idempotent)."""
    email = normalize_email(os.getenv("BOOTSTRAP_ADMIN_EMAIL", "admin@thelawguys.com"))
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "Admin.123!")

    user = get_user_by_email(db, email)
    if user:
        user.hashed_password = get_password_hash(password)
        user.role = "admin"
        user.is_active = True
        user.must_change_password = False
        user.can_change_password = True
        db.add(user)
        db.commit()
        print(f"Updated existing user: {email} (admin)")
    else:
        user = User(
            email=email,
            hashed_password=get_password_hash(password),
            role="admin",
            is_active=True,
            must_change_password=False,
            can_change_password=True,
        )
        db.add(user)
        db.commit()
        print(f"Created admin user: {email}")
