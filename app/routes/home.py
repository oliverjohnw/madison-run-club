"""Home, the club page, and member profiles."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select

from app import club, quiz, stats
from app.db import SessionLocal
from app.models import Meetup, RaceVote, Rsvp, Run, User
from app.routes.deps import me, meetups_by_id, users_by_id
from app.routes.runs import feed_items
from app.routes.schedule import rsvp_map
from app.templating import render

router = APIRouter()


def race_info() -> dict:
    """Locked race date if there is one, else the earliest option (for the countdown)."""
    locked = club.locked_race_date()
    target = locked or min(club.race_options())
    return {"locked": locked, "date": target, "days": (target - club.today()).days}


@router.get("/")
def home(request: Request, user: User = Depends(me)):
    today = club.today()
    with SessionLocal() as session:
        users = users_by_id(session)
        upcoming = list(session.scalars(
            select(Meetup).where(Meetup.date >= today, Meetup.canceled.is_(False)).order_by(Meetup.date).limit(3)))
        rsvps = rsvp_map(session, [m.id for m in upcoming])
        my_runs = list(session.scalars(select(Run).where(Run.user_id == user.id)))
        voted = session.get(RaceVote, user.id)
        feed = feed_items(session, user, users, limit=4)
        week_start = club.week_start(club.week_number(today))
        week_runs = list(session.scalars(select(Run).where(Run.date >= week_start)))
        meetups = meetups_by_id(session)

    s = stats.runner_stats(my_runs, meetups, today)
    club_week = {"miles": sum(r.distance_mi for r in week_runs), "runners": len({r.user_id for r in week_runs})}
    return render(request, "home.html", {
        "upcoming": upcoming, "rsvps": rsvps, "users": users, "s": s, "race": race_info(),
        "fresh": request.query_params.get("fresh") == "1",
        "voted": voted, "feed": feed, "club_week": club_week, "week_n": club.week_number(today),
    })


@router.get("/club")
def club_page(request: Request, user: User = Depends(me)):
    today = club.today()
    with SessionLocal() as session:
        users = users_by_id(session)
        runs = list(session.scalars(select(Run)))
        meetups = meetups_by_id(session)
        rsvps = list(session.scalars(select(Rsvp)))
    member_list = sorted(users.values(), key=lambda u: u.name.lower())
    week_since = club.week_start(club.week_number(today))
    total = sum(r.distance_mi for r in runs)
    return render(request, "club.html", {
        "members": member_list,
        "total_miles": total,
        "total_runs": len(runs),
        "total_seconds": sum(r.duration_sec for r in runs),
        "journey": stats.journey(total),
        "board_week": stats.leaderboard(member_list, runs, meetups, since=week_since),
        "board_all": stats.leaderboard(member_list, runs, meetups),
        "turnout": stats.turnout(sorted(meetups.values(), key=lambda m: m.date), rsvps, runs, today),
        "heat": stats.heatmap(runs, today, scale=max(1.0, len({r.user_id for r in runs}) / 2)),
        "plans": club.plans_config(),
    })


@router.get("/u/{username}")
def profile(request: Request, username: str, user: User = Depends(me)):
    today = club.today()
    with SessionLocal() as session:
        person = session.scalar(select(User).where(func.lower(User.username) == username.lower()))
        if person is None:
            raise HTTPException(404)
        runs = list(session.scalars(select(Run).where(Run.user_id == person.id)))
        meetups = meetups_by_id(session)
        users = users_by_id(session)
        recent = feed_items(session, user, users, limit=6, only_user=person.id)
        going = list(session.scalars(
            select(Meetup).join(Rsvp, Rsvp.meetup_id == Meetup.id)
            .where(Rsvp.user_id == person.id, Rsvp.status == "in", Meetup.date >= today, Meetup.date < today + timedelta(days=14))
            .order_by(Meetup.date)))
    s = stats.runner_stats(runs, meetups, today)
    plans = club.plans_config()
    return render(request, "profile.html", {
        "person": person,
        "s": s,
        "bars": stats.weekly_bars(runs, today),
        "heat": stats.heatmap(runs, today),
        "trend": stats.pace_trend(runs, person.goal_pace_sec),
        "recent": recent,
        "going": going,
        "plan": plans.get(person.plan_key),
        "quiz_answers": quiz.describe(person.quiz) if user.is_admin else None,
        "is_me": person.id == user.id,
    })
