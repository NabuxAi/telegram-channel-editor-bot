"""Pure, reusable validation for safe Telegram channel post editing.

No Telegram access here: NabuGen's panel and a future standalone bot can share
these functions. Never accepts a free-form method, channel or Bot API payload.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
from urllib.parse import urlsplit


class PostEditError(ValueError):
    pass


def public_https(value: str) -> str:
    """Accept a public HTTPS URL for a link button or replacement photo."""
    url = str(value or "").strip()
    if len(url) > 2048 or any(ord(c) < 32 for c in url):
        raise PostEditError("URL must be a valid HTTPS link.")
    try:
        parts = urlsplit(url)
        hostname = (parts.hostname or "").lower().rstrip(".")
        port = parts.port  # validate before forwarding to Telegram
    except ValueError as exc:
        raise PostEditError("URL must be a valid HTTPS link.") from exc
    if (parts.scheme != "https" or not hostname or parts.username
            or parts.password or hostname == "localhost"
            or hostname.endswith((".localhost", ".local", ".internal"))
            or port not in (None, 443) or not hostname.count(".")):
        raise PostEditError("URL must be a public HTTPS link.")
    try:
        address = ipaddress.ip_address(hostname.strip("[]"))
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise PostEditError("Private and local network URLs are blocked.")
    return url


def keyboard(rows: list[list[dict]] | None) -> dict | None:
    """None preserves existing buttons; [] deliberately clears them."""
    if rows is None:
        return None
    if not isinstance(rows, list) or len(rows) > 5:
        raise PostEditError("At most five button rows are allowed.")
    clean: list[list[dict]] = []
    for row in rows:
        if not isinstance(row, list) or not 1 <= len(row) <= 3:
            raise PostEditError("Each row must have one to three URL buttons.")
        current = []
        for button in row:
            if not isinstance(button, dict) or set(button) != {"text", "url"}:
                raise PostEditError("Only URL buttons with text and url are supported.")
            label = button["text"]
            if not isinstance(label, str) or not 1 <= len(label.strip()) <= 64:
                raise PostEditError("Button text must contain 1 to 64 characters.")
            current.append({"text": label.strip(), "url": public_https(button["url"])})
        clean.append(current)
    return {"inline_keyboard": clean}


def operation(kind: str, *, text: str | None = None, image_url: str | None = None,
              buttons: list[list[dict]] | None = None, has_media: bool = False) -> tuple[str, dict]:
    """Return the one permitted Telegram Bot API mutation and its non-ID fields."""
    if kind not in {"text", "caption", "photo", "buttons"}:
        raise PostEditError("Unsupported edit operation.")
    markup = keyboard(buttons)
    if kind == "buttons":
        if markup is None or text is not None or image_url is not None:
            raise PostEditError("Button editing requires buttons, without text or image.")
        return "editMessageReplyMarkup", {"reply_markup": markup}
    if kind == "text":
        if has_media or image_url is not None or not isinstance(text, str) or not text.strip() or len(text) > 4096:
            raise PostEditError("Text edits require an existing text post of 1–4096 characters.")
        payload = {"text": text}
        method = "editMessageText"
    elif kind == "caption":
        if not has_media or image_url is not None or not isinstance(text, str) or len(text) > 1024:
            raise PostEditError("Caption edits require a media post and at most 1024 characters.")
        payload = {"caption": text}
        method = "editMessageCaption"
    else:
        if (not has_media or not image_url or not isinstance(text, str)
                or len(text) > 1024):
            raise PostEditError("Photo replacement needs an existing media post, new image URL and explicit caption (may be empty).")
        payload = {"media": {"type": "photo", "media": public_https(image_url), "caption": text}}
        method = "editMessageMedia"
    if markup is not None:
        payload["reply_markup"] = markup
    return method, payload


def preview_key(history_id: int, message_id: str, prior_caption: str | None,
                prior_image: str | None, method: str, args: dict, user_id: int) -> str:
    """Bind preview confirmation to a particular owner, post and current content."""
    data = [user_id, history_id, message_id, prior_caption, prior_image, method, args]
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
