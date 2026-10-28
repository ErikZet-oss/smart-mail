"""Signature image uploads (DECISIONS D22, SETTINGS 03a / 11c).

PNG, JPEG and GIF stay raster images. SVG is rejected — the browser converts SVG to PNG before
upload. At most 5 uploads and 200 kB each, and at most 2000×2000 px.
Uploaded bytes are stored outside the HTML and referenced as ``cid:`` so the 64 kB HTML limit still holds.
"""

from __future__ import annotations

import io
import re
from email.message import EmailMessage
from typing import Any

_CID = re.compile(r"""cid:([^"'>\s]+)""", re.IGNORECASE)

MAX_SIGNATURE_IMAGE_BYTES = 200 * 1024
MAX_SIGNATURE_IMAGES = 5
MAX_SIGNATURE_IMAGE_PX = 2000


class SignatureImageError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def image_dicts(raw: object) -> list[dict[str, Any]]:
    """Drop legacy string entries; keep records that have an id."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("cid"), str):
            out.append(item)
    return out


def sniff_image_type(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    return "application/octet-stream"


def _is_svg(data: bytes) -> bool:
    head = data.lstrip()[:200].lower()
    return head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in data[:2000].lower())


def _reject_huge(image: object) -> None:
    """``image.size`` before any ``save`` — a small file can still be a decompression bomb."""
    size = getattr(image, "size", None)
    if not isinstance(size, tuple) or len(size) != 2:
        raise SignatureImageError("image_type")
    width, height = size
    if not isinstance(width, int) or not isinstance(height, int):
        raise SignatureImageError("image_type")
    if width < 1 or height < 1 or width > MAX_SIGNATURE_IMAGE_PX or height > MAX_SIGNATURE_IMAGE_PX:
        raise SignatureImageError("image_too_large")


def normalize_signature_image(data: bytes) -> tuple[bytes, str]:
    """Return ``(bytes, content_type)`` for a file the editor may store. Rejects anything else."""
    if not data or len(data) > MAX_SIGNATURE_IMAGE_BYTES:
        raise SignatureImageError("image_too_large" if data else "image_type")
    if _is_svg(data):
        # SVG is converted in the browser. Never rasterise it here (file read / SSRF).
        raise SignatureImageError("image_type")
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - pillow is a project dependency
        raise SignatureImageError("image_type") from exc
    Image.MAX_IMAGE_PIXELS = MAX_SIGNATURE_IMAGE_PX * MAX_SIGNATURE_IMAGE_PX
    try:
        with Image.open(io.BytesIO(data)) as image:
            _reject_huge(image)
            fmt = (image.format or "").upper()
            if fmt == "GIF":
                return data, "image/gif"
            out = io.BytesIO()
            if fmt == "JPEG":
                image.convert("RGB").save(out, format="JPEG", quality=90)
                payload = out.getvalue()
                content_type = "image/jpeg"
            elif fmt == "PNG":
                image.save(out, format="PNG")
                payload = out.getvalue()
                content_type = "image/png"
            else:
                raise SignatureImageError("image_type")
    except SignatureImageError:
        raise
    except Image.DecompressionBombError as exc:
        raise SignatureImageError("image_too_large") from exc
    except Exception as exc:
        raise SignatureImageError("image_type") from exc
    if len(payload) > MAX_SIGNATURE_IMAGE_BYTES:
        raise SignatureImageError("image_too_large")
    return payload, content_type


def cids_in_html(html: str) -> list[str]:
    seen: list[str] = []
    for cid in _CID.findall(html or ""):
        if cid not in seen:
            seen.append(cid)
    return seen


def add_related_images(message: EmailMessage, blobs: list[tuple[str, bytes, str]]) -> None:
    """Attach ``(cid, bytes, content_type)`` as related parts on the HTML body (D22 inline CID)."""
    if not blobs:
        return
    html_part = message.get_body(preferencelist=("html",))
    if html_part is None:
        return
    for cid, data, content_type in blobs:
        # SVG is not an e-mail image (issue #31). The logo file we attach is PNG.
        if not data or "svg" in (content_type or "").lower() or _is_svg(data):
            continue
        maintype, _, subtype = (content_type or "image/png").partition("/")
        if maintype != "image":
            continue
        html_part.add_related(data, maintype=maintype, subtype=subtype or "png", cid=f"<{cid}>")
