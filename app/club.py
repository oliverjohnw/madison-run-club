"""
Club config (config/club.yaml), dates, and pace math.

Everything here is plain functions over the YAML + numbers, so it's easy to
test and the routes stay thin.
"""

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from sqlalchemy import select

from app.db import SessionLocal

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
# Each plan week: one club run (done together at that week's meetup) + two bonus runs on your own.
SLOTS = ("club", "short", "long")
SLOT_NAMES = {"club": "Club run", "short": "Bonus · short", "long": "Bonus · long", "race": "Race day", "other": "Extra"}
FIVE_K_MI = 3.107


# --- YAML (re-read when the file changes, so edits show up on refresh) -------

def _load(name: str) -> dict:
    path = CONFIG_DIR / name
    return _load_cached(path, path.stat().st_mtime)


@lru_cache(maxsize=8)
def _load_cached(path: Path, _mtime: float) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def config() -> dict:
    return _load("club.yaml")


def plans_config() -> dict:
    return _load("plans.yaml")["plans"]


# --- Dates ------------------------------------------------------------------

def today() -> date:
    # CLUB_TODAY=2026-11-05 pretends it's that day (handy with scripts/demo_data.py
    # to see the site mid-plan). Never set it in production.
    fake = os.environ.get("CLUB_TODAY", "").strip()
    if fake:
        return date.fromisoformat(fake)
    return datetime.now(ZoneInfo(config()["timezone"])).date()


def start_date() -> date:
    return config()["start_date"]


def race_options() -> list[date]:
    return list(config()["race"]["options"])


def week_number(d: date) -> int:
    """Plan week for a date. Week 1 starts on start_date; 0 or less = before the club starts."""
    return (d - start_date()).days // 7 + 1


def week_start(n: int) -> date:
    return start_date() + timedelta(weeks=n - 1)


def locked_race_date() -> date | None:
    from app.models import ClubSetting

    with SessionLocal() as session:
        row = session.scalar(select(ClubSetting).where(ClubSetting.key == "race_date"))
    return date.fromisoformat(row.value) if row and row.value else None


# --- Pace + time formatting -------------------------------------------------

def parse_clock(text: str) -> int | None:
    """'7:30' -> 450, '1:02:03' -> 3723, '25' -> 1500 (bare number = minutes). None if unreadable."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        parts = [float(p) for p in text.split(":")]
    except ValueError:
        return None
    if any(p < 0 for p in parts) or len(parts) > 3:
        return None
    if len(parts) == 1:
        return round(parts[0] * 60)
    if any(p >= 60 for p in parts[1:]):
        return None
    seconds = 0.0
    for p in parts:
        seconds = seconds * 60 + p
    return round(seconds)


def clock(seconds: float | None) -> str:
    """450 -> '7:30', 3723 -> '1:02:03'."""
    if seconds is None:
        return "-"
    s = round(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def five_k_time(pace_sec: float) -> float:
    return pace_sec * FIVE_K_MI


def riegel_5k(distance_mi: float, duration_sec: float) -> float:
    """Predicted 5K time from any effort (Riegel's formula, exponent 1.06)."""
    return duration_sec * (FIVE_K_MI / distance_mi) ** 1.06


# --- Training plans ---------------------------------------------------------

@dataclass
class Session:
    week: int
    slot: str
    title: str
    what: str
    est: str

    @property
    def steps(self) -> list[str]:
        """The workout one piece per line: warm-up, main set, cool-down."""
        return [part.strip() for part in self.what.split(" · ") if part.strip()]


def plan_for_pace(goal_pace_sec: int | None) -> str:
    if goal_pace_sec is None:
        return "finish"
    for key, plan in plans_config().items():
        if goal_pace_sec <= plan["max_pace"]:
            return key
    return "finish"


def zones(goal: int) -> dict[str, str]:
    return {
        "goal": f"goal pace ({clock(goal)}/mi)",
        "tempo": f"tempo ({clock(goal + 15)}-{clock(goal + 25)}/mi)",
        "easy": f"easy ({clock(goal + 75)}-{clock(goal + 120)}/mi)",
    }


def anchor_pace(plan: dict) -> int | None:
    return parse_clock(plan["anchor"].split("/")[0]) if "/" in plan["anchor"] else None


def plan_weeks(plan_key: str, goal_pace_sec: int | None) -> list[dict]:
    """The plan with paces filled in for this runner: [{n, focus, start, sessions: {slot: Session}}]."""
    plan = plans_config()[plan_key]
    goal = goal_pace_sec or anchor_pace(plan)
    fill = zones(goal) if goal else {"goal": "goal pace", "tempo": "tempo", "easy": "easy"}
    weeks = []
    for i, wk in enumerate(plan["weeks"], start=1):
        sessions = {
            slot: Session(i, slot, wk[slot]["title"], wk[slot]["what"].format(**fill), wk[slot].get("est", ""))
            for slot in SLOTS
        }
        weeks.append({"n": i, "focus": wk["focus"], "start": week_start(i), "sessions": sessions})
    return weeks


def plan_week(plan_key: str, goal_pace_sec: int | None, n: int) -> dict | None:
    """One week of a plan (1-based), or None outside the plan / with no plan."""
    if plan_key not in plans_config():
        return None
    weeks = plan_weeks(plan_key, goal_pace_sec)
    return weeks[n - 1] if 1 <= n <= len(weeks) else None
