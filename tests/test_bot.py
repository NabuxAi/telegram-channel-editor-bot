"""Offline verification: no Telegram or Telegraph network access."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bot import ChannelEditor, BotError, _channel, _message_id


class FakeTelegram:
    def __init__(self, *, editable=True, postable=True):
        self.editable = editable
        self.postable = postable
        self.calls = []
        self.sent = []

    def call(self, method, payload):
        self.calls.append((method, payload))
        if method == "getMe":
            return {"id": 900}
        if method == "getChatMember":
            return {
                "status": "administrator",
                "can_edit_messages": self.editable,
                "can_post_messages": self.postable,
            }
        if method == "sendMessage":
            if isinstance(payload.get("chat_id"), int):
                self.sent.append(payload["text"])
            return {"message_id": 321}
        if method.startswith("editMessage"):
            return True
        raise AssertionError("Unexpected API method: " + method)


def update(text, *, owner=15, private=True):
    return {"message": {"from": {"id": owner}, "chat": {
        "type": "private" if private else "channel",
    }, "text": text}}


def edited(fake):
    return [(method, data) for method, data in fake.calls if method.startswith("editMessage")]


class ChannelEditorTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeTelegram()
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.data_file = str(Path(self.tempdir.name) / "buttons.json")
        self.editor = ChannelEditor(self.fake, {15}, data_file=self.data_file)

    def confirm(self):
        code = self.editor.pending[15]["code"]
        self.editor.handle(update("/confirm " + code))

    def test_untrusted_or_public_chats_are_ignored(self):
        self.editor.handle(update("/edit @news 111 Test", owner=99))
        self.editor.handle(update("/edit @news 111 Test", private=False))
        self.assertEqual(self.fake.calls, [])

    def test_buttons_require_preview_and_confirmation(self):
        self.editor.handle(update("/button @news 111 Read more | https://example.org/post"))
        self.assertEqual(edited(self.fake), [])
        self.assertIn("PREVIEW", self.fake.sent[-1])
        self.confirm()
        self.assertEqual(len(edited(self.fake)), 1)
        method, payload = edited(self.fake)[0]
        self.assertEqual(method, "editMessageReplyMarkup")
        self.assertEqual(payload["chat_id"], "@news")
        self.assertEqual(payload["message_id"], 111)
        self.assertEqual(payload["reply_markup"]["inline_keyboard"][0][0], {
            "text": "Read more", "url": "https://example.org/post",
        })
        self.editor.handle(update("/confirm " + self.fake.sent[0].split()[-1]))
        self.assertEqual(len(edited(self.fake)), 1)

    def test_wrong_confirmation_does_not_mutate(self):
        self.editor.handle(update("/edit @news 111 Fixed text"))
        self.editor.handle(update("/confirm wrong"))
        self.assertEqual(edited(self.fake), [])
        self.confirm()
        self.assertEqual(edited(self.fake)[0][0], "editMessageText")

    def test_missing_admin_edit_right_rejected(self):
        self.fake.editable = False
        self.editor.handle(update("/caption @news 111 Changed caption"))
        self.confirm()
        self.assertEqual(edited(self.fake), [])
        self.assertIn("can_edit_messages", self.fake.sent[-1])

    def test_edit_caption_photo_and_clear_buttons(self):
        self.editor.handle(update("/caption @news 111 Updated caption"))
        self.confirm()
        self.assertEqual(edited(self.fake)[-1][0], "editMessageCaption")
        self.editor.handle(update("/photo @news 111 https://example.org/p.jpg | New photo caption"))
        self.confirm()
        method, payload = edited(self.fake)[-1]
        self.assertEqual(method, "editMessageMedia")
        self.assertEqual(payload["media"]["caption"], "New photo caption")
        self.editor.handle(update("/clearbuttons @news 111"))
        self.confirm()
        self.assertEqual(edited(self.fake)[-1][1]["reply_markup"], {"inline_keyboard": []})

    def test_reject_private_inline_urls(self):
        self.editor.handle(update("/button @news 111 Visit | http://local.example"))
        self.editor.handle(update("/button @news 111 Visit | https://127.0.0.1/post"))
        self.assertEqual(self.editor.pending, {})
        self.assertEqual(edited(self.fake), [])

    def test_default_button_only_affects_own_future_posts(self):
        self.editor.handle(update("/default @news Open website | https://example.org"))
        self.assertFalse(Path(self.data_file).exists())
        self.confirm()
        self.assertTrue(Path(self.data_file).exists())
        self.assertEqual(self.editor.defaults["@news"][0][0]["text"], "Open website")
        recreated = ChannelEditor(self.fake, {15}, data_file=self.data_file)
        self.assertEqual(recreated.defaults, self.editor.defaults)
        self.editor.handle(update("/post @news Hello everyone"))
        published_before = [m for m, p in self.fake.calls if m == "sendMessage" and p.get("chat_id") == "@news"]
        self.assertEqual(published_before, [])
        self.confirm()
        publish = [(m, p) for m, p in self.fake.calls if m == "sendMessage" and p.get("chat_id") == "@news"]
        self.assertEqual(len(publish), 1)
        self.assertEqual(publish[0][1]["reply_markup"]["inline_keyboard"][0][0]["url"], "https://example.org")

    def test_telegraph_requires_configuration_and_second_confirm(self):
        self.editor.handle(update("/telegraph Article | One paragraph"))
        self.assertIn("not configured", self.fake.sent[-1])
        self.editor.telegraph_token = "fake-telegraph-token"
        with patch("bot.telegraph_page", return_value="https://telegra.ph/Some-Page") as publish:
            self.editor.handle(update("/telegraph Article | One paragraph"))
            publish.assert_not_called()
            self.confirm()
            publish.assert_called_once_with("fake-telegraph-token", "Article", "One paragraph")
        self.assertEqual(self.fake.sent[-1], "https://telegra.ph/Some-Page")
        self.assertNotIn("fake-telegraph-token", " ".join(self.fake.sent))

    def test_bad_target_is_refused(self):
        self.assertEqual(_channel("@news"), "@news")
        with self.assertRaises(BotError):
            _channel("https://t.me/news")
        with self.assertRaises(BotError):
            _message_id("zero")


if __name__ == "__main__":
    unittest.main()
