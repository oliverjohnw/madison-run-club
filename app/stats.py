"""
Numbers and chart shapes for the profile, home and club pages.

Charts are hand-drawn SVG (see templates/_viz.html). This module does the
math and hands the templates ready-to-draw coordinates, so the templates stay
dumb and every number is testable.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from app import club
from app.models import Meetup, Run

EFFORTS = {1: "Chill", 2: "Comfy", 3: "Honest", 4: "Hard", 5: "Cooked"}
ACTIVITIES = {"run": "Run", "walk": "Walk", "bike": "Bike"}

# Which logs count where:
# - "miles" (leaderboards, road trip, weekly bars, heatmap) = on foot: runs + walks.
#   A long bike ride would otherwise swamp everyone's running totals.
# - pace stats (average pace, pace chart, projected 5K, longest run) = runs only.
# - bike miles are tracked on their own, and every log counts toward streaks and badges.


def on_foot(runs: list[Run]) -> list[Run]:
    return [r for r in runs if r.activity != "bike"]


def runs_only(runs: list[Run]) -> list[Run]:
    return [r for r in runs if r.activity == "run"]


def short_date(d: date) -> str:
    return f"{d:%b} {d.day}"  # "Oct 13" (strftime's %-d isn't portable to Windows)


# --- One runner -------------------------------------------------------------

@dataclass
class RunnerStats:
    miles: float = 0.0          # on foot (run + walk)
    runs: int = 0               # every log, any activity
    seconds: int = 0            # on foot
    run_miles: float = 0.0
    run_seconds: int = 0
    longest: float = 0.0        # longest run
    best_pace: float | None = None
    best_5k: float | None = None
    club_runs: int = 0
    week_streak: int = 0
    week_miles: float = 0.0     # on foot, this plan week
    by_activity: dict = field(default_factory=lambda: {k: 0.0 for k in ACTIVITIES})       # all-time miles
    week_by_activity: dict = field(default_factory=lambda: {k: 0.0 for k in ACTIVITIES})  # this week's miles
    badges: list = field(default_factory=list)

    @property
    def avg_pace(self) -> float | None:
        """Average running pace (walks and rides left out)."""
        return self.run_seconds / self.run_miles if self.run_miles else None

    @property
    def bike_miles(self) -> float:
        return self.by_activity["bike"]


def runner_stats(runs: list[Run], meetups: dict[int, Meetup], today: date) -> RunnerStats:
    s = RunnerStats()
    this_week = club.week_number(today)
    for r in runs:
        s.runs += 1
        kind = r.activity if r.activity in ACTIVITIES else "run"
        s.by_activity[kind] += r.distance_mi
        if club.week_number(r.date) == this_week:
            s.week_by_activity[kind] += r.distance_mi
        if r.meetup_id in meetups:
            s.club_runs += 1
        if kind == "bike":
            continue
        s.miles += r.distance_mi
        s.seconds += r.duration_sec
        if kind != "run":
            continue
        s.run_miles += r.distance_mi
        s.run_seconds += r.duration_sec
        s.longest = max(s.longest, r.distance_mi)
        if r.distance_mi >= 1:
            s.best_pace = min(filter(None, [s.best_pace, r.pace_sec]))
            pred = club.riegel_5k(r.distance_mi, r.duration_sec)
            s.best_5k = min(filter(None, [s.best_5k, pred]))
    weeks_with_runs = {club.week_number(r.date) for r in runs}  # any activity keeps a streak alive
    s.week_miles = s.week_by_activity["run"] + s.week_by_activity["walk"]
    w = this_week if this_week in weeks_with_runs else this_week - 1
    while w in weeks_with_runs:
        s.week_streak += 1
        w -= 1
    s.badges = badges(runs, meetups, s, today)
    return s


BADGE_DEFS = [
    ("first", "First Tracks", "Log your first run"),
    ("club3", "Regular", "Make 3 club runs"),
    ("perfect", "Perfect Attendance", "Every club run so far (2+)"),
    ("wkd", "Early Moose", "A weekend morning run"),
    ("hat", "Hat Trick", "3 runs in one week"),
    ("5k", "The Full 5K", "Run or walk 3.1 mi in one go"),
    ("ten", "Double Digits", "10 total miles"),
    ("mara", "Marathon, Eventually", "26.2 total miles"),
    ("solo", "Lone Moose", "Log a run on your own time"),
]


def badges(runs: list[Run], meetups: dict[int, Meetup], s: RunnerStats, today: date) -> list[dict]:
    club_runs = [r.meetup_id for r in runs if r.meetup_id in meetups and meetups[r.meetup_id].slot == "club"]
    past_club = {m.id for m in meetups.values() if m.slot == "club" and not m.canceled and m.date <= today}
    per_week = defaultdict(int)
    for r in runs:
        per_week[club.week_number(r.date)] += 1
    earned = {
        "first": s.runs >= 1,
        "club3": len(set(club_runs)) >= 3,
        "perfect": len(past_club) >= 2 and past_club <= set(club_runs),
        "wkd": any(r.date.weekday() >= 5 for r in runs),
        "hat": max(per_week.values(), default=0) >= 3,
        "5k": max([r.distance_mi for r in on_foot(runs)] + [0]) >= 3.1,
        "ten": s.miles >= 10,
        "mara": s.miles >= 26.2,
        "solo": any(r.meetup_id is None for r in runs),
    }
    return [{"key": k, "name": n, "desc": d, "earned": earned[k]} for k, n, d in BADGE_DEFS]


# --- Charts -----------------------------------------------------------------

def plan_week_count() -> int:
    """Weeks to draw: plan weeks plus the race week."""
    last = max(club.race_options())
    return club.week_number(last)


def weekly_bars(runs: list[Run], today: date) -> dict:
    runs = on_foot(runs)
    n_weeks = plan_week_count()
    miles = defaultdict(float)
    for r in runs:
        miles[club.week_number(r.date)] += r.distance_mi
    top = max([miles[w] for w in range(1, n_weeks + 1)] + [5.0])
    current = club.week_number(today)
    bars = []
    for w in range(1, n_weeks + 1):
        bars.append({
            "n": w,
            "label": short_date(club.week_start(w)),
            "miles": miles[w],
            "h": miles[w] / top,
            "current": w == current,
            "future": w > current,
        })
    return {"bars": bars, "top": top}


def heatmap(runs: list[Run], today: date, scale: float = 1.0) -> dict:
    """Tue-Mon rows x one column per plan week, shaded by miles that day.
    `scale` stretches the shade thresholds (the club-wide map passes ~members/2)."""
    runs = on_foot(runs)
    by_day = defaultdict(float)
    for r in runs:
        by_day[r.date] += r.distance_mi
    race_days = set(club.race_options())
    cols = []
    for w in range(1, plan_week_count() + 1):
        start = club.week_start(w)
        cells = []
        for i in range(7):
            d = start + timedelta(days=i)
            mi = by_day.get(d, 0.0)
            level = 0 if mi == 0 else 1 if mi < 2 * scale else 2 if mi < 3.1 * scale else 3 if mi < 5 * scale else 4
            cells.append({"date": d, "miles": mi, "level": level, "future": d > today,
                          "today": d == today, "race": d in race_days})
        cols.append({"n": w, "cells": cells})
    return {"cols": cols, "rows": ["Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Mon"]}


def pace_trend(runs: list[Run], goal_pace: int | None, width: int = 860, height: int = 220) -> dict | None:
    pts = sorted((r for r in runs_only(runs) if r.distance_mi >= 0.5), key=lambda r: (r.date, r.id))
    if len(pts) < 2:
        return None
    paces = [r.pace_sec for r in pts]
    lo = min(paces + ([goal_pace] if goal_pace else []))
    hi = max(paces + ([goal_pace] if goal_pace else []))
    lo, hi = lo - 20, hi + 20
    pad_l, pad_r, pad_t, pad_b = 44, 12, 14, 22
    w, h = width - pad_l - pad_r, height - pad_t - pad_b

    def y(p: float) -> float:  # faster = higher on the chart
        return pad_t + (p - lo) / (hi - lo) * h

    step = w / (len(pts) - 1)
    dots = [{"x": pad_l + i * step, "y": y(r.pace_sec), "run": r} for i, r in enumerate(pts)]
    line = " ".join(f"{d['x']:.1f},{d['y']:.1f}" for d in dots)
    area = f"{pad_l},{pad_t + h} {line} {pad_l + w},{pad_t + h}"
    ticks = [{"y": y(p), "label": club.clock(p)} for p in _nice_ticks(lo, hi)]
    return {
        "width": width, "height": height, "line": line, "area": area, "dots": dots, "ticks": ticks,
        "goal_y": y(goal_pace) if goal_pace else None, "goal": club.clock(goal_pace) if goal_pace else None,
        "x0": pad_l, "x1": pad_l + w, "bottom": pad_t + h,
    }


def _nice_ticks(lo: float, hi: float) -> list[int]:
    span = hi - lo
    step = 15 if span <= 90 else 30 if span <= 200 else 60
    first = int(lo // step + 1) * step
    return list(range(first, int(hi), step))


# --- The whole club ---------------------------------------------------------

def leaderboard(users: list, runs: list[Run], meetups: dict[int, Meetup], since: date | None = None) -> list[dict]:
    rows = {u.id: {"user": u, "miles": 0.0, "runs": 0, "club": 0} for u in users}
    for r in on_foot(runs):
        if since and r.date < since:
            continue
        row = rows.get(r.user_id)
        if row:
            row["miles"] += r.distance_mi
            row["runs"] += 1
            row["club"] += r.meetup_id in meetups
    out = sorted(rows.values(), key=lambda x: (-x["miles"], -x["runs"], x["user"].name.lower()))
    top = max([x["miles"] for x in out] + [1.0])
    for x in out:
        x["share"] = x["miles"] / top
    return out


def journey(total_miles: float) -> dict:
    cfg = club.config()["journey"]
    stops = cfg["stops"]
    end = stops[-1]["mi"]
    laps, into = divmod(total_miles, end)
    passed = [s for s in stops if s["mi"] <= into]
    upcoming = next((s for s in stops if s["mi"] > into), stops[-1])
    return {
        "name": cfg["name"],
        "stops": [{**s, "at": s["mi"] / end, "passed": s["mi"] <= into} for s in stops],
        "progress": into / end,
        "laps": int(laps),
        "last": passed[-1]["name"] if passed else stops[0]["name"],
        "next": upcoming["name"],
        "to_next": upcoming["mi"] - into,
        "total": total_miles,
    }


def turnout(meetups: list[Meetup], rsvps: list, runs: list[Run], today: date) -> dict:
    """Past (non-canceled) meetups: how many said they'd come vs. how many logged it,
    plus whole-number y-axis ticks (people)."""
    said = defaultdict(int)
    for r in rsvps:
        if r.status == "in":
            said[r.meetup_id] += 1
    logged = defaultdict(set)
    for r in runs:
        if r.meetup_id:
            logged[r.meetup_id].add(r.user_id)
    rows = [{"meetup": m, "said": said[m.id], "logged": len(logged[m.id])}
            for m in meetups if m.date <= today and not m.canceled]
    peak = max([max(x["said"], x["logged"]) for x in rows] + [1])
    step = 1 if peak <= 6 else 2 if peak <= 12 else 5
    top = -(-peak // step) * step  # round up to a whole tick
    for x in rows:
        x["said_h"], x["logged_h"] = x["said"] / top, x["logged"] / top
    return {"rows": rows, "ticks": [{"v": v, "h": v / top} for v in range(0, top + 1, step)]}
