# OnTgAgent

A Telegram agent that **monitors channels you choose, rewrites their newest
posts in your own writing style with Claude, and sends each draft to a bot
where you approve, edit or reject it** before it's published.

```
 channels you add ──►  userbot reads new posts  ──►  Claude rewrites to your style
                                                                │
                                                                ▼
        your channel  ◄── you tap ✅ Approve ──  bot DMs you the draft (✅ ✏️ ❌)
```

## How it works

There are two Telegram identities involved, and you need both:

1. **A userbot (your own account, via Telethon).**
   A normal Telegram *bot* cannot read posts from channels it doesn't own.
   So the agent logs in as *you* using Telegram's API to read the channels you
   subscribe to. It only *reads*.

2. **A confirmation bot (via @BotFather).**
   This is what you actually talk to. It DMs you every rewritten draft with
   **✅ Approve / ✏️ Edit / ❌ Reject** buttons, and it's where you run
   `/add`, `/remove` and `/list` to manage the monitored channels. On approval
   it publishes the post to your target channel.

Rewriting is done by **Claude**, guided by a `style.txt` file that you write to
describe your voice.

## Setup

### 1. Requirements

- Python 3.10+
- A Telegram account
- API credentials (all free):
  - `API_ID` / `API_HASH` from <https://my.telegram.org> → *API development tools*
  - A bot token from [@BotFather](https://t.me/BotFather)
  - Your numeric user id from [@userinfobot](https://t.me/userinfobot)
  - An Anthropic API key from <https://console.anthropic.com>

### 2. Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env        # then edit .env with your credentials
cp style.example.txt style.txt   # then describe your writing style
```

At minimum, fill in `API_ID`, `API_HASH`, `BOT_TOKEN`, `OWNER_ID` and
`ANTHROPIC_API_KEY` in `.env`. Set `TARGET_CHANNEL` to the channel where
approved posts should be published (and make your **bot an admin** of that
channel with *Post Messages* rights). Leave it empty to just mark drafts
approved without auto-publishing.

### 4. Log the userbot in (one time)

```bash
python login.py
```

Enter your phone number and the code Telegram sends you (and your 2FA password
if you use one). This creates a session file under `sessions/` so the agent can
read channels as your account. **Keep this file private — it's a login to your
account.**

### 5. Run

```bash
python -m ontgagent
```

The bot will DM you "OnTgAgent is online". Send it `/help`.

## Using it

In the chat with your bot:

| Command | What it does |
| --- | --- |
| `/add @channel` | Start monitoring a channel (you must be subscribed to it). Sends you its latest post right away. |
| `/remove @channel` | Stop monitoring a channel. |
| `/list` | Show all monitored channels. |
| `/help` | Show the command list. |

You can pass `@username`, a `t.me/...` link, or a numeric channel id.

Every `POLL_INTERVAL` seconds the agent checks each channel for new posts,
rewrites them, and sends you a draft:

- **✅ Approve** — publishes it to `TARGET_CHANNEL` (or just marks it approved).
- **✏️ Edit** — reply with corrected text; the draft updates and you can
  approve the new version.
- **❌ Reject** — discards it.

## Configuration reference

All settings live in `.env` (see `.env.example` for the annotated version):

| Variable | Description |
| --- | --- |
| `API_ID`, `API_HASH` | Telegram app credentials (userbot). |
| `SESSION_NAME` | Where the Telethon login session is stored. |
| `BOT_TOKEN` | Your @BotFather bot token. |
| `OWNER_ID` | Your numeric Telegram id — only you can control the agent. |
| `TARGET_CHANNEL` | Channel to publish approved posts to (bot must be admin). |
| `ANTHROPIC_API_KEY` | Claude API key. |
| `CLAUDE_MODEL` | Model used for rewriting (default `claude-sonnet-5`). |
| `POLL_INTERVAL` | Seconds between channel checks (default 120). |
| `FETCH_LIMIT` | Kept for tuning how many recent messages are scanned. |
| `DB_PATH` | SQLite database path. |
| `STYLE_FILE` | File describing your writing style. |

## Tuning your style

Edit `style.txt` and describe how you want posts to sound — tone, length,
emoji usage, language, things to strip out. The more specific you are, the
closer the drafts match your voice. Changes take effect on the next restart.

## Notes & limits

- The userbot only reads channels **you are subscribed to**. Add a channel in
  the Telegram app first, then `/add` it here.
- Posts with no text (pure media, polls, stickers) are skipped — there's
  nothing to rewrite.
- State (channels, seen posts, drafts) is stored in SQLite at `DB_PATH`, so
  restarts don't re-send old posts.
- This is a personal automation tool. Respect the copyright and terms of the
  channels you republish from.
```
