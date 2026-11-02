import re

from app import club


def test_parse_clock():
    assert club.parse_clock("7:30") == 450
    assert club.parse_clock("1:02:03") == 3723
    assert club.parse_clock("25") == 1500
    assert club.parse_clock("7:75") is None
    assert club.parse_clock("2430") == 24 * 60 + 30      # typed without colons
    assert club.parse_clock("12010") == 3600 + 20 * 60 + 10
    assert club.parse_clock("243") == 2 * 60 + 43
    assert club.parse_clock("2490") is None              # 90 seconds isn't a clock
    assert club.parse_clock("abc") is None
    assert club.clock(3723) == "1:02:03"
    assert club.clock(450) == "7:30"


def test_week_math():
    assert club.week_number(club.start_date()) == 1
    assert club.week_start(2).isoformat() == "2026-10-20"


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
    assert len(stats.pace_trend(runs) or {}) == 0  # one run isn't a trend; the walk/ride don't count
    board = stats.leaderboard([type("U", (), {"id": 1, "name": "A"})()], runs, {})
    assert board[0]["miles"] == 5.0 and board[0]["label"] == "1 run · 1 walk"
