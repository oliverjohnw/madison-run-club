"""
Profile pictures: decode, fix rotation, center-crop square, re-encode as JPEG.

Re-encoding drops the EXIF metadata phones attach (including GPS location)
and keeps each picture small enough to live in the database.
"""

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
SIZE = 400


class AvatarError(ValueError):
    pass


def process(upload: bytes) -> bytes:
    if len(upload) > MAX_UPLOAD_BYTES:
        raise AvatarError("That photo is over 15 MB.")
    try:
        img = Image.open(BytesIO(upload))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise AvatarError("Couldn't read that as a photo. JPEG or PNG work best.") from exc
    img = ImageOps.exif_transpose(img)
    if img.mode != "RGB":
        img = img.convert("RGB")
    img = ImageOps.fit(img, (SIZE, SIZE), Image.Resampling.LANCZOS)
    out = BytesIO()
    img.save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue()
