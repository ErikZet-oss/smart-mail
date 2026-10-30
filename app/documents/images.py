"""Branch stamp and person signature images for print documents (#139).

PNG with a transparent background only (the stamp is printed over the signature box), max 1 MB and 4000 px,
scaled down to 1200 px on the long side. The images are used only when the server renders a PDF; they are never
served publicly and never become signature variables in e-mails.
"""

from __future__ import annotations

import io

from app.mail.signature_images import SignatureImageError

MAX_STAMP_BYTES = 1024 * 1024
MAX_STAMP_INPUT_PX = 4000
STAMP_TARGET_PX = 1200


def normalize_stamp_png(data: bytes) -> bytes:
    """Validate and normalise an uploaded stamp or signature; raises SignatureImageError(code)."""
    if not data:
        raise SignatureImageError("image_type")
    if len(data) > MAX_STAMP_BYTES:
        raise SignatureImageError("image_too_large")
    if not data.startswith(b"\x89PNG"):
        raise SignatureImageError("image_png_required")
    from PIL import Image

    try:
        # `open` only reads the header; the size is checked here, before any decode — no change of Pillow's global
        # MAX_IMAGE_PIXELS, which other uploads in the same process rely on (#140 review)
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            if width < 1 or height < 1 or width > MAX_STAMP_INPUT_PX or height > MAX_STAMP_INPUT_PX:
                raise SignatureImageError("image_too_large")
            has_alpha = image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info)
            if not has_alpha:
                raise SignatureImageError("image_not_transparent")
            rgba = image.convert("RGBA")
            low, _high = rgba.getchannel("A").getextrema()
            if low == 255:  # an alpha channel that is fully opaque everywhere
                raise SignatureImageError("image_not_transparent")
            rgba.thumbnail((STAMP_TARGET_PX, STAMP_TARGET_PX))
            out = io.BytesIO()
            rgba.save(out, format="PNG", optimize=True)
    except SignatureImageError:
        raise
    except Image.DecompressionBombError as exc:
        raise SignatureImageError("image_too_large") from exc
    except Exception as exc:
        raise SignatureImageError("image_type") from exc
    return out.getvalue()
