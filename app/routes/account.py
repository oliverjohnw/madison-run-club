"""Log in, sign up, log out, profile settings, profile pictures."""

import hmac

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import undefer
from starlette.responses import RedirectResponse

from app import avatars
from app.auth import (
    MIN_PASSWORD,
    USERNAME_RE,
    clear_failed_logins,
    club_code,
    get_current_user,
    get_user_by_username,
    hash_password,
    log_in_user,
    log_out_user,
    login_blocked,
    record_failed_login,
    verify_password,
)
from app.db import SessionLocal
from app.models import User
from app.routes.deps import me
from app.templating import render

router = APIRouter()


def valid_phone(text: str) -> bool:
    """Loose on purpose: 7-15 digits, any formatting."""
    return 7 <= sum(c.isdigit() for c in text) <= 15


@router.get("/login")
def login_page(request: Request):
    if get_current_user(request):
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html")


@router.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if login_blocked(request):
        return render(request, "login.html", {"error": "Too many tries. Give it 15 minutes.", "username": username}, status_code=429)
    user = get_user_by_username(username)
    if not user or not verify_password(password, user.password_hash):
        record_failed_login(request)
        return render(request, "login.html", {"error": "That username and password don't match.", "username": username}, status_code=401)
    clear_failed_logins(request)
    log_in_user(request, user)
    return RedirectResponse("/welcome" if not user.onboarded else "/", status_code=303)


@router.get("/signup")
def signup_page(request: Request):
    if get_current_user(request):
        return RedirectResponse("/", status_code=303)
    return render(request, "signup.html", {"need_code": bool(club_code()), "form": {}})


@router.post("/signup")
def signup_submit(
    request: Request,
    username: str = Form(""),
    full_name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    password: str = Form(""),
    code: str = Form(""),
):
    form = {"username": username, "full_name": full_name, "email": email, "phone": phone, "code": code}
    username = username.strip().lower()
    error = None
    if login_blocked(request):  # shares the login throttle, so the club code can't be brute-forced
        return render(request, "signup.html", {"error": "Too many tries. Give it 15 minutes.", "need_code": bool(club_code()),
                                               "form": form}, status_code=429)
    if club_code() and not hmac.compare_digest(code.strip().lower(), club_code().lower()):
        record_failed_login(request)
        error = "That club code isn't right. Ask John for it."
    elif not USERNAME_RE.match(username):
        error = "Usernames are 2-24 characters: letters, numbers, dots, dashes, underscores."
    elif get_user_by_username(username):
        error = "Someone already has that username."
    elif not full_name.strip():
        error = "Fill in your name."
    elif "@" not in email or "." not in email.split("@")[-1]:
        error = "That email doesn't look right."
    elif phone.strip() and not valid_phone(phone):
        error = "That phone number doesn't look right."
    elif len(password) < MIN_PASSWORD:
        error = "Pick a password."
    if error:
        return render(request, "signup.html", {"error": error, "need_code": bool(club_code()), "form": form}, status_code=400)

    with SessionLocal() as session:
        user = User(
            username=username,
            display_name=full_name.strip()[:60],
            full_name=full_name.strip()[:120],
            email=email.strip()[:254],
            phone=phone.strip()[:40],
            password_hash=hash_password(password),
        )
        session.add(user)
        session.commit()
    log_in_user(request, user)
    return RedirectResponse("/welcome", status_code=303)


@router.post("/logout")
def logout(request: Request):
    log_out_user(request)
    return RedirectResponse("/login", status_code=303)


# --- Settings ---------------------------------------------------------------

@router.get("/settings")
def settings_page(request: Request, user: User = Depends(me)):
    return render(request, "settings.html", {"saved": request.query_params.get("saved")})


@router.post("/settings")
def settings_save(
    request: Request,
    user: User = Depends(me),
    full_name: str = Form(""),
    tagline: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
):
    if not full_name.strip() or "@" not in email:
        return render(request, "settings.html", {"error": "Your name and a real email, please."}, status_code=400)
    if phone.strip() and not valid_phone(phone):
        return render(request, "settings.html", {"error": "That phone number doesn't look right."}, status_code=400)
    with SessionLocal() as session:
        u = session.get(User, user.id)
        u.display_name = full_name.strip()[:60]
        u.full_name = full_name.strip()[:120]
        u.tagline = tagline.strip()[:140]
        u.email = email.strip()[:254]
        u.phone = phone.strip()[:40]
        session.commit()
    return RedirectResponse("/settings?saved=profile", status_code=303)


@router.post("/settings/avatar")
async def settings_avatar(request: Request, user: User = Depends(me), photo: UploadFile = File(None), remove: str = Form("")):
    onboarding = request.query_params.get("next") == "/welcome/photo"
    own = user.training == "own"
    page, ctx = ("welcome/photo.html", {"step": 2 if own else 4, "total": 2 if own else 4}) if onboarding else ("settings.html", {})
    with SessionLocal() as session:
        u = session.get(User, user.id)
        if remove:
            u.avatar, u.has_avatar = None, False
        else:
            if photo is None or not photo.filename:
                return render(request, page, {**ctx, "error": "Pick a photo first."}, status_code=400)
            try:
                u.avatar, u.has_avatar = avatars.process(await photo.read()), True
            except avatars.AvatarError as exc:
                return render(request, page, {**ctx, "error": str(exc)}, status_code=400)
        u.avatar_version = (u.avatar_version or 0) + 1
        session.commit()
    return RedirectResponse("/welcome/photo" if onboarding else "/settings?saved=photo", status_code=303)


@router.post("/settings/password")
def settings_password(request: Request, user: User = Depends(me), current: str = Form(""), new: str = Form("")):
    if not verify_password(current, user.password_hash):
        return render(request, "settings.html", {"error": "Current password is wrong."}, status_code=400)
    if len(new) < MIN_PASSWORD:
        return render(request, "settings.html", {"error": "Type a new password."}, status_code=400)
    with SessionLocal() as session:
        session.get(User, user.id).password_hash = hash_password(new)
        session.commit()
    return RedirectResponse("/settings?saved=password", status_code=303)


@router.get("/avatars/{user_id}.jpg")
def avatar(user_id: int):
    with SessionLocal() as session:
        u = session.scalar(select(User).options(undefer(User.avatar)).where(User.id == user_id))
        if not u or not u.avatar:
            raise HTTPException(404)
        # URLs carry ?v=avatar_version, so a new photo is a new URL: cache hard.
        return Response(u.avatar, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=31536000, immutable"})
