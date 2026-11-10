# Security

## Model

- Bot acts **only** via the official Telegram Bot API, not personal user sessions.
- Only allowlisted numeric Telegram users can issue commands in a private chat.
- Every channel operation checks the bot's administrator status and required
  `can_edit_messages` or `can_post_messages` permissions immediately before mutation.
- Every mutation requires preview plus a single-use confirmation, expiring in
  three minutes; no background batch edits.
- URL buttons and replacement photos must use public HTTPS URLs; dangerous URL
  schemes, credentials in URLs and local IPs are rejected.
- Default buttons are stored locally as private data; credentials are never
  stored by this tool.
- Telegraph account token stays in process memory and is used only for
  explicitly confirmed article creation.
- No automatic retries of uncertain content-changing requests.

## Threats / limits

- A compromised admin session or exposed bot token grants substantial
  permissions. Use least-privilege, rotate compromised tokens and restrict
  access to your machine.
- Telegram may refuse editing posts not authored by this bot, depending on
  its permissions and platform limitations; no workaround is attempted.
- Long polling is intended for a single process with one bot token.
- Default buttons apply only when this process sends future posts via `/post`.
  Editing old posts in bulk is intentionally not implemented.
- Confirmation tokens are stored only in memory; they are invalid after restart.
- HTTPS URLs are syntax-validated, not DNS-resolved. Do not bypass hosting
  safeguards when serving content at those addresses.

## Report vulnerabilities

Open a private GitHub security advisory or contact the repository maintainers.
Do not put tokens, exported Telegram sessions, personal contact data or other
secrets in a public issue.
