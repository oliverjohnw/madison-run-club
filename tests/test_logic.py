import re

import pytest

from app import club, quiz


def test_parse_clock():
    assert club.parse_clock("7:30") == 450
    assert club.parse_clock("1:02:03") == 3723
    assert club.parse_clock("25") == 1500
    assert club.parse_clock("7:75") is None
    assert club.parse_clock("abc") is None
    assert club.clock(3723) == "1:02:03"
    assert club.clock(450) == "7:30"


def test_week_math():
    assert club.week_number(club.start_date()) == 1
    assert club.week_start(2).isoformat() == "2026-10-20"


@pytest.mark.parametrize("pace,key", [(390, "send"), (450, "push"), (540, "chase"), (660, "cruise"), (750, "finish"), (None, "finish")])
def test_plan_for_pace(pace, key):
    assert club.plan_for_pace(pace) == key


@pytest.mark.parametrize("key", ["send", "push", "chase", "cruise", "finish"])
def test_every_plan_fills_in(key):
    weeks = club.plan_weeks(key, 480)
    assert len(weeks) == 6
    for w in weeks:
        for slot in club.SLOTS:
            s = w["sessions"][slot]
            assert s.title and s.what
            assert not re.search(r"[{}]", s.what), s.what


def test_quiz_suggestions():
    fast = quiz.suggest({"mile": "u7", "longest": "6+", "often": "3+"})
    assert fast.pace_sec == 420 and fast.plan_key == "send"
    mid = quiz.suggest({"mile": "7-8", "longest": "3-6", "often": "1-2"})
    assert mid.plan_key == "push"
    new_runner = quiz.suggest({"mile": "8-930", "longest": "none", "often": "0"})
    assert new_runner.plan_key == "cruise"
    beginner = quiz.suggest({"mile": "idk", "longest": "none", "often": "0"})
    assert beginner.pace_sec is None and beginner.plan_key == "finish"
    assert quiz.decode(quiz.encode({"mile": "u7", "longest": "1", "often": "0"})) == {"mile": "u7", "longest": "1", "often": "0"}


def test_plan_week_lookup():
    wk = club.plan_week("push", 450, 2)
    assert wk["n"] == 2 and set(wk["sessions"]) == {"club", "short", "long"}
    assert club.plan_week("push", 450, 0) is None and club.plan_week("push", 450, 7) is None
    assert club.plan_week("", None, 2) is None  # own workouts: no plan


def test_stats_split_by_activity():
    from datetime import date

    from app import stats
    from app.models import Run

    runs = [
        Run(id=1, user_id=1, date=date(2026, 10, 20), activity="run", distance_mi=3.0, duration_sec=1800),   # 10:00/mi
        Run(id=2, user_id=1, date=date(2026, 10, 21), activity="walk", distance_mi=2.0, duration_sec=2400),  # 20:00/mi
        Run(id=3, user_id=1, date=date(2026, 10, 22), activity="bike", distance_mi=15.0, duration_sec=3600),  # 15 mph
    ]
    s = stats.runner_stats(runs, {}, date(2026, 10, 22))
    assert s.runs == 3                                   # every log counts
    assert s.miles == 5.0                                # on foot: run + walk, not the ride
    assert s.bike_miles == 15.0
    assert s.avg_pace == 600                             # run pace only (walk and ride left out)
    assert s.longest == 3.0                              # longest *run*
    assert s.week_by_activity == {"run": 3.0, "walk": 2.0, "bike": 15.0}
    assert len(stats.pace_trend(runs, None) or {}) == 0  # one run isn't a trend; the walk/ride don't count
    board = stats.leaderboard([type("U", (), {"id": 1, "name": "A"})()], runs, {})
    assert board[0]["miles"] == 5.0
