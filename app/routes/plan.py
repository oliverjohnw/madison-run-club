"""Your training plan (or browsing them if you do your own thing), and changing it."""

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from starlette.responses import RedirectResponse

from app import club, quiz
from app.db import SessionLocal
from app.models import Meetup, User
from app.routes.deps import me
from app.routes.schedule import club_meetups_by_week
from app.routes.welcome import save_goal
from app.templating import render

router = APIRouter()


@router.get("/plan")
def plan_page(request: Request, user: User = Depends(me)):
    plans = club.plans_config()
    own_key = user.plan_key if user.follows_plan else None
    key = request.query_params.get("show") or own_key or next(iter(plans))
    if key not in plans:
        key = own_key or next(iter(plans))
    mine = key == own_key
    goal = user.goal_pace_sec if mine else None
    with SessionLocal() as session:
        week_meetups = club_meetups_by_week(session.scalars(select(Meetup)))
    answers = quiz.decode(user.quiz)
    weeks = club.plan_weeks(key, goal)
    # Weeks with no club run (e.g. week 1): point at the next one so it's obvious it's a solo week.
    next_club = {w["n"]: next((week_meetups[n] for n in sorted(week_meetups) if n > w["n"]), None)
                 for w in weeks if w["n"] not in week_meetups}
    first_club = week_meetups[min(week_meetups)] if week_meetups else None
    return render(request, "plan.html", {
        "plans": plans, "key": key, "plan": plans[key], "mine": mine,
        "weeks": weeks,
        "week_meetups": week_meetups,
        "next_club": next_club,
        "first_club": first_club,
        "zones": club.zones(goal) if goal else None,
        "goal_5k": club.clock(club.five_k_time(goal)) if goal else None,
        "week_n": club.week_number(club.today()),
        "fresh": request.query_params.get("fresh") == "1",
        "suggestion": quiz.suggest(answers) if quiz.valid(answers) else None,
        "race_dates": club.race_options(),
    })


@router.post("/plan/goal")
def plan_goal(request: Request, user: User = Depends(me), choice: str = Form(""), pace: str = Form(""), plan: str = Form("")):
    error = save_goal(user, choice, pace, quiz.decode(user.quiz), plan)
    return RedirectResponse("/plan" + ("?err=1" if error else ""), status_code=303)


@router.post("/plan/own")
def plan_own(request: Request, user: User = Depends(me)):
    with SessionLocal() as session:
        u = session.get(User, user.id)
        u.training, u.plan_key, u.goal_pace_sec = "own", "", None
        session.commit()
    return RedirectResponse("/plan", status_code=303)
