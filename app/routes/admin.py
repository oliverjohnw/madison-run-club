"""Admin: members (with private name/email), the schedule, locking the race date."""

import secrets
from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import func, select
from starlette.responses import RedirectResponse

from app import club, quiz
from app.auth import hash_password
from app.db import SessionLocal
from app.models import ClubSetting, Meetup, Run, User
from app.routes.deps import admin_only
from app.routes.race import tally
from app.templating import render

router = APIRouter(prefix="/admin")


@router.get("")
def admin_home(request: Request, user: User = Depends(admin_only)):
    with SessionLocal() as session:
        members = list(session.scalars(select(User).order_by(User.created_at)))
        run_counts = dict(session.execute(select(Run.user_id, func.count(Run.id)).group_by(Run.user_id)).all())
        meetups = list(session.scalars(select(Meetup).where(Meetup.date >= club.today()).order_by(Meetup.date)))
        votes = tally(session)
        logs = list(session.scalars(select(Run).order_by(Run.date.desc(), Run.id.desc()).limit(200)))
    return render(request, "admin/index.html", {
        "members": members, "run_counts": run_counts, "meetups": meetups, "votes": votes,
        "locked": club.locked_race_date(), "plans": club.plans_config(),
        "quiz": {m.id: quiz.describe(m.quiz) for m in members},
        # One-time display of a freshly reset password (kept out of the URL so it never lands in logs).
        "temp": request.session.pop("temp_password", None),
        "saved": request.session.pop("admin_saved", None),
        "logs": logs, "members_by_id": {m.id: m for m in members},
        "log_saved": request.session.pop("log_saved", None),
    })


# --- Meetups ----------------------------------------------------------------

def _meetup_form(request: Request, m: Meetup | None, error: str | None = None, status: int = 200):
    return render(request, "admin/meetup_form.html", {"m": m, "error": error}, status_code=status)


@router.get("/meetups/new")
def meetup_new(request: Request, user: User = Depends(admin_only)):
    return _meetup_form(request, None)


@router.get("/meetups/{meetup_id}")
def meetup_edit(request: Request, meetup_id: int, user: User = Depends(admin_only)):
    with SessionLocal() as session:
        m = session.get(Meetup, meetup_id)
    if m is None:
        raise HTTPException(404)
    return _meetup_form(request, m)


async def _apply(request: Request, m: Meetup) -> str | None:
    form = await request.form()
    try:
        m.date = date.fromisoformat(form.get("date", ""))
    except ValueError:
        return "Pick a date."
    m.title = form.get("title", "").strip()[:120]
    if not m.title:
        return "Give it a title."
    m.time_label = form.get("time_label", "").strip()[:20]
    m.location = form.get("location", "").strip()[:200]
    m.details = form.get("details", "").strip()[:4000]
    m.slot = form.get("slot") if form.get("slot") in ("club", "race", "other") else "club"
    m.is_event = form.get("is_event") == "1"
    m.canceled = form.get("canceled") == "1"
    return None


@router.post("/meetups/new")
async def meetup_create(request: Request, user: User = Depends(admin_only)):
    m = Meetup()
    error = await _apply(request, m)
    if error:
        return _meetup_form(request, None, error, 400)
    with SessionLocal() as session:
        session.add(m)
        session.commit()
        return RedirectResponse(f"/meetups/{m.id}", status_code=303)


@router.post("/meetups/{meetup_id}")
async def meetup_update(request: Request, meetup_id: int, user: User = Depends(admin_only)):
    with SessionLocal() as session:
        m = session.get(Meetup, meetup_id)
        if m is None:
            raise HTTPException(404)
        error = await _apply(request, m)
        if error:
            session.rollback()
            return _meetup_form(request, session.get(Meetup, meetup_id), error, 400)
        session.commit()
    return RedirectResponse(f"/meetups/{meetup_id}", status_code=303)


@router.post("/meetups/{meetup_id}/quick")
def meetup_quick(request: Request, meetup_id: int, user: User = Depends(admin_only),
                 date_: str = Form("", alias="date"), time_label: str = Form(""), location: str = Form(""),
                 details: str = Form("")):
    """The inline date / time / place / description editor on the Admin page."""
    with SessionLocal() as session:
        m = session.get(Meetup, meetup_id)
        if m is None:
            raise HTTPException(404)
        try:
            m.date = date.fromisoformat(date_)
        except ValueError:
            pass  # keep the old date rather than erroring the whole row
        m.time_label = time_label.strip()[:20]
        m.location = location.strip()[:200]
        m.details = details.strip()[:4000]
        session.commit()
        request.session["admin_saved"] = f"{m.title} ({m.date:%b} {m.date.day})"
    return RedirectResponse("/admin#schedule", status_code=303)


@router.post("/meetups/{meetup_id}/delete")
def meetup_delete(request: Request, meetup_id: int, user: User = Depends(admin_only)):
    with SessionLocal() as session:
        m = session.get(Meetup, meetup_id)
        if m:
            session.delete(m)
            session.commit()
    return RedirectResponse("/schedule", status_code=303)


# --- Race date --------------------------------------------------------------

@router.post("/race")
def race_lock(request: Request, user: User = Depends(admin_only), choice: str = Form("")):
    """Lock a date (adds the race to the schedule) or unlock (choice empty)."""
    with SessionLocal() as session:
        row = session.get(ClubSetting, "race_date") or ClubSetting(key="race_date")
        session.add(row)
        race = session.scalar(select(Meetup).where(Meetup.slot == "race"))
        try:
            d = date.fromisoformat(choice)
        except ValueError:
            d = None
        if d in club.race_options():
            row.value = d.isoformat()
            cfg = club.config()["race"]
            if race is None:
                race = Meetup(slot="race", title="The Moosehead 5K", time_label=cfg["time_label"], location=cfg["location"],
                              details="3.1 miles. Run it, jog it, walk some of it. Then we celebrate.")
                session.add(race)
            race.date = d
        else:
            row.value = ""
            if race:
                session.delete(race)
        session.commit()
    return RedirectResponse("/admin#race", status_code=303)


# --- Logs -------------------------------------------------------------------

@router.post("/runs/{run_id}/activity")
def run_activity(request: Request, run_id: int, user: User = Depends(admin_only), activity: str = Form("")):
    """One-click Run / Walk / Bike fix for any member's log (e.g. walks logged before Walk existed).
    For anything else (distance, time, notes), use Edit on the log itself."""
    if activity not in ("run", "walk", "bike"):
        raise HTTPException(400)
    with SessionLocal() as session:
        run = session.get(Run, run_id)
        if run is None:
            raise HTTPException(404)
        run.activity = activity
        session.commit()
        owner = session.get(User, run.user_id)
        request.session["log_saved"] = f"{owner.name if owner else 'That'}'s {run.date:%b} {run.date.day} log is now a {activity}."
    return RedirectResponse("/admin#logs", status_code=303)


# --- Members ----------------------------------------------------------------

@router.post("/members/{member_id}/password")
def reset_password(request: Request, member_id: int, user: User = Depends(admin_only)):
    temp = "-".join(secrets.choice(["moose", "antler", "trail", "lake", "pine", "stride", "mile", "loop"]) for _ in range(2)) \
        + str(secrets.randbelow(90) + 10)
    with SessionLocal() as session:
        m = session.get(User, member_id)
        if m is None:
            raise HTTPException(404)
        m.password_hash = hash_password(temp)
        session.commit()
        name = m.username
    request.session["temp_password"] = [name, temp]
    return RedirectResponse("/admin#members", status_code=303)


@router.post("/members/{member_id}/delete")
def delete_member(request: Request, member_id: int, user: User = Depends(admin_only)):
    if member_id == user.id:
        raise HTTPException(403)
    with SessionLocal() as session:
        m = session.get(User, member_id)
        if m:
            session.delete(m)
            session.commit()
    return RedirectResponse("/admin#members", status_code=303)
