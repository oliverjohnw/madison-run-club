"""
Shared Jinja2 renderer. `render()` injects the logged-in user and club config
into every page so base.html can draw the nav without each route repeating it.
"""

from datetime import date

from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app import club
from app.auth import get_current_user
from app.stats import ACTIVITIES, EFFORTS, short_date

templates = Jinja2Templates(directory="app/templates")


def miles(value: float | None) -> str:
    if not value:
        return "0"
    return f"{value:.1f}" if value < 100 else f"{value:.0f}"


def day_label(d: date) -> str:
    """'Tue, Oct 13'"""
    return f"{d:%a}, {short_date(d)}"


def relative_day(d: date) -> str:
    delta = (d - club.today()).days
    return {0: "Today", 1: "Tomorrow", -1: "Yesterday"}.get(delta) or day_label(d)


def people(ids: list[int], users: dict) -> list:
    return [users[i] for i in ids if i in users]


templates.env.filters["people"] = people
templates.env.filters["clock"] = club.clock
templates.env.filters["miles"] = miles
templates.env.filters["day"] = day_label
templates.env.filters["short"] = short_date
templates.env.filters["rel"] = relative_day
templates.env.globals["EFFORTS"] = EFFORTS
templates.env.globals["ACTIVITIES"] = ACTIVITIES
templates.env.globals["SLOT_NAMES"] = club.SLOT_NAMES
templates.env.globals["week_of"] = club.week_number
templates.env.globals["club_today"] = club.today  # for macros, which don't see the page's `today`


def render(request: Request, template_name: str, context: dict | None = None, status_code: int = 200):
    ctx = {"user": get_current_user(request), "cfg": club.config(), "today": club.today(), **(context or {})}
    return templates.TemplateResponse(request, template_name, ctx, status_code=status_code)


# Macro libraries every template can use without importing: ui.avatar(...), viz.heatmap(...).
templates.env.globals["ui"] = templates.env.get_template("_ui.html").module
templates.env.globals["viz"] = templates.env.get_template("_viz.html").module
