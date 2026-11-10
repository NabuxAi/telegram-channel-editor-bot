# Nabu Channel Editor Bot

**Self-hostable, owner-controlled Telegram channel editor** built with Python's standard library. Free Core Forever: no subscription, credit card, paid API or dependency installation is required. A VPS/domain is optional and costs extra if used.

## Why it exists

TelegramMCP (the owner's existing `tm.nabuxai.com`) can already edit message text and photos through a permitted personal Telegram session. **A personal account cannot attach bot inline keyboards.** This separate project uses the official Telegram **Bot API** for editing channel posts and adding URL buttons, with an explicit confirmation step.

**This repository contains working source, not an already-registered Telegram bot.** You must register your own bot with BotFather, set a private token, and add that bot as an admin to channels you control. No real messages are sent by the included test suite.

## Features

- Edit a channel post's text, media caption, or replace its photo with a public HTTPS image URL.
- Add, replace or remove an inline **URL** button on a specific existing post.
- Set a per-channel default URL button for **future posts created by this bot**. This does not rewrite existing posts or posts created by other services.
- Create a Telegraph article through the official Telegraph API (optional, token provided separately).
- Owner allowlist, private-chat-only commands, channel administrator permission checks, 3-minute explicit preview/confirmation, one mutation per confirmation, no background bulk edits.
- Zero third-party Python packages; unit tests and GitHub Actions CI.

## Quick Start

Requires Python 3.11+ and an authorized Telegram bot token.

```bash
git clone https://github.com/NabuxAi/telegram-channel-editor-bot.git
cd telegram-channel-editor-bot
cp .env.example .env
# Edit .env with your real values locally; never commit credentials.
set -a; . ./.env; set +a
python3 bot.py
```

Prepare `.env` with:

```dotenv
TG_BOT_TOKEN=YOUR_PRIVATE_BOT_TOKEN_FROM_BOTFATHER
ALLOWED_USER_IDS=123456789
TELEGRAPH_ACCESS_TOKEN=
DATA_FILE=data/default-buttons.json
```

Use your **numeric Telegram user ID** in `ALLOWED_USER_IDS` (comma-separated for multiple authorized owners). Never use an arbitrary username or `*`. Only the allowlisted user's private DM commands are processed. The bot must be made an administrator in each channel with `can_edit_messages` for editing existing posts and `can_post_messages` for new posts.

### Commands (send in a private chat with your bot)

| Command | Description |
|---|---|
| `/help` | Show instructions |
| `/edit @mychannel 123 Updated post text` | Edit text on a specific channel post |
| `/caption @mychannel 123 Updated caption` | Edit existing media caption |
| `/photo @mychannel 123 https://example.org/new.jpg \| New caption` | Replace an existing image, with explicit caption |
| `/button @mychannel 123 Read more \| https://example.org/post` | Add/replace a URL inline button |
| `/clearbuttons @mychannel 123` | Remove existing inline buttons |
| `/default @mychannel Visit website \| https://example.org` | Set default URL button on **this bot's future /post messages** |
| `/post @mychannel New approved post text` | Preview and publish one post; uses channel's default button |
| `/telegraph Title \| Article text` | Create a Telegraph page if token configured |
| `/confirm CODE` | Apply the last previewed operation within 3 minutes |

Example flow: send `/button @mychannel 123 Read more | https://example.org/post`, inspect the preview, then reply with the unique `/confirm CODE`. Merely asking for a preview **does not edit Telegram**.

**Limitations:** The Bot API can edit only messages for which it has permission. Telegram may reject attempts to edit content posted by another account or with unsupported media. Even a bot admin cannot guarantee an arbitrary old message can be changed. If a channel is administered by a user session, use the existing TelegramMCP editing function for text/photo. Inline keyboards require the bot route.

## Telegraph

Optional: provide `TELEGRAPH_ACCESS_TOKEN` for an existing Telegraph account. Use `/telegraph Title | Text` in the bot's private chat. The official API creates the article only after explicit confirmation. This implementation **does not** create Telegraph account credentials automatically, persist them, or include article editing; Telegraph editing remains available in the NabuGen backend adapter.

## Deployment & security

- Long polling with Telegram's official API; **do not run multiple instances using the same token**. Set `TG_BOT_TOKEN` from a private environment file/secret manager (not command arguments or repository).
- Keep `.env` and `data/` private. The app stores only optional default URL buttons as `data/default-buttons.json`, permissions `0600`.
- Commands are accepted only in a private chat from IDs in `ALLOWED_USER_IDS`. Editing requires bot's `can_edit_messages`; posting/default needs `can_post_messages`.
- All content-changing operations require a single-use confirmation which expires after 3 minutes, and **are never retried automatically** after uncertain network failures.
- No contact scraping, mass editing, bot-session takeover, unsolicited bulk posting, account rotation or ban evasion.
- Existing bot token must remain separate from NabuGen unless expressly approved by its owner. Running this source does not change `tm.nabuxai.com`, NabuGen or production channels.
- Network and hosting costs, if any, are yours. This core remains MIT-licensed and free.

## Development

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
python3 -m compileall -q bot.py editor_core.py tests
```

All tests use a fake Telegram client and mocked Telegraph API. Never run live writes from CI.

## Roadmap

- Optional authorized per-channel button presets with exact post-ID scoping and explicit human approval.
- Telegraph edit-page support; custom page formatting only after safe review.
- Integration into NabuGen via its existing owner-scoped API, not duplicate Telegram user sessions.
- Backup/preview support for batched historical edits **before** enabling any bulk editing, with explicit opt-in and rate limits.

See [SECURITY.md](SECURITY.md) and Telegram's [Bot API](https://core.telegram.org/bots/api) and [Telegraph API](https://telegra.ph/api) for details.
