"""All the tables. Small club, small schema."""

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True)
    display_name: Mapped[str] = mapped_column(String(60), server_default="")
    password_hash: Mapped[str] = mapped_column(String(128))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    # display_name is what everyone sees (their full name, set at signup).
    # Private: only the admin ever sees full_name/email/phone on their own.
    full_name: Mapped[str] = mapped_column(String(120), server_default="")
    email: Mapped[str] = mapped_column(String(254), server_default="")
    phone: Mapped[str] = mapped_column(String(40), server_default="")

    tagline: Mapped[str] = mapped_column(String(140), server_default="")
    # JPEGs live in the database (Railway's disk is wiped on every deploy).
    # Deferred so listing members doesn't drag every photo along.
    avatar: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    avatar_version: Mapped[int] = mapped_column(Integer, default=0)
    has_avatar: Mapped[bool] = mapped_column(Boolean, default=False)

    # Training. training = "plan" (follows a recommended plan) or "own" (does their own
    # workouts); "" until they choose. goal_pace_sec is None for "just finish" / own.
    training: Mapped[str] = mapped_column(String(8), server_default="")
    plan_key: Mapped[str] = mapped_column(String(16), server_default="")
    goal_pace_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    days: Mapped[str] = mapped_column(String(32), server_default="")  # unused since the switch to one meetup a week
    quiz: Mapped[str] = mapped_column(String(200), server_default="")  # "mile=8-930;longest=1;often=rare"
    onboarded: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    @property
    def name(self) -> str:
        return self.display_name or self.username

    @property
    def first_name(self) -> str:
        return self.name.split()[0]

    @property
    def follows_plan(self) -> bool:
        return self.training == "plan" and bool(self.plan_key)


class Meetup(Base):
    __tablename__ = "meetups"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    time_label: Mapped[str] = mapped_column(String(20), server_default="")
    slot: Mapped[str] = mapped_column(String(8), server_default="club")  # club (the weekly run) / race / other
    title: Mapped[str] = mapped_column(String(120))
    location: Mapped[str] = mapped_column(String(200), server_default="")
    details: Mapped[str] = mapped_column(Text, server_default="")
    is_event: Mapped[bool] = mapped_column(Boolean, default=False)  # e.g. run + watch Thursday Night Football
    canceled: Mapped[bool] = mapped_column(Boolean, default=False)


class Rsvp(Base):
    __tablename__ = "rsvps"
    __table_args__ = (UniqueConstraint("meetup_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    meetup_id: Mapped[int] = mapped_column(ForeignKey("meetups.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(8))  # in / solo / out
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    distance_mi: Mapped[float] = mapped_column(Float)
    duration_sec: Mapped[int] = mapped_column(Integer)
    meetup_id: Mapped[int | None] = mapped_column(ForeignKey("meetups.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(120), server_default="")
    effort: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1 chill .. 5 cooked
    notes: Mapped[str] = mapped_column(Text, server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    @property
    def pace_sec(self) -> float:
        return self.duration_sec / self.distance_mi if self.distance_mi else 0


class Kudos(Base):
    __tablename__ = "kudos"
    __table_args__ = (UniqueConstraint("run_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))


class RaceVote(Base):
    __tablename__ = "race_votes"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    choice: Mapped[date] = mapped_column(Date)


class ClubSetting(Base):
    """Key/value for the few things the admin changes on the site (e.g. the locked race date)."""

    __tablename__ = "club_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(500), server_default="")
