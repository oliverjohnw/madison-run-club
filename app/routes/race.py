"""Race day vote. Members tick every day that works for them; most votes wins."""

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select

from app import club
from app.db import SessionLocal
from app.models import RaceVote, User
from app.routes.deps import back, me, users_by_id
from app.templating import render

router = APIRouter()


def tally(session) -> dict[date, list[User]]:
    users = users_by_id(session)
    out = {d: [] for d in club.race_options()}
    for v in session.scalars(select(RaceVote)):
        if v.choice in out and v.user_id in users:
            out[v.choice].append(users[v.user_id])
    return out


def my_days(session, user_id: int) -> list[date]:
    return sorted(session.scalars(select(RaceVote.choice).where(RaceVote.user_id == user_id)))


@router.get("/race")
def race_page(request: Request, user: User = Depends(me)):
    with SessionLocal() as session:
        votes = tally(session)
        mine = my_days(session, user.id)
        total = len(users_by_id(session))
        voter_count = len(set(session.scalars(select(RaceVote.user_id))))
    locked = club.locked_race_date()
    return render(request, "race.html", {"votes": votes, "mine": mine, "locked": locked, "total": total,
                                         "voter_count": voter_count, "top": max([len(v) for v in votes.values()] + [1])})


@router.post("/race/vote")
def vote(request: Request, user: User = Depends(me), choice: str = Form("")):
    try:
        d = date.fromisoformat(choice)
    except ValueError:
        d = None
    if d in club.race_options() and not club.locked_race_date():
        with SessionLocal() as session:  # each day toggles on/off independently
            row = session.scalar(select(RaceVote).where(RaceVote.user_id == user.id, RaceVote.choice == d))
            if row:
                session.delete(row)
            else:
                session.add(RaceVote(user_id=user.id, choice=d))
            session.commit()
    return back(request, "/race")
