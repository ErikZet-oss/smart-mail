"""Signature image uploads (DECISIONS D22, SETTINGS 03a / 11c).

PNG, JPEG and GIF stay raster images. SVG is converted to PNG. At most 5 uploads and 200 kB each.
Uploaded bytes are stored outside the HTML and referenced as ``cid:`` so the 64 kB HTML limit still holds.
"""

from __future__ import annotations

import io
import re
import shutil
import subprocess
from email.message import EmailMessage
from typing import Any

_CID = re.compile(r"""cid:([^"'>\s]+)""", re.IGNORECASE)

MAX_SIGNATURE_IMAGE_BYTES = 200 * 1024
MAX_SIGNATURE_IMAGES = 5


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


def _svg_to_png(data: bytes) -> bytes:
    """Rasterise SVG with a system tool when one is installed. The browser converts before upload."""
    tools: tuple[tuple[str, list[str]], ...] = (
        ("rsvg-convert", ["-f", "png"]),
        ("convert", ["svg:-", "png:-"]),
    )
    for binary, args in tools:
        path = shutil.which(binary)
        if not path:
            continue
        completed = subprocess.run([path, *args], input=data, capture_output=True, check=False)  # noqa: S603
        if completed.returncode == 0 and completed.stdout.startswith(b"\x89PNG"):
            return completed.stdout
    raise SignatureImageError("image_type")


def normalize_signature_image(data: bytes) -> tuple[bytes, str]:
    """Return ``(bytes, content_type)`` for a file the editor may store. Rejects anything else."""
    if not data or len(data) > MAX_SIGNATURE_IMAGE_BYTES:
        raise SignatureImageError("image_too_large" if data else "image_type")
    if _is_svg(data):
        png = _svg_to_png(data)
        if len(png) > MAX_SIGNATURE_IMAGE_BYTES:
            raise SignatureImageError("image_too_large")
        return png, "image/png"
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - pillow is a project dependency
        raise SignatureImageError("image_type") from exc
    try:
        with Image.open(io.BytesIO(data)) as image:
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
        maintype, _, subtype = (content_type or "image/png").partition("/")
        html_part.add_related(data, maintype=maintype or "image", subtype=subtype or "png", cid=f"<{cid}>")
