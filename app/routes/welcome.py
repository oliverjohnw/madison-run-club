"""
New-member setup.

    /welcome         plan or your own thing?
      plan  ->  /welcome/quiz  ->  /welcome/goal  ->  /welcome/photo
      own   ->                                        /welcome/photo
    /welcome/done    marks them set up and lands them on /plan

The quiz and goal pages also work for members who are already set up (e.g. someone
who chose "my own thing" and later wants a plan); they finish on /plan instead.
"""

from fastapi import APIRouter, Depends, Form, Request
from starlette.responses import RedirectResponse

from app import club, quiz
from app.db import SessionLocal
from app.models import User
from app.routes.deps import me
from app.templating import render

router = APIRouter()


def _steps(user: User, step: int) -> dict:
    """Step counter for the progress bar: 4 steps on the plan path, 2 on the own path."""
    if user.training == "own":
        return {"step": 1 if step == 1 else 2, "total": 2}
    return {"step": step, "total": 4}


@router.get("/welcome")
def choose_page(request: Request, user: User = Depends(me)):
    return render(request, "welcome/choose.html", _steps(user, 1))


@router.post("/welcome")
def choose_submit(request: Request, user: User = Depends(me), training: str = Form("")):
    if training not in ("plan", "own"):
        return render(request, "welcome/choose.html", {**_steps(user, 1), "error": "Pick one."}, status_code=400)
    with SessionLocal() as session:
        u = session.get(User, user.id)
        u.training = training
        if training == "own":
            u.plan_key, u.goal_pace_sec = "", None
        session.commit()
    if training == "own":
        return RedirectResponse("/welcome/photo" if not user.onboarded else "/plan", status_code=303)
    return RedirectResponse("/welcome/quiz", status_code=303)


@router.get("/welcome/quiz")
def quiz_page(request: Request, user: User = Depends(me)):
    return render(request, "welcome/quiz.html", {**_steps(user, 2), "questions": quiz.QUESTIONS, "answers": quiz.decode(user.quiz)})


@router.post("/welcome/quiz")
async def quiz_submit(request: Request, user: User = Depends(me)):
    form = await request.form()
    answers = {q["key"]: form.get(q["key"], "") for q in quiz.QUESTIONS}
    if not quiz.valid(answers):
        return render(request, "welcome/quiz.html", {**_steps(user, 2), "questions": quiz.QUESTIONS, "answers": answers,
                                                     "error": "Answer all three (any answer is fine)."}, status_code=400)
    with SessionLocal() as session:
        session.get(User, user.id).quiz = quiz.encode(answers)
        session.commit()
    return RedirectResponse("/welcome/goal", status_code=303)


@router.get("/welcome/goal")
def goal_page(request: Request, user: User = Depends(me)):
    answers = quiz.decode(user.quiz)
    if not quiz.valid(answers):
        return RedirectResponse("/welcome/quiz", status_code=303)
    return render(request, "welcome/goal.html", _goal_ctx(user, answers))


def _goal_ctx(user: User, answers: dict, **extra) -> dict:
    s = quiz.suggest(answers)
    plans = club.plans_config()
    return {**_steps(user, 3), "s": s, "plan": plans[s.plan_key], "plans": plans, **extra}


@router.post("/welcome/goal")
def goal_submit(request: Request, user: User = Depends(me), choice: str = Form(""), pace: str = Form(""), plan: str = Form("")):
    error = save_goal(user, choice, pace, quiz.decode(user.quiz), plan)
    if error:
        return render(request, "welcome/goal.html", _goal_ctx(user, quiz.decode(user.quiz), error=error, pace=pace), status_code=400)
    return RedirectResponse("/plan" if user.onboarded else "/welcome/photo", status_code=303)


def save_goal(user: User, choice: str, pace: str, answers: dict, plan: str = "") -> str | None:
    """Shared with the Plan page. choice = accept | finish | custom | plan (pick a plan, use its anchor pace).
    Saving a goal also means they're following a plan."""
    plans = club.plans_config()
    plan_key = None
    if choice == "accept" and quiz.valid(answers):
        goal = quiz.suggest(answers).pace_sec
    elif choice == "finish":
        goal = None
    elif choice == "plan" and plan in plans:
        goal, plan_key = club.anchor_pace(plans[plan]), plan
    elif choice == "custom":
        goal = club.parse_clock(pace)
        if goal is None or not 240 <= goal <= 1200:
            return "Type a pace like 8:30 (minutes:seconds per mile)."
    else:
        return "Pick one."
    with SessionLocal() as session:
        u = session.get(User, user.id)
        u.training = "plan"
        u.goal_pace_sec = goal
        u.plan_key = plan_key or club.plan_for_pace(goal)
        session.commit()
    return None


def _ready(user: User) -> bool:
    return user.training == "own" or (user.training == "plan" and bool(user.plan_key))


@router.get("/welcome/photo")
def photo_page(request: Request, user: User = Depends(me)):
    if not _ready(user):
        return RedirectResponse("/welcome", status_code=303)
    return render(request, "welcome/photo.html", _steps(user, 4))


@router.post("/welcome/done")
def done(request: Request, user: User = Depends(me)):
    if not _ready(user):
        return RedirectResponse("/welcome", status_code=303)
    with SessionLocal() as session:
        session.get(User, user.id).onboarded = True
        session.commit()
    request.session["setup"] = False
    return RedirectResponse("/plan?fresh=1" if user.training == "plan" else "/?fresh=1", status_code=303)
