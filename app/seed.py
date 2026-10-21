"""First-run setup: put the club runs from config/club.yaml on the schedule."""

from sqlalchemy import func, inspect, select, text, update

from app import club
from app.db import SessionLocal, engine
from app.models import ClubSetting, Meetup, RaceVote, User


def seed_meetups() -> int:
    """Only when there are no meetups at all, so deleting one on the site sticks."""
    with SessionLocal() as session:
        if session.scalar(select(func.count(Meetup.id))):
            return 0
        rows = club.config().get("meetups", [])
        for m in rows:
            session.add(Meetup(date=m["date"], slot="club", title=m.get("title", "Club Run"),
                               time_label=m.get("time", ""), location=m.get("location", ""),
                               details=(m.get("details") or "").strip(), is_event=bool(m.get("event"))))
        session.commit()
        return len(rows)


def backfill_training() -> None:
    """Members who signed up before the plan / own-workouts choice existed: keep their plan."""
    with SessionLocal() as session:
        session.execute(update(User).where(User.training == "", User.plan_key != "", User.onboarded.is_(True))
                        .values(training="plan"))
        session.commit()


def migrate_race_votes() -> None:
    """Race votes used to be one per person (table `race_votes`). Copy them into the
    multi-day table exactly once (remembered in club_settings). The old table is left alone."""
    with SessionLocal() as session:
        if session.get(ClubSetting, "race_votes_migrated"):
            return
        if inspect(engine).has_table("race_votes") and not session.scalar(select(func.count(RaceVote.id))):
            session.execute(text("INSERT INTO race_day_votes (user_id, choice) SELECT user_id, choice FROM race_votes"))
        session.add(ClubSetting(key="race_votes_migrated", value="1"))
        session.commit()
