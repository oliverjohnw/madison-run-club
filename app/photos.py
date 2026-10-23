"""
Club-run photos: decode, fix rotation, shrink, re-encode as JPEG.

Re-encoding (rather than storing the upload as-is) drops the EXIF metadata phones
attach, including GPS location, and keeps each photo small enough for the database.
"""

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_PER_UPLOAD = 10
FULL_SIZE = 1600  # longest side, px
THUMB_SIZE = 480


class PhotoError(ValueError):
    pass


def _jpeg(img: Image.Image, longest: int, quality: int) -> bytes:
    copy = img.copy()
    copy.thumbnail((longest, longest), Image.Resampling.LANCZOS)
    out = BytesIO()
    copy.save(out, "JPEG", quality=quality, optimize=True, progressive=True)  # no exif= : metadata dropped
    return out.getvalue()


def process(upload: bytes) -> tuple[bytes, bytes, int, int]:
    """Returns (full JPEG, thumbnail JPEG, width, height). Raises PhotoError."""
    if len(upload) > MAX_UPLOAD_BYTES:
        raise PhotoError("One of those photos is over 20 MB.")
    try:
        img = Image.open(BytesIO(upload))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise PhotoError("Couldn't read one of those as a photo. JPEG and PNG work best.") from exc
    img = ImageOps.exif_transpose(img)  # phones store rotation in EXIF; apply it before dropping EXIF
    if img.mode != "RGB":
        img = img.convert("RGB")
    full = _jpeg(img, FULL_SIZE, 85)
    width, height = Image.open(BytesIO(full)).size
    return full, _jpeg(img, THUMB_SIZE, 80), width, height
