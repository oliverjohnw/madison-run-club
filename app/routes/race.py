"""Race day vote."""

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


@router.get("/race")
def race_page(request: Request, user: User = Depends(me)):
    with SessionLocal() as session:
        votes = tally(session)
        mine = session.get(RaceVote, user.id)
        total = len(users_by_id(session))
    locked = club.locked_race_date()
    return render(request, "race.html", {"votes": votes, "mine": mine.choice if mine else None, "locked": locked,
                                         "total": total, "top": max([len(v) for v in votes.values()] + [1])})


@router.post("/race/vote")
def vote(request: Request, user: User = Depends(me), choice: str = Form("")):
    try:
        d = date.fromisoformat(choice)
    except ValueError:
        d = None
    if d in club.race_options() and not club.locked_race_date():
        with SessionLocal() as session:
            row = session.get(RaceVote, user.id)
            if row:
                row.choice = d
            else:
                session.add(RaceVote(user_id=user.id, choice=d))
            session.commit()
    return back(request, "/race")
