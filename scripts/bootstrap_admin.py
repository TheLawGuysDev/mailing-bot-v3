"""
Create or update the bootstrap admin user. Idempotent.

Run from repo root (or /app in Docker):
  python scripts/bootstrap_admin.py

Override defaults with env BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.chdir(ROOT)

from app.db import SessionLocal
from app.startup_bootstrap import upsert_bootstrap_admin


def main() -> None:
    db = SessionLocal()
    try:
        upsert_bootstrap_admin(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
