from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


def is_image_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def image_part(source: str, *, root: Path | None = None) -> dict[str, Any]:
    """Build an OpenAI-compatible image_url content part from a URL or local image."""
    if is_image_url(source):
        return {"type": "image_url", "image_url": {"url": source}}

    path = Path(source).expanduser()
    if not path.is_absolute() and root is not None:
        path = root / path
    path = path.resolve()
    if root is not None:
        try:
            path.relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError(f"Image path escapes project root: {path}") from exc
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Image file not found: {path}")
    mime, _ = mimetypes.guess_type(path.name)
    mime = mime or "application/octet-stream"
    if mime not in SUPPORTED_IMAGE_TYPES:
        raise ValueError(f"Unsupported image type: {mime}. Supported: {', '.join(sorted(SUPPORTED_IMAGE_TYPES))}")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}


def user_content_with_images(text: str, image_sources: list[str] | None = None, *, root: Path | None = None) -> str | list[dict[str, Any]]:
    if not image_sources:
        return text
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for source in image_sources:
        parts.append(image_part(source, root=root))
    return parts
