import os
import tempfile
from pathlib import Path

# Point the app at a throwaway SQLite file BEFORE anything imports app.db.
_tmp = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}"
os.environ["SESSION_SECRET"] = "test-secret"
os.environ["ADMIN_USERNAME"] = "john"
os.environ["ADMIN_PASSWORD"] = "admin-password-123"
os.environ["CLUB_CODE"] = "moose"
os.environ["CLUB_TODAY"] = "2026-10-22"  # a Thursday in week 2
