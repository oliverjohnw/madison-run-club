"""Small helpers every route module uses."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app.auth import get_current_user
from app.models import Meetup, User


class StaleSession(Exception):
    """The login cookie points at an account that no longer exists (e.g. it was removed)."""


def me(request: Request) -> User:
    user = get_current_user(request)
    if user is None:
        # The gate already sent anyone without a cookie to /login, so this is a cookie for a
        # deleted account. Forget it; main.py turns this into a redirect to /login.
        request.session.clear()
        raise StaleSession()
    return user


def admin_only(request: Request) -> User:
    user = me(request)
    if not user.is_admin:
        raise HTTPException(403)
    return user


def users_by_id(session: Session) -> dict[int, User]:
    return {u.id: u for u in session.scalars(select(User).order_by(User.display_name))}


def meetups_by_id(session: Session) -> dict[int, Meetup]:
    return {m.id: m for m in session.scalars(select(Meetup))}


def back(request: Request, fallback: str = "/") -> RedirectResponse:
    """Redirect to ?next=/somewhere (local paths only) or the fallback."""
    nxt = request.query_params.get("next", "")
    target = nxt if nxt.startswith("/") and not nxt.startswith("//") else fallback
    return RedirectResponse(target, status_code=303)
