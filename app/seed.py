"""First-run setup: put the club runs from config/club.yaml on the schedule."""

from sqlalchemy import func, select

from app import club
from app.db import SessionLocal
from app.models import ClubSetting, Meetup


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


def seed_race_sessions() -> None:
    """Put the 5K sessions from config/club.yaml on the schedule, exactly once (remembered in
    club_settings). A race run already on one of those dates (from the old "lock in race day"
    button) is updated in place rather than duplicated; one on any other date is removed."""
    with SessionLocal() as session:
        if session.get(ClubSetting, "race_sessions_seeded"):
            return
        race = club.config()["race"]
        wanted = {cfg["date"] for cfg in race["sessions"]}
        for stray in session.scalars(select(Meetup).where(Meetup.slot == "race")):
            if stray.date not in wanted:
                session.delete(stray)
        for cfg in race["sessions"]:
            m = session.scalar(select(Meetup).where(Meetup.slot == "race", Meetup.date == cfg["date"]))
            if m is None:
                m = Meetup(slot="race", date=cfg["date"])
                session.add(m)
            m.title = cfg["title"]
            m.time_label = cfg.get("time", "")
            m.location = race.get("location", "")
            m.details = (cfg.get("details") or "").strip()
            m.canceled = False
        session.add(ClubSetting(key="race_sessions_seeded", value="1"))
        session.commit()
