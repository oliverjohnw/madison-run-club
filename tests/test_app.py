from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import Meetup, Run


def client():
    return TestClient(app)


def signup(c, username="jen", **extra):
    data = {"username": username, "full_name": "Jen Runner", "email": f"{username}@secret-mail.example",
            "phone": "608-555-0199", "password": "pw", "code": "moose", **extra}
    return c.post("/signup", data=data)


def plan_path(c, quiz=("8-930", "2-3", "1-2"), goal=None):
    c.post("/welcome", data={"training": "plan"})
    c.post("/welcome/quiz", data=dict(zip(("mile", "longest", "often"), quiz)))
    return c.post("/welcome/goal", data=goal or {"choice": "accept"})


def first_club_run() -> Meetup:
    with SessionLocal() as s:
        return s.scalars(select(Meetup).where(Meetup.slot == "club").order_by(Meetup.date)).first()


def test_logged_out_redirects():
    with client() as c:
        r = c.get("/", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login"
        assert c.get("/healthz").json() == {"ok": True}


def test_signup_needs_code():
    with client() as c:
        r = signup(c, "nocode", code="wrong")
        assert r.status_code == 400 and "club code" in r.text


def test_schedule_is_the_five_club_runs():
    dates = [m.date.isoformat() for m in _all_club_runs()]
    assert dates == ["2026-10-22", "2026-10-31", "2026-11-04", "2026-11-11", "2026-11-19"]


def _all_club_runs():
    with TestClient(app):  # startup seeds the schedule
        with SessionLocal() as s:
            return list(s.scalars(select(Meetup).where(Meetup.slot == "club").order_by(Meetup.date)))


def test_plan_member_flow():
    with client() as c:
        r = signup(c)
        assert r.url.path == "/welcome" and "How do you want to train?" in r.text
        assert c.get("/schedule", follow_redirects=False).headers["location"] == "/welcome"  # setup first

        r = c.post("/welcome", data={"training": "plan"})
        assert r.url.path == "/welcome/quiz" and "Step 2 of 4" in r.text
        r = c.post("/welcome/quiz", data={"mile": "8-930", "longest": "2-3", "often": "1-2"})
        assert r.url.path == "/welcome/goal" and "Suggested 5K goal" in r.text
        r = c.post("/welcome/goal", data={"choice": "custom", "pace": "8:00"})
        assert r.url.path == "/welcome/photo" and "Step 4 of 4" in r.text
        r = c.post("/welcome/done")
        assert r.url.path == "/plan" and "Push It" in r.text and "8:00/mi" in r.text
        assert "<li>10 min easy" in r.text  # workouts render one piece per line
        assert "Club run · Thu Oct 22" in r.text  # week 2's club workout is tied to that week's meetup

        home = c.get("/").text
        assert "Hey, Jen" in home and 'href="/plan#week-2"' in home  # "Check out this week's workout" on the next club run

        m = first_club_run()
        r = c.post(f"/meetups/{m.id}/rsvp", data={"status": "in"})
        assert r.status_code == 200 and 'aria-pressed="true"' in r.text
        meetup_page = c.get(f"/meetups/{m.id}").text
        assert "What everyone" in meetup_page and "Push It" in meetup_page

        r = c.post("/log", data={"date": "2026-10-22", "distance": "3.2", "time": "27:12", "meetup_id": str(m.id), "effort": "3"})
        assert "/runs/" in str(r.url) and "Logged." in r.text and "8:30" in r.text
        assert c.post("/log", data={"date": "2026-10-20", "distance": "3", "time": "2:00"}).status_code == 400

        for path in ["/feed", "/club", "/race", "/u/jen", "/plan?show=send", "/settings", "/log", "/schedule"]:
            assert c.get(path).status_code == 200, path

        r = c.post("/race/vote", data={"choice": "2026-11-22"})
        assert r.status_code == 200 and "Your vote" in r.text

        # Email and phone stay private from non-admins; full name is the public name.
        profile = c.get("/u/jen").text
        assert "Jen Runner" in profile and "secret-mail" not in profile and "0199" not in profile
        assert c.get("/admin").status_code == 403

        # Dropping the plan.
        r = c.post("/plan/own")
        assert "Your own thing" in r.text and "Get a recommended plan" in r.text


def test_own_workouts_flow():
    with client() as c:
        signup(c, "freestyle")
        r = c.post("/welcome", data={"training": "own"})
        assert r.url.path == "/welcome/photo" and "Step 2 of 2" in r.text
        r = c.post("/welcome/done")
        assert r.url.path == "/" and "Doing your own thing" in r.text
        assert "Your own thing" in c.get("/plan").text
        # Picking a plan later from the plan page.
        r = c.post("/plan/goal", data={"choice": "plan", "plan": "chase"})
        assert "Chase It" in r.text and "Stop following a plan" in r.text


def test_admin_private_info_quick_edit_and_kudos():
    with client() as c:
        signup(c, "kudosgiver")
        plan_path(c, ("idk", "none", "0"))
        c.post("/welcome/done")
        with SessionLocal() as s:
            run = s.scalars(select(Run)).first()
        if run:
            assert "1 antler up" in c.post(f"/runs/{run.id}/kudos?next=/feed").text
        c.post("/logout")

        c.post("/login", data={"username": "john", "password": "admin-password-123"})
        plan_path(c, goal={"choice": "plan", "plan": "cruise"})
        assert "Cruise It" in c.post("/welcome/done").text
        admin = c.get("/admin")
        assert admin.status_code == 200 and "jen@secret-mail.example" in admin.text and "608-555-0199" in admin.text

        m = first_club_run()
        r = c.post(f"/admin/meetups/{m.id}/quick", data={"date": "2026-10-23", "time_label": "6:30 PM", "location": "Olin Park", "details": "Meet by the pavilion."})
        assert "Saved Club Run (Oct 23)" in r.text
        with SessionLocal() as s:
            moved = s.get(Meetup, m.id)
        assert moved.date.isoformat() == "2026-10-23" and moved.location == "Olin Park" and moved.time_label == "6:30 PM"
        assert moved.details == "Meet by the pavilion."

        r = c.post("/admin/race", data={"choice": "2026-11-23"})
        assert "Lock in" in r.text
        assert "The Moosehead 5K" in c.get("/schedule").text


def test_photo_step_upload():
    buf = BytesIO()
    Image.new("RGB", (900, 600), "#1f4a37").save(buf, "JPEG")
    with client() as c:
        signup(c, "photo.person")
        plan_path(c, ("7-8", "2-3", "1-2"))
        r = c.post("/settings/avatar?next=/welcome/photo", files={"photo": ("me.jpg", buf.getvalue(), "image/jpeg")})
        assert r.url.path == "/welcome/photo" and "Looking good." in r.text
        bad = c.post("/settings/avatar?next=/welcome/photo", files={"photo": ("x.jpg", b"not an image", "image/jpeg")})
        assert bad.status_code == 400 and "Step 4 of 4" in bad.text
        assert c.post("/welcome/done").url.path == "/plan"


def test_deleted_account_cookie_goes_to_login():
    from app.models import User

    with client() as c:
        signup(c, "gone.soon")
        with SessionLocal() as s:
            s.delete(s.scalars(select(User).where(User.username == "gone.soon")).one())
            s.commit()
        assert c.get("/").url.path == "/login"
        r = c.get("/", follow_redirects=False)  # cookie was cleared: straight to login, no loop
        assert r.status_code == 303 and r.headers["location"] == "/login"


def test_club_code_guessing_is_throttled():
    from app import auth

    with client() as c:
        for _ in range(auth.MAX_FAILURES):
            assert signup(c, "guesser", code="nope").status_code == 400
        assert signup(c, "guesser", code="moose").status_code == 429
        auth._failures.clear()
