"""
Club config (config/club.yaml), dates, and pace math.

Everything here is plain functions over the YAML + numbers, so it's easy to
test and the routes stay thin.
"""

import os
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from sqlalchemy import select

from app.db import SessionLocal

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
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


# --- Dates ------------------------------------------------------------------

def today() -> date:
    # CLUB_TODAY=2026-11-05 pretends it's that day (handy with scripts/demo_data.py
    # to see the site mid-season). Never set it in production.
    fake = os.environ.get("CLUB_TODAY", "").strip()
    if fake:
        return date.fromisoformat(fake)
    return datetime.now(ZoneInfo(config()["timezone"])).date()


def start_date() -> date:
    return config()["start_date"]


def race_options() -> list[date]:
    return list(config()["race"]["options"])


def week_number(d: date) -> int:
    """Club week for a date. Week 1 starts on start_date; 0 or less = before the club starts."""
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
    """'7:30' -> 450, '1:02:03' -> 3723, '25' -> 1500 (1-2 bare digits = minutes).
    3+ bare digits are a clock typed without colons, the same way the log form formats them
    as you type: '2430' -> 24:30, '12010' -> 1:20:10. None if unreadable."""
    text = (text or "").strip()
    if not text:
        return None
    if text.isdigit() and len(text) >= 3:
        text = (text[:-4] + ":" if len(text) > 4 else "") + text[-4:-2] + ":" + text[-2:]
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
