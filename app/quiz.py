"""
The 3-question signup quiz and the goal pace it suggests.

The math: take their mile guess, stretch it to a 5K with Riegel's formula
(5K pace ~ 7% slower than mile pace), then add time if they haven't been
running much or haven't gone far. Round to 15 seconds. Slower than 12:00/mi
gets pointed at the "just finish" (run/walk) plan.
"""

from dataclasses import dataclass

from app.club import clock, five_k_time, plan_for_pace

QUESTIONS = [
    {
        "key": "mile",
        "ask": "If you ran one mile right now, how long would it take?",
        "hint": "Gut feeling. Nobody's timing you.",
        "options": [
            ("u7", "Under 7 min"),
            ("7-8", "7-8 min"),
            ("8-930", "8-9:30"),
            ("930-12", "9:30-12"),
            ("12+", "12+, with some walking"),
            ("idk", "No idea"),
        ],
    },
    {
        "key": "longest",
        "ask": "Longest you've run in the last couple months?",
        "hint": "Without stopping, roughly.",
        "options": [
            ("none", "Haven't run"),
            ("1", "About a mile"),
            ("2-3", "2-3 miles"),
            ("3-6", "3-6 miles"),
            ("6+", "More than 6"),
        ],
    },
    {
        "key": "often",
        "ask": "How often do you run these days?",
        "hint": None,
        "options": [
            ("0", "Basically never"),
            ("rare", "Once in a while"),
            ("1-2", "1-2× a week"),
            ("3+", "3+ a week"),
        ],
    },
]

MILE_SEC = {"u7": 390, "7-8": 450, "8-930": 525, "930-12": 645, "12+": 780}
MILE_GUESS_BY_HABIT = {"0": 690, "rare": 600, "1-2": 510, "3+": 450}  # when they pick "No idea"
LONGEST_ADD = {"none": 60, "1": 40, "2-3": 15, "3-6": 0, "6+": 0}
HABIT_ADD = {"0": 20, "rare": 10, "1-2": 0, "3+": 0}
FINISH_CUTOFF = 720  # slower than 12:00/mi -> suggest the run/walk plan


@dataclass
class Suggestion:
    pace_sec: int | None  # None = "just finish"
    est_pace_sec: int     # what we think they'd run today-ish, even for "finish"
    plan_key: str

    @property
    def label(self) -> str:
        return "Just finish" if self.pace_sec is None else f"{clock(self.pace_sec)}/mi"

    @property
    def five_k(self) -> str:
        return clock(five_k_time(self.est_pace_sec))


def valid(answers: dict) -> bool:
    return all(answers.get(q["key"]) in {k for k, _ in q["options"]} for q in QUESTIONS)


def suggest(answers: dict) -> Suggestion:
    mile = MILE_SEC.get(answers["mile"]) or MILE_GUESS_BY_HABIT[answers["often"]]
    pace = mile * 1.07 + LONGEST_ADD[answers["longest"]] + HABIT_ADD[answers["often"]]
    pace = int(round(pace / 15) * 15)
    goal = None if pace > FINISH_CUTOFF else pace
    return Suggestion(goal, pace, plan_for_pace(goal))


def encode(answers: dict) -> str:
    return ";".join(f"{q['key']}={answers.get(q['key'], '')}" for q in QUESTIONS)


def decode(text: str) -> dict:
    return dict(part.split("=", 1) for part in (text or "").split(";") if "=" in part)


def describe(text: str) -> list[tuple[str, str]]:
    """[(question, answer label)] for the admin page."""
    answers = decode(text)
    out = []
    for q in QUESTIONS:
        labels = dict(q["options"])
        out.append((q["ask"], labels.get(answers.get(q["key"], ""), "-")))
    return out
