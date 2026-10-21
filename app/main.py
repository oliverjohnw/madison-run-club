"""
App entry point. Run with:

    uv run uvicorn app.main:app --port 8002

See README.md for first-run setup.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

# Load .env BEFORE importing anything that reads env vars at import time
# (app.db builds its engine from DATABASE_URL on import).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.exception_handlers import http_exception_handler  # noqa: E402
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402
from starlette.middleware.sessions import SessionMiddleware  # noqa: E402
from starlette.responses import RedirectResponse  # noqa: E402
from starlette.staticfiles import StaticFiles  # noqa: E402

import app.models  # noqa: E402,F401  (registers tables before init_db)
from app.auth import AuthGateMiddleware, ensure_admin_user  # noqa: E402
from app.db import init_db  # noqa: E402
from app.routes import account, admin, home, plan, race, runs, schedule, welcome  # noqa: E402
from app.routes.deps import StaleSession  # noqa: E402
from app.seed import backfill_training, migrate_race_votes, seed_meetups  # noqa: E402
from app.templating import render  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    ensure_admin_user()
    seed_meetups()  # first run only
    backfill_training()
    migrate_race_votes()
    yield


app = FastAPI(title="Moosehead Run Club", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

# Starlette runs the LAST-added middleware FIRST: sessions must exist before the gate checks them.
app.add_middleware(AuthGateMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ["SESSION_SECRET"],
    same_site="lax",
    https_only=os.environ.get("HTTPS_ONLY_COOKIES") == "1",
    max_age=60 * 60 * 24 * 90,  # stay logged in for 90 days
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

for module in (account, welcome, home, schedule, runs, plan, race, admin):
    app.include_router(module.router)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.exception_handler(StaleSession)
async def stale_session(request: Request, exc: StaleSession):
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if exc.status_code in (403, 404):
        return render(request, "error.html", {"code": exc.status_code}, status_code=exc.status_code)
    return await http_exception_handler(request, exc)
