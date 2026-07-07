#!/usr/bin/env python3
"""One-time interactive login for the Telethon userbot.

Run this once before starting the agent. It will ask for your phone number and
the login code Telegram sends you (and your 2FA password if you have one), then
save a session file so the agent can read channels as your account.

    python login.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from telethon import TelegramClient

from ontgagent.config import Config


async def main() -> None:
    config = Config.load()
    Path(config.session_name).parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(config.session_name, config.api_id, config.api_hash)
    await client.start()  # prompts for phone + code interactively
    me = await client.get_me()
    username = getattr(me, "username", None) or me.id
    print(f"\n✅ Logged in as {username}. Session saved to {config.session_name}.")
    print("You can now start the agent with:  python -m ontgagent")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
