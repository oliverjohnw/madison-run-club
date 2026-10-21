"""Logging runs, the activity feed, and kudos (here: "antlers up")."""

from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from starlette.responses import RedirectResponse

from app import club
from app.db import SessionLocal
from app.models import Kudos, Meetup, Rsvp, Run, User
from app.routes.deps import back, me, users_by_id
from app.templating import render

router = APIRouter()


def feed_items(session: Session, viewer: User, users: dict[int, User], limit: int = 30,
               only_user: int | None = None) -> list[dict]:
    q = select(Run).order_by(Run.date.desc(), Run.id.desc()).limit(limit)
    if only_user:
        q = q.where(Run.user_id == only_user)
    runs = list(session.scalars(q))
    if not runs:
        return []
    ids = [r.id for r in runs]
    kudos = defaultdict(list)
    for k in session.scalars(select(Kudos).where(Kudos.run_id.in_(ids)).order_by(Kudos.id)):
        kudos[k.run_id].append(k.user_id)
    meetup_ids = {r.meetup_id for r in runs if r.meetup_id}
    meetups = {m.id: m for m in session.scalars(select(Meetup).where(Meetup.id.in_(meetup_ids)))} if meetup_ids else {}
    crews = defaultdict(set)
    if meetup_ids:
        for uid, mid in session.execute(select(Run.user_id, Run.meetup_id).where(Run.meetup_id.in_(meetup_ids))):
            crews[mid].add(uid)
    items = []
    for r in runs:
        items.append({
            "run": r,
            "user": users.get(r.user_id),
            "meetup": meetups.get(r.meetup_id),
            "kudos": [users[u] for u in kudos[r.id] if u in users],
            "mine_kudos": viewer.id in kudos[r.id],
            "crew": [users[u] for u in crews.get(r.meetup_id, ()) if u != r.user_id and u in users],
        })
    return items


@router.get("/feed")
def feed(request: Request, user: User = Depends(me)):
    with SessionLocal() as session:
        users = users_by_id(session)
        items = feed_items(session, user, users, limit=60)
    return render(request, "feed.html", {"items": items})


# --- Log / edit -------------------------------------------------------------

def meetup_choices(session: Session, around: date) -> list[Meetup]:
    return list(session.scalars(
        select(Meetup).where(Meetup.date >= around - timedelta(days=10), Meetup.date <= around + timedelta(days=1),
                             Meetup.canceled.is_(False)).order_by(Meetup.date.desc())))


def _form_ctx(session: Session, run: Run | None, form: dict, error: str | None = None) -> dict:
    return {"run": run, "form": form, "error": error, "choices": meetup_choices(session, club.today())}


@router.get("/log")
def log_page(request: Request, user: User = Depends(me)):
    today = club.today()
    with SessionLocal() as session:
        mid = request.query_params.get("meetup", "")
        if not mid:  # default to today's meetup if they said they were coming
            m = session.scalar(select(Meetup).join(Rsvp, Rsvp.meetup_id == Meetup.id).where(
                Meetup.date == today, Rsvp.user_id == user.id, Rsvp.status == "in"))
            mid = str(m.id) if m else ""
        form = {"date": today.isoformat(), "meetup_id": mid, "effort": "3", "activity": "run"}
        if mid.isdigit() and (m := session.get(Meetup, int(mid))):
            form["date"] = m.date.isoformat()
        return render(request, "run_form.html", _form_ctx(session, None, form))


# Sanity limits per activity: max distance (mi), and fastest / slowest believable pace (sec per mile).
LIMITS = {"run": (60, 150, 3600), "walk": (60, 480, 3600), "bike": (200, 90, 1800)}


def _parse(form: dict) -> tuple[dict | None, str | None]:
    activity = form.get("activity", "run")
    if activity not in LIMITS:
        return None, "Pick Run, Walk or Bike."
    max_mi, fastest, slowest = LIMITS[activity]
    try:
        d = date.fromisoformat(form.get("date", ""))
    except ValueError:
        return None, "Pick a date."
    try:
        dist = float(form.get("distance", "").strip())
    except ValueError:
        return None, "Distance should be a number of miles, like 3.1."
    if not 0.05 <= dist <= max_mi:
        return None, f"Distance should be between 0.05 and {max_mi} miles."
    secs = club.parse_clock(form.get("time", ""))
    if not secs:
        return None, "Time should look like 28:15 (or 1:02:30)."
    if not fastest <= secs / dist <= slowest:
        shown = f"{dist / (secs / 3600):.1f} mph" if activity == "bike" else f"{club.clock(secs / dist)}/mi"
        return None, f"That's {shown}. Double-check the distance and time (and Run / Walk / Bike)?"
    if d > club.today() + timedelta(days=1):
        return None, "That date's in the future."
    mid = form.get("meetup_id", "")
    effort = form.get("effort", "")
    return {
        "date": d, "activity": activity, "distance_mi": round(dist, 2), "duration_sec": secs,
        "meetup_id": int(mid) if mid.isdigit() else None,
        "effort": int(effort) if effort in ("1", "2", "3", "4", "5") else None,
        "title": form.get("title", "").strip()[:120],
        "notes": form.get("notes", "").strip()[:2000],
    }, None


def _default_title(session: Session, values: dict) -> str:
    if values["meetup_id"] and (m := session.get(Meetup, values["meetup_id"])):
        return m.title
    noun = {"run": "miles, solo", "walk": "walk", "bike": "ride"}[values["activity"]]
    return f"{values['date']:%A} {noun}"


@router.post("/log")
async def log_submit(request: Request, user: User = Depends(me)):
    form = dict(await request.form())
    values, error = _parse(form)
    with SessionLocal() as session:
        if error:
            return render(request, "run_form.html", _form_ctx(session, None, form, error), status_code=400)
        values["title"] = values["title"] or _default_title(session, values)
        run = Run(user_id=user.id, **values)
        session.add(run)
        session.commit()
        run_id = run.id
    return RedirectResponse(f"/runs/{run_id}?new=1", status_code=303)


def _own_run(session: Session, run_id: int, user: User) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404)
    if run.user_id != user.id and not user.is_admin:
        raise HTTPException(403)
    return run


@router.get("/runs/{run_id}")
def run_page(request: Request, run_id: int, user: User = Depends(me)):
    with SessionLocal() as session:
        run = session.get(Run, run_id)
        if run is None:
            raise HTTPException(404)
        users = users_by_id(session)
        item = next(i for i in feed_items(session, user, users, limit=1000, only_user=run.user_id) if i["run"].id == run_id)
        theirs = list(session.scalars(select(Run).where(Run.user_id == run.user_id)))
    # Little context numbers for the detail page.
    earlier = [r for r in theirs if (r.date, r.id) < (run.date, run.id)]
    same = [r for r in earlier if r.activity == run.activity]  # "longest walk yet" compares walks with walks
    ctx = {
        "item": item,
        "longest_yet": bool(same) and run.distance_mi > max(r.distance_mi for r in same),
        "fastest_yet": run.distance_mi >= 1 and bool(same) and run.pace_sec < min(
            [r.pace_sec for r in same if r.distance_mi >= 1] + [99999]),
        "nth": len(same) + 1,
        "pred_5k": club.riegel_5k(run.distance_mi, run.duration_sec) if run.distance_mi >= 1 and run.activity == "run" else None,
        "new": request.query_params.get("new") == "1",
    }
    return render(request, "run.html", ctx)


@router.get("/runs/{run_id}/edit")
def edit_page(request: Request, run_id: int, user: User = Depends(me)):
    with SessionLocal() as session:
        run = _own_run(session, run_id, user)
        form = {"date": run.date.isoformat(), "activity": run.activity, "distance": f"{run.distance_mi:g}", "time": club.clock(run.duration_sec),
                "meetup_id": str(run.meetup_id or ""), "effort": str(run.effort or ""), "title": run.title, "notes": run.notes}
        return render(request, "run_form.html", _form_ctx(session, run, form))


@router.post("/runs/{run_id}/edit")
async def edit_submit(request: Request, run_id: int, user: User = Depends(me)):
    form = dict(await request.form())
    values, error = _parse(form)
    with SessionLocal() as session:
        run = _own_run(session, run_id, user)
        if error:
            return render(request, "run_form.html", _form_ctx(session, run, form, error), status_code=400)
        values["title"] = values["title"] or _default_title(session, values)
        for k, v in values.items():
            setattr(run, k, v)
        session.commit()
    return RedirectResponse(f"/runs/{run_id}", status_code=303)


@router.post("/runs/{run_id}/delete")
def delete_run(request: Request, run_id: int, user: User = Depends(me)):
    with SessionLocal() as session:
        session.delete(_own_run(session, run_id, user))
        session.commit()
    return RedirectResponse("/feed", status_code=303)


@router.post("/runs/{run_id}/kudos")
def kudos(request: Request, run_id: int, user: User = Depends(me)):
    with SessionLocal() as session:
        run = session.get(Run, run_id)
        if run is None:
            raise HTTPException(404)
        existing = session.scalar(select(Kudos).where(Kudos.run_id == run_id, Kudos.user_id == user.id))
        if existing:
            session.execute(delete(Kudos).where(Kudos.id == existing.id))
        elif run.user_id != user.id:
            session.add(Kudos(run_id=run_id, user_id=user.id))
        session.commit()
    return back(request, "/feed")
