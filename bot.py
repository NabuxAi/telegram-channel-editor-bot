"""Nabu Channel Editor — independent, consent-based Telegram channel post bot.

Standard-library only. All mutation commands are private, allowlisted, checked
against Telegram channel admin permissions and require explicit confirmation.
No mass-editing, user-session scraping, or account rotation.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from editor_core import PostEditError, keyboard, operation

METHODS = {
    "getMe", "getUpdates", "getChatMember", "sendMessage", "editMessageText",
    "editMessageCaption", "editMessageMedia", "editMessageReplyMarkup",
}


class BotError(RuntimeError):
    pass


class TelegramAPI:
    def __init__(self, token: str):
        if not token:
            raise BotError("TG_BOT_TOKEN is required.")
        self._token = token

    def call(self, method: str, payload: dict) -> dict:
        if method not in METHODS:
            raise BotError("Telegram method is not allowed.")
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"https://api.telegram.org/bot{self._token}/{method}",
            data=data, headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urlopen(request, timeout=35) as response:
                reply = json.load(response)
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            # Never echo URL or exception: HTTP error URLs contain the bot token.
            raise BotError("Telegram request failed.") from exc
        if not reply.get("ok"):
            raise BotError("Telegram refused the operation (check permissions and message type).")
        return reply.get("result")


def telegraph_page(token: str, title: str, body: str) -> str:
    """Create one official Telegraph page; the secret stays out of the result."""
    if not token:
        raise BotError("TELEGRAPH_ACCESS_TOKEN is not configured.")
    title = title.strip()
    if not 1 <= len(title) <= 256 or not body.strip():
        raise BotError("Telegraph requires a title and article body.")
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    content = json.dumps([{"tag": "p", "children": [p]} for p in paragraphs],
                         ensure_ascii=False)
    if not paragraphs or len(content.encode("utf-8")) > 60_000:
        raise BotError("Telegraph article exceeds the safe size limit.")
    request = Request(
        "https://api.telegra.ph/createPage",
        data=urlencode({
            "access_token": token, "title": title, "content": content,
            "return_content": "false",
        }).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST",
    )
    try:
        with urlopen(request, timeout=25) as response:
            result = json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise BotError("Telegraph request failed.") from exc
    page = result.get("result") if result.get("ok") else None
    if not isinstance(page, dict) or not isinstance(page.get("url"), str):
        raise BotError("Telegraph refused the page.")
    return page["url"]


def _channel(channel: str) -> str:
    value = channel.strip()
    if value.startswith("@") and len(value) > 2 and " " not in value:
        return value
    if value.startswith("-100") and value[1:].isdigit():
        return value
    raise BotError("Use a public @channel or -100... channel ID.")


def _message_id(value: str) -> int:
    try:
        mid = int(value)
    except ValueError as exc:
        raise BotError("Message ID must be a number.") from exc
    if mid <= 0:
        raise BotError("Message ID must be positive.")
    return mid


def _label_url(value: str) -> tuple[str, str]:
    label, separator, url = value.partition("|")
    if not separator:
        raise BotError("Use Label | https://example.org")
    rows = keyboard([[{"text": label.strip(), "url": url.strip()}]])
    button = rows["inline_keyboard"][0][0]
    return button["text"], button["url"]


class ChannelEditor:
    def __init__(self, api, owner_ids: set[int], *,
                 telegraph_token: str = "", data_file: str | None = None):
        if not owner_ids:
            raise BotError("ALLOWED_USER_IDS must name at least one owner.")
        self.api = api
        self.owner_ids = set(owner_ids)
        self.telegraph_token = telegraph_token
        self.data_file = Path(data_file) if data_file else None
        self.defaults: dict[str, list] = {}
        self.pending: dict[int, dict] = {}
        self.bot_id: int | None = None
        if self.data_file and self.data_file.exists():
            try:
                stored = json.loads(self.data_file.read_text(encoding="utf-8"))
                for channel, buttons in stored.items():
                    _channel(channel)
                    self.defaults[channel] = keyboard(buttons)["inline_keyboard"]
            except (OSError, ValueError, TypeError, PostEditError) as exc:
                raise BotError("Invalid defaults JSON; refusing to start.") from exc

    def _save_defaults(self):
        if not self.data_file:
            raise BotError("DATA_FILE is needed for persistent default buttons.")
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        temp = self.data_file.with_name(self.data_file.name + ".tmp")
        temp.write_text(json.dumps(self.defaults, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(temp, 0o600)
        os.replace(temp, self.data_file)

    def _reply(self, owner: int, message: str):
        self.api.call("sendMessage", {"chat_id": owner, "text": message[:4096]})

    def _get_bot_id(self) -> int:
        if self.bot_id is None:
            self.bot_id = int(self.api.call("getMe", {})["id"])
        return self.bot_id

    def _require_channel_permission(self, channel: str, action: str):
        member = self.api.call("getChatMember", {
            "chat_id": channel, "user_id": self._get_bot_id(),
        })
        if member.get("status") not in {"administrator", "creator"}:
            raise BotError("Bot must be a channel administrator.")
        right = "can_post_messages" if action in {"post", "default"} else "can_edit_messages"
        if not member.get(right):
            raise BotError(f"Bot needs channel admin permission: {right}.")

    def _queue(self, owner: int, purpose: str, action: dict, preview: str):
        code = secrets.token_urlsafe(6)
        self.pending[owner] = {
            "code": code, "expires": time.monotonic() + 180,
            "action": action, "purpose": purpose,
        }
        self._reply(owner, f"PREVIEW: {preview[:2800]}\n\nConfirm within 3 minutes: /confirm {code}")

    def _execute(self, action: dict) -> str:
        command = action["command"]
        channel = action.get("channel")
        if channel:
            self._require_channel_permission(channel, command)
        if command == "default":
            previous = self.defaults.get(channel)
            self.defaults[channel] = action["rows"]
            try:
                self._save_defaults()
            except Exception:
                if previous is None:
                    self.defaults.pop(channel, None)
                else:
                    self.defaults[channel] = previous
                raise
            return "Default URL button saved for future /post commands in this bot only."
        if command == "telegraph":
            return telegraph_page(
                self.telegraph_token, action["title"], action["body"]
            )
        result = self.api.call(action["method"], action["payload"])
        if command == "post":
            message_id = result.get("message_id") if isinstance(result, dict) else None
            return f"Published one channel post. Message ID: {message_id}."
        return "Edit confirmed by Telegram."

    def handle(self, update: dict):
        message = update.get("message") or {}
        sender = message.get("from") or {}
        chat = message.get("chat") or {}
        owner = sender.get("id")
        # A bot can receive channel updates. Never treat those as owner commands.
        if not isinstance(owner, int) or owner not in self.owner_ids or chat.get("type") != "private":
            return
        text = message.get("text")
        if not isinstance(text, str) or not text.startswith("/"):
            return
        command, _, rest = text.partition(" ")
        command = command.split("@", 1)[0].lower()
        rest = rest.strip()
        try:
            if command in {"/start", "/help"}:
                self._reply(owner,
                    "Nabu Channel Editor · admin-only\n"
                    "/edit @channel 123 New text\n"
                    "/caption @channel 123 New caption\n"
                    "/button @channel 123 Read more | https://site.com/post\n"
                    "/clearbuttons @channel 123\n"
                    "/photo @channel 123 https://site.com/photo.jpg | New caption\n"
                    "/default @channel Read more | https://site.com\n"
                    "/post @channel New one-off channel post\n"
                    "/telegraph Title | Article body\n"
                    "/confirm CODE\n\n"
                    "Default buttons apply ONLY to new /post messages created by THIS bot; "
                    "old posts are never edited in bulk.")
                return
            if command == "/confirm":
                pending = self.pending.get(owner)
                if not pending or pending["code"] != rest or pending["expires"] < time.monotonic():
                    raise BotError("Confirmation missing or expired.")
                self.pending.pop(owner, None)  # no replay even on timeout
                try:
                    result = self._execute(pending["action"])
                except BotError:
                    raise
                except Exception as exc:
                    raise BotError("Operation failed without automatic retry.") from exc
                self._reply(owner, result)
                return
            if command == "/telegraph":
                title, sep, body = rest.partition("|")
                if not sep or not title.strip() or not body.strip():
                    raise BotError("Use: /telegraph Title | Article body")
                if not self.telegraph_token:
                    raise BotError("TELEGRAPH_ACCESS_TOKEN is not configured.")
                self._queue(owner, "telegraph", {
                    "command": "telegraph", "title": title.strip(), "body": body.strip(),
                }, f"Publish Telegraph article: {title.strip()}\n{body.strip()}")
                return
            if command in {"/default", "/post"}:
                pieces = rest.split(maxsplit=1)
                if len(pieces) < 2:
                    raise BotError("Specify a channel and content.")
                channel = _channel(pieces[0])
                if command == "/default":
                    label, url = _label_url(pieces[1])
                    rows = [[{"text": label, "url": url}]]
                    self._queue(owner, "default", {
                        "command": "default", "channel": channel, "rows": rows,
                    }, f"Future bot-authored posts in {channel}: {label} → {url}")
                else:
                    new_text = pieces[1].strip()
                    if not new_text or len(new_text) > 4096:
                        raise BotError("Post must contain 1–4096 characters.")
                    payload = {"chat_id": channel, "text": new_text}
                    if channel in self.defaults:
                        payload["reply_markup"] = {"inline_keyboard": self.defaults[channel]}
                    self._queue(owner, "post", {
                        "command": "post", "channel": channel, "method": "sendMessage",
                        "payload": payload,
                    }, f"Publish to {channel}: {new_text}")
                return
            if command not in {"/edit", "/caption", "/photo", "/button", "/clearbuttons"}:
                raise BotError("Unknown command. Use /help.")
            parts = rest.split(maxsplit=2)
            if len(parts) < 2:
                raise BotError("Use /help for channel and message-ID syntax.")
            channel = _channel(parts[0])
            mid = _message_id(parts[1])
            value = parts[2] if len(parts) >= 3 else ""
            if command == "/edit":
                method, fields = operation("text", text=value, has_media=False)
            elif command == "/caption":
                method, fields = operation("caption", text=value, has_media=True)
            elif command == "/clearbuttons":
                if value:
                    raise BotError("/clearbuttons accepts only channel and message ID.")
                method, fields = operation("buttons", buttons=[])
            elif command == "/button":
                label, url = _label_url(value)
                method, fields = operation("buttons", buttons=[[{"text": label, "url": url}]])
            else:
                url, sep, caption = value.partition("|")
                if not sep:
                    raise BotError("Use: /photo @channel ID https://image.jpg | Caption")
                method, fields = operation("photo", text=caption.strip(),
                                           image_url=url.strip(), has_media=True)
            payload = {"chat_id": channel, "message_id": mid, **fields}
            self._queue(owner, command, {
                "command": command[1:], "channel": channel,
                "method": method, "payload": payload,
            }, f"{command} on {channel} message {mid}: {value}")
        except (BotError, PostEditError, KeyError, TypeError, ValueError) as exc:
            self._reply(owner, f"Not applied: {str(exc)[:350]}")


def main():
    owners = {int(x.strip()) for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x.strip().isdigit()}
    editor = ChannelEditor(
        TelegramAPI(os.getenv("TG_BOT_TOKEN", "")), owners,
        telegraph_token=os.getenv("TELEGRAPH_ACCESS_TOKEN", ""),
        data_file=os.getenv("DATA_FILE", "data/default-buttons.json"),
    )
    offset = None
    print("Nabu Channel Editor started (private owner commands only).")
    try:
        while True:
            try:
                payload = {"timeout": 25, "allowed_updates": ["message"]}
                if offset is not None:
                    payload["offset"] = offset
                updates = editor.api.call("getUpdates", payload)
                for item in updates or []:
                    offset = max(offset or 0, item["update_id"] + 1)
                    try:
                        editor.handle(item)
                    except BotError:
                        # A private owner notification can fail without exposing credentials.
                        print("One command was not processed.")
            except BotError:
                print("Telegram connection unavailable; retrying.")
                time.sleep(4)
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    try:
        main()
    except (BotError, ValueError) as exc:
        sys.exit(str(exc))
