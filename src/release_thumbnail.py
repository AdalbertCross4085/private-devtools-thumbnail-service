from __future__ import annotations

import base64
import binascii
import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError


class InvalidImage(ValueError):
    pass


MAX_SOURCE_BYTES = 12 * 1024 * 1024


@dataclass(frozen=True)
class Thumbnail:
    content: bytes
    width: int
    height: int
    resized: bool
    content_type: str = "image/webp"


def render_thumbnail(data_base64: str, max_width: int, max_height: int) -> Thumbnail:
    try:
        source = base64.b64decode(data_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidImage("image_base64 must be valid base64") from exc
    if len(source) > MAX_SOURCE_BYTES:
        raise InvalidImage("decoded image exceeds the 12 MiB input limit")

    try:
        with Image.open(io.BytesIO(source)) as opened:
            if opened.format not in {"JPEG", "PNG", "WEBP"}:
                raise InvalidImage("accepted formats are JPEG, PNG, and WebP")
            image = ImageOps.exif_transpose(opened)
            original_size = image.size
            image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            resized = image.size != original_size
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA" if "transparency" in image.info else "RGB")
            output = io.BytesIO()
            image.save(output, format="WEBP", quality=82, method=4)
            return Thumbnail(output.getvalue(), image.width, image.height, resized)
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidImage("image_base64 does not contain a readable image") from exc
