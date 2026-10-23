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
        assert "What everyone" not in meetup_page and 'id="photos"' in meetup_page

        r = c.post("/log", data={"date": "2026-10-22", "distance": "3.2", "time": "27:12", "meetup_id": str(m.id), "effort": "3"})
        assert "/runs/" in str(r.url) and "Logged." in r.text and "8:30" in r.text
        assert c.post("/log", data={"date": "2026-10-20", "distance": "3", "time": "2:00"}).status_code == 400

        for path in ["/feed", "/club", "/race", "/u/jen", "/plan?show=send", "/settings", "/log", "/schedule"]:
            assert c.get(path).status_code == 200, path

        # Race day: several days can be picked, and clicking one again takes it back off.
        c.post("/race/vote", data={"choice": "2026-11-22"})
        r = c.post("/race/vote", data={"choice": "2026-11-23"})
        assert r.status_code == 200 and r.text.count("✓ Works for me") == 2
        r = c.post("/race/vote", data={"choice": "2026-11-23"})
        assert r.text.count("✓ Works for me") == 1
        assert "You picked Sun." in c.get("/").text

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
        assert r.url.path == "/" and "Next up" in r.text
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


def test_home_shows_only_the_next_run_all_day():
    """Conftest pretends it's Thu Oct 22: that day's run is still the one on the home page."""
    with client() as c:
        signup(c, "homebody")
        c.post("/welcome", data={"training": "own"})
        home = c.post("/welcome/done").text
        assert home.count('class="ticket ') == 1
        assert "Wilsons Bar" in home or "Club Run" in home
        assert home.index("Next up") < home.index("Lately")


def test_log_walk_and_bike():
    with client() as c:
        signup(c, "multisport")
        c.post("/welcome", data={"training": "own"})
        c.post("/welcome/done")
        r = c.post("/log", data={"date": "2026-10-21", "activity": "bike", "distance": "18", "time": "1:12:00"})
        assert r.url.path.startswith("/runs/") and "15.0" in r.text and "mph" in r.text and "Wednesday ride" in r.text
        r = c.post("/log", data={"date": "2026-10-21", "activity": "walk", "distance": "2", "time": "38:00"})
        assert "Wednesday walk" in r.text and "19:00" in r.text
        # A 2:00/mi "run" is a typo; the same speed (30 mph) on a bike is fine.
        assert c.post("/log", data={"date": "2026-10-21", "activity": "run", "distance": "5", "time": "10:00"}).status_code == 400
        assert c.post("/log", data={"date": "2026-10-21", "activity": "bike", "distance": "5", "time": "10:00"}).url.path.startswith("/runs/")
        assert c.post("/log", data={"date": "2026-10-21", "activity": "jog", "distance": "1", "time": "10:00"}).status_code == 400
        home = c.get("/").text
        assert "23.0" in home and "2.0" in home  # bike (18 + 5) and walk miles in the You card


def _jpeg_bytes(color="#df5420", size=(1200, 900)):
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


def test_admin_can_fix_anyones_log():
    with client() as c:
        signup(c, "oldwalker")
        c.post("/welcome", data={"training": "own"})
        c.post("/welcome/done")
        r = c.post("/log", data={"date": "2026-10-21", "activity": "run", "distance": "2", "time": "36:00"})
        run_id = int(r.url.path.split("/")[2])
        assert "Edit (admin)" not in r.text
        assert c.post(f"/admin/runs/{run_id}/activity", data={"activity": "walk"}).status_code == 403  # not admin
        c.post("/logout")

        c.post("/login", data={"username": "john", "password": "admin-password-123"})
        c.post("/welcome", data={"training": "own"})  # finish admin setup if this test runs first
        c.post("/welcome/done")
        assert "Edit (admin)" in c.get(f"/runs/{run_id}").text
        r = c.post(f"/admin/runs/{run_id}/activity", data={"activity": "walk"})
        assert "log is now a walk" in r.text
        with SessionLocal() as s:
            run = s.get(Run, run_id)
            assert run.activity == "walk" and run.user_id != 0
        # Full edit as admin keeps it as their log.
        page = c.get(f"/runs/{run_id}/edit").text
        assert "Admin edit" in page
        c.post(f"/runs/{run_id}/edit", data={"date": "2026-10-21", "activity": "walk", "distance": "2.2", "time": "36:00"})
        with SessionLocal() as s:
            run = s.get(Run, run_id)
            owner = s.get(__import__("app.models", fromlist=["User"]).User, run.user_id)
            assert run.distance_mi == 2.2 and owner.username == "oldwalker"


def test_event_photos():
    with client() as c:
        signup(c, "shutterbug")
        c.post("/welcome", data={"training": "own"})
        c.post("/welcome/done")
        from datetime import date as _date, timedelta as _td
        with SessionLocal() as s:  # its own runs, so other tests moving dates around can't interfere
            today_run = Meetup(date=_date(2026, 10, 22), slot="club", title="Photo Test Run")  # "today" in tests
            future = Meetup(date=_date(2026, 10, 22) + _td(days=3), slot="club", title="Later Run")
            s.add_all([today_run, future])
            s.commit()

        # Not before the run day.
        r = c.post(f"/meetups/{future.id}/photos", files=[("photos", ("a.jpg", _jpeg_bytes(), "image/jpeg"))])
        assert "Photos open on the day of the run" in r.text

        r = c.post(f"/meetups/{today_run.id}/photos", files=[
            ("photos", ("a.jpg", _jpeg_bytes(), "image/jpeg")),
            ("photos", ("b.png", _jpeg_bytes("#1f4a37"), "image/jpeg")),
        ])
        msg = [l.strip() for l in r.text.splitlines() if 'class="ok"' in l or 'class="error"' in l]
        assert "Added 2 photos" in r.text and r.text.count('class="gallery-item"') == 2, msg
        ids = [int(x) for x in __import__("re").findall(r'/photos/(\d+)/thumb\.jpg', r.text)]
        thumb = c.get(f"/photos/{ids[0]}/thumb.jpg")
        full = c.get(f"/photos/{ids[0]}.jpg")
        assert thumb.headers["content-type"] == "image/jpeg" and len(thumb.content) < len(full.content)
        assert Image.open(BytesIO(full.content)).size == (1200, 900)
        assert "See photos from this event (2)" in c.get("/schedule?past=1").text

        bad = c.post(f"/meetups/{today_run.id}/photos", files=[("photos", ("x.jpg", b"nope", "image/jpeg"))])
        assert "read one of those as a photo" in bad.text
        c.post("/logout")

        # Someone else can't delete it; the admin can.
        signup(c, "nosy")
        c.post("/welcome", data={"training": "own"})
        c.post("/welcome/done")
        assert c.post(f"/photos/{ids[0]}/delete").status_code == 403
        c.post("/logout")
        c.post("/login", data={"username": "john", "password": "admin-password-123"})
        c.post("/welcome", data={"training": "own"})  # finish admin setup if this test runs first
        c.post("/welcome/done")
        r = c.post(f"/photos/{ids[0]}/delete")
        assert "Photo removed" in r.text and r.text.count('class="gallery-item"') == 1
        assert c.get(f"/photos/{ids[0]}.jpg").status_code == 404


def test_photo_buttons_on_run_cards():
    from datetime import date as _date, timedelta as _td

    with client() as c:
        signup(c, "cardphotos")
        c.post("/welcome", data={"training": "own"})
        c.post("/welcome/done")
        with SessionLocal() as s:
            today_run = Meetup(date=_date(2026, 10, 22), slot="club", title="Card Photo Run")
            later = Meetup(date=_date(2026, 10, 22) + _td(days=2), slot="club", title="Card Later Run")
            s.add_all([today_run, later])
            s.commit()
        sched = c.get("/schedule").text
        assert f'action="/meetups/{today_run.id}/photos"' in sched      # run day: can add from the card
        assert f'action="/meetups/{later.id}/photos"' not in sched      # future run: no button yet
        assert f'href="/meetups/{today_run.id}#photos">See photos' not in sched
        c.post(f"/meetups/{today_run.id}/photos", files=[("photos", ("a.jpg", _jpeg_bytes(), "image/jpeg"))])
        assert f'href="/meetups/{today_run.id}#photos">See photos from this event (1)' in c.get("/schedule").text
