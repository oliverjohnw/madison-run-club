"""The Moosehead 5K: three sessions, come to any or all. RSVPs work like any club run."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from app import club
from app.db import SessionLocal
from app.models import Meetup, User
from app.routes.deps import me, users_by_id
from app.routes.schedule import rsvp_map
from app.templating import render

router = APIRouter()


def race_sessions(session) -> list[Meetup]:
    return list(session.scalars(select(Meetup).where(Meetup.slot == "race").order_by(Meetup.date, Meetup.id)))


@router.get("/race")
def race_page(request: Request, user: User = Depends(me)):
    with SessionLocal() as session:
        sessions = race_sessions(session)
        rsvps = rsvp_map(session, [m.id for m in sessions])
        users = users_by_id(session)
    return render(request, "race.html", {"sessions": sessions, "rsvps": rsvps, "users": users,
                                         "intro": club.config()["race"].get("intro", "")})
