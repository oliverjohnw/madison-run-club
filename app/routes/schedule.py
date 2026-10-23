"""The schedule, meetup pages, and RSVPs."""

from collections import defaultdict

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import club
from app.db import SessionLocal
from app.models import Meetup, MeetupPhoto, Rsvp, Run, User
from app.routes.deps import back, me, users_by_id
from app.routes.photos import can_add_photos
from app.templating import render

router = APIRouter()
STATUSES = ("in", "solo", "out")


def rsvp_map(session: Session, meetup_ids: list[int]) -> dict[int, dict]:
    """{meetup_id: {"in": [user_id...], "solo": [...], "out": [...], "by_user": {user_id: status}, "photos": n}}"""
    out: dict[int, dict] = defaultdict(lambda: {"in": [], "solo": [], "out": [], "by_user": {}, "photos": 0})
    if meetup_ids:
        for r in session.scalars(select(Rsvp).where(Rsvp.meetup_id.in_(meetup_ids)).order_by(Rsvp.updated_at)):
            out[r.meetup_id][r.status].append(r.user_id)
            out[r.meetup_id]["by_user"][r.user_id] = r.status
        counts = session.execute(select(MeetupPhoto.meetup_id, func.count(MeetupPhoto.id))
                                 .where(MeetupPhoto.meetup_id.in_(meetup_ids)).group_by(MeetupPhoto.meetup_id))
        for mid, n in counts:
            out[mid]["photos"] = n
    return out


def club_meetups_by_week(meetups) -> dict[int, Meetup]:
    """{plan week: that week's club run} (first non-canceled one, if a week somehow has two)."""
    out: dict[int, Meetup] = {}
    for m in sorted(meetups, key=lambda m: m.date):
        if m.slot == "club" and not m.canceled:
            out.setdefault(club.week_number(m.date), m)
    return out


@router.get("/schedule")
def schedule(request: Request, user: User = Depends(me)):
    today = club.today()
    show_past = request.query_params.get("past") == "1"
    with SessionLocal() as session:
        q = select(Meetup).order_by(Meetup.date, Meetup.id)
        if not show_past:
            q = q.where(Meetup.date >= today)
        meetups = list(session.scalars(q))
        rsvps = rsvp_map(session, [m.id for m in meetups])
        users = users_by_id(session)
    weeks: dict[int, list[Meetup]] = defaultdict(list)
    for m in meetups:
        weeks[club.week_number(m.date)].append(m)
    n_plan = len(next(iter(club.plans_config().values()))["weeks"])
    return render(request, "schedule.html", {
        "weeks": sorted(weeks.items()), "rsvps": rsvps, "users": users, "show_past": show_past,
        "n_plan": n_plan, "plans": club.plans_config(), "race_locked": club.locked_race_date(),
        "race_dates": club.race_options(),
    })


@router.get("/meetups/{meetup_id}")
def meetup_page(request: Request, meetup_id: int, user: User = Depends(me)):
    with SessionLocal() as session:
        m = session.get(Meetup, meetup_id)
        if m is None:
            raise HTTPException(404)
        rsvps = rsvp_map(session, [m.id])[m.id]
        users = users_by_id(session)
        logged = list(session.scalars(select(Run).where(Run.meetup_id == m.id).order_by(Run.distance_mi.desc())))
        photos = list(session.scalars(select(MeetupPhoto).where(MeetupPhoto.meetup_id == m.id).order_by(MeetupPhoto.id)))
    return render(request, "meetup.html", {
        "m": m, "rsvps": rsvps, "users": users, "logged": logged,
        "week_n": club.week_number(m.date), "photos": photos, "can_add_photos": can_add_photos(m),
        "photo_msg": request.session.pop("photo_msg", None), "photo_ok": request.session.pop("photo_ok", None),
    })


@router.post("/meetups/{meetup_id}/rsvp")
def rsvp(request: Request, meetup_id: int, user: User = Depends(me), status: str = Form("")):
    with SessionLocal() as session:
        m = session.get(Meetup, meetup_id)
        if m is None:
            raise HTTPException(404)
        row = session.scalar(select(Rsvp).where(Rsvp.meetup_id == meetup_id, Rsvp.user_id == user.id))
        if status not in STATUSES or (row and row.status == status):
            if row:  # clicking your current answer again clears it
                session.delete(row)
        elif row:
            row.status = status
        else:
            session.add(Rsvp(meetup_id=meetup_id, user_id=user.id, status=status))
        session.commit()
    return back(request, f"/meetups/{meetup_id}")
