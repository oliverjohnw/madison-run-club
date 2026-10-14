"""
Passwords, sessions, and the login wall.

Anyone with the club code (CLUB_CODE env var) can sign up at /signup. The
admin login is created on startup from ADMIN_USERNAME / ADMIN_PASSWORD.

Sessions are Starlette's signed cookie holding {"user_id": ..., "setup": bool}.
Signed, not encrypted - never put anything secret in it. "setup" is set while a
new member still has the welcome quiz to do, so the gate can send them there
without a database lookup on every request.
"""

import os
import re
import time
from collections import defaultdict, deque

import bcrypt
from sqlalchemy import func, select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app.db import SessionLocal
from app.models import User

PUBLIC_PATH_PREFIXES = ("/login", "/signup", "/static", "/favicon.ico", "/healthz")
SETUP_ALLOWED_PREFIXES = ("/welcome", "/logout", "/avatars", "/static", "/settings")
USERNAME_RE = re.compile(r"^[a-z0-9_.-]{2,24}$")
MIN_PASSWORD = 1  # no length rule; it's a run club


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def get_user_by_username(username: str) -> User | None:
    with SessionLocal() as session:
        return session.scalar(select(User).where(func.lower(User.username) == username.strip().lower()))


def get_user_by_id(user_id: int) -> User | None:
    with SessionLocal() as session:
        return session.get(User, user_id)


def set_password(username: str, password: str, admin: bool = False) -> bool:
    """Create the user, or reset their password if they exist. Returns True if created."""
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.username == username))
        created = user is None
        if created:
            user = User(username=username, display_name=username.title(), password_hash=hash_password(password))
            session.add(user)
        else:
            user.password_hash = hash_password(password)
        if admin:
            user.is_admin = True
        session.commit()
        return created


def ensure_admin_user() -> None:
    """On startup: create the admin from env vars if they don't exist yet. Never overwrites a password."""
    username = os.environ.get("ADMIN_USERNAME", "").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD", "")
    if username and password and get_user_by_username(username) is None:
        set_password(username, password, admin=True)


def club_code() -> str:
    return os.environ.get("CLUB_CODE", "").strip()


def log_in_user(request: Request, user: User) -> None:
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["setup"] = not user.onboarded


def log_out_user(request: Request) -> None:
    request.session.clear()


def get_current_user(request: Request) -> User | None:
    user_id = request.session.get("user_id")
    return get_user_by_id(user_id) if user_id is not None else None


# --- Login throttling (in-memory; resets on restart, fine for one instance) ---
MAX_FAILURES = 8
WINDOW_SECONDS = 15 * 60
_failures: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def login_blocked(request: Request) -> bool:
    attempts = _failures[_client_ip(request)]
    cutoff = time.monotonic() - WINDOW_SECONDS
    while attempts and attempts[0] < cutoff:
        attempts.popleft()
    return len(attempts) >= MAX_FAILURES


def record_failed_login(request: Request) -> None:
    _failures[_client_ip(request)].append(time.monotonic())


def clear_failed_logins(request: Request) -> None:
    _failures.pop(_client_ip(request), None)


class AuthGateMiddleware(BaseHTTPMiddleware):
    """Logged out -> /login. Logged in but quiz not done -> /welcome."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not any(path.startswith(p) for p in PUBLIC_PATH_PREFIXES):
            if request.session.get("user_id") is None:
                return RedirectResponse("/login", status_code=303)
            if request.session.get("setup") and not any(path.startswith(p) for p in SETUP_ALLOWED_PREFIXES):
                return RedirectResponse("/welcome", status_code=303)
        return await call_next(request)
