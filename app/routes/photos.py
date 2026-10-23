"""Photos on club runs: upload (any member, from the day of the run on), view, delete."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import undefer
from starlette.datastructures import UploadFile  # what request.form() returns (FastAPI's is a subclass)
from starlette.responses import RedirectResponse

from app import club, photos
from app.db import SessionLocal
from app.models import Meetup, MeetupPhoto, User
from app.routes.deps import me

router = APIRouter()


def can_add_photos(m: Meetup) -> bool:
    """Photos open on the day of the run (no point before), and never for canceled runs."""
    return not m.canceled and m.date <= club.today()


@router.post("/meetups/{meetup_id}/photos")
async def upload(request: Request, meetup_id: int, user: User = Depends(me)):
    form = await request.form()
    files = [f for f in form.getlist("photos") if isinstance(f, UploadFile) and f.filename]
    back = RedirectResponse(f"/meetups/{meetup_id}#photos", status_code=303)
    with SessionLocal() as session:
        m = session.get(Meetup, meetup_id)
        if m is None:
            raise HTTPException(404)
        if not can_add_photos(m):
            request.session["photo_msg"] = "Photos open on the day of the run."
            return back
        if not files:
            request.session["photo_msg"] = "Pick at least one photo."
            return back
        if len(files) > photos.MAX_PER_UPLOAD:
            request.session["photo_msg"] = f"Up to {photos.MAX_PER_UPLOAD} photos at a time."
            return back
        added = 0
        for f in files:
            try:
                full, thumb, w, h = photos.process(await f.read())
            except photos.PhotoError as exc:
                request.session["photo_msg"] = str(exc)
                continue
            session.add(MeetupPhoto(meetup_id=m.id, user_id=user.id, image=full, thumb=thumb, width=w, height=h))
            added += 1
        session.commit()
    if added:
        request.session["photo_ok"] = f"Added {added} photo{'s' if added != 1 else ''}."
    return back


def _photo(photo_id: int, column) -> Response:
    with SessionLocal() as session:
        p = session.scalar(select(MeetupPhoto).options(undefer(column)).where(MeetupPhoto.id == photo_id))
        if p is None:
            raise HTTPException(404)
        data = p.image if column is MeetupPhoto.image else p.thumb
    # A photo never changes once uploaded (only deleted), so cache hard.
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=31536000, immutable"})


@router.get("/photos/{photo_id}.jpg")
def full_photo(photo_id: int):
    return _photo(photo_id, MeetupPhoto.image)


@router.get("/photos/{photo_id}/thumb.jpg")
def thumb_photo(photo_id: int):
    return _photo(photo_id, MeetupPhoto.thumb)


@router.post("/photos/{photo_id}/delete")
def delete(request: Request, photo_id: int, user: User = Depends(me)):
    with SessionLocal() as session:
        p = session.get(MeetupPhoto, photo_id)
        if p is None:
            raise HTTPException(404)
        if p.user_id != user.id and not user.is_admin:
            raise HTTPException(403)
        meetup_id = p.meetup_id
        session.delete(p)
        session.commit()
    request.session["photo_ok"] = "Photo removed."
    return RedirectResponse(f"/meetups/{meetup_id}#photos", status_code=303)
