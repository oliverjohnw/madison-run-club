"""New-member setup: one optional step (a profile picture), then you're in."""

from fastapi import APIRouter, Depends, Request
from starlette.responses import RedirectResponse

from app.db import SessionLocal
from app.models import User
from app.routes.deps import me
from app.templating import render

router = APIRouter()


@router.get("/welcome")
def photo_page(request: Request, user: User = Depends(me)):
    return render(request, "welcome/photo.html")


@router.post("/welcome/done")
def done(request: Request, user: User = Depends(me)):
    with SessionLocal() as session:
        session.get(User, user.id).onboarded = True
        session.commit()
    request.session["setup"] = False
    return RedirectResponse("/?fresh=1", status_code=303)
