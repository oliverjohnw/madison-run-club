"""
Fill a LOCAL database with pretend members, RSVPs, runs and votes, so you can
see what the site looks like mid-plan.

    uv run python scripts/demo_data.py 2026-11-05     # runs up to that date
    CLUB_TODAY=2026-11-05 uv run uvicorn app.main:app --port 8002

Every demo member's password is "moosetracks". Refuses to touch Postgres.
Run with --wipe to delete the demo members (and their runs) again.
"""

import os
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

if os.environ.get("DATABASE_URL", "").strip():
    sys.exit("DATABASE_URL is set - demo data is for the local SQLite file only.")

from sqlalchemy import delete, select  # noqa: E402

from app import club  # noqa: E402
from app.auth import hash_password  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Kudos, Meetup, RaceVote, Rsvp, Run, User  # noqa: E402
from app.seed import seed_meetups  # noqa: E402

PEOPLE = [
    # username, name, goal pace, training ("plan"/"own"), how reliable (chance they show up / run solo)
    ("maddie", "Maddie Kowalski", 405, "plan", 0.9),
    ("tbone", "Tony Bonilla", None, "own", 0.75),
    ("priya", "Priya Raman", 540, "plan", 0.7),
    ("gus", "Gus Lindqvist", None, "plan", 0.8),
    ("kels", "Kelsey Ortega", 660, "plan", 0.55),
    ("dre", "Dre Washington", None, "own", 0.6),
]
TITLES_SOLO = ["Lakeshore path loop", "Capitol Square laps", "Treadmill, don't judge", "Picnic Point out-and-back",
               "Arboretum wander", "Before-work miles", "Sunset on Monona"]
NOTES = ["Windy on the isthmus.", "Legs felt heavy, got better.", "Geese were aggressive today.", "",
         "Felt great honestly", "", "Walked the hill. No regrets.", ""]


def wipe(session) -> None:
    names = [p[0] for p in PEOPLE]
    session.execute(delete(User).where(User.username.in_(names)))
    session.commit()


def main() -> None:
    init_db()
    seed_meetups()
    rng = random.Random(7)
    with SessionLocal() as session:
        wipe(session)
        if "--wipe" in sys.argv:
            print("Demo members removed.")
            return
        until = date.fromisoformat(next((a for a in sys.argv[1:] if not a.startswith("--")), club.today().isoformat()))
        meetups = list(session.scalars(select(Meetup).order_by(Meetup.date)))
        users = []
        for username, display, pace, training, _ in PEOPLE:
            u = User(username=username, display_name=display, full_name=display, email=f"{username}@example.com", phone="608-555-0100",
                     password_hash=hash_password("moosetracks"), training=training, goal_pace_sec=pace,
                     plan_key=club.plan_for_pace(pace) if training == "plan" else "",
                     quiz="mile=8-930;longest=2-3;often=1-2", onboarded=True)
            session.add(u)
            users.append(u)
        session.flush()

        for u, (_, _, pace, _, reliable) in zip(users, PEOPLE):
            base = (pace or 600) + 60  # they run easier than goal most days
            for m in meetups:
                if m.slot != "club":
                    continue
                showed = rng.random() < reliable
                if m.date > until:  # future: just RSVP
                    if rng.random() < reliable:
                        session.add(Rsvp(meetup_id=m.id, user_id=u.id, status="in" if showed else "solo"))
                    continue
                session.add(Rsvp(meetup_id=m.id, user_id=u.id, status="in" if showed else rng.choice(["solo", "out"])))
                if not showed:
                    continue
                week = club.week_number(m.date)
                dist = 2.6 * (pace and 1.3 or 1) + week * 0.15 + rng.uniform(-0.3, 0.3)
                speedup = week * 4  # getting fitter
                secs = int(dist * (base - speedup + rng.uniform(-15, 20)))
                session.add(Run(user_id=u.id, date=m.date, distance_mi=round(dist, 2), duration_sec=secs, meetup_id=m.id,
                                title=m.title, effort=rng.choice([2, 3, 3, 4]), notes=rng.choice(NOTES)))
            # A few solo runs.
            d = club.start_date()
            while d <= until:
                if d.weekday() in (1, 5) and rng.random() < reliable * 0.5:
                    dist = round(rng.uniform(1.5, 3.5), 2)
                    session.add(Run(user_id=u.id, date=d, distance_mi=dist, duration_sec=int(dist * (base + rng.uniform(-10, 30))),
                                    title=rng.choice(TITLES_SOLO), effort=rng.choice([1, 2, 3]), notes=rng.choice(NOTES)))
                d += timedelta(days=1)
            session.add(RaceVote(user_id=u.id, choice=rng.choice(club.race_options()[:2])))
        session.flush()

        runs = list(session.scalars(select(Run)))
        for r in runs:
            for u in users:
                if u.id != r.user_id and rng.random() < 0.35:
                    session.add(Kudos(run_id=r.id, user_id=u.id))
        session.commit()
        print(f"Added {len(users)} demo members and {len(runs)} runs up to {until}. Password: moosetracks")


if __name__ == "__main__":
    main()
