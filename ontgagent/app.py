"""Wires the pieces together and runs the poll loop and bot concurrently."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from telethon import TelegramClient

from .bot import ConfirmationBot
from .config import Config
from .db import Database
from .reader import Reader
from .rewriter import Rewriter

log = logging.getLogger(__name__)


class App:
    def __init__(self, config: Config):
        self.config = config
        self.db = Database(config.db_path)
        self.rewriter = Rewriter(
            api_key=config.anthropic_api_key,
            model=config.claude_model,
            style=config.read_style(),
        )
        Path(config.session_name).parent.mkdir(parents=True, exist_ok=True)
        self.client = TelegramClient(
            config.session_name, config.api_id, config.api_hash
        )
        self.reader = Reader(self.client, self.db, self.rewriter)
        self.bot = ConfirmationBot(self.config, self.db, self.reader)

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self.reader.poll_once(self.bot.send_draft)
            except Exception as exc:  # noqa: BLE001 - keep the loop alive
                log.exception("Poll loop error: %s", exc)
            await asyncio.sleep(self.config.poll_interval)

    async def run(self) -> None:
        await self.db.connect()
        await self.client.connect()
        if not await self.client.is_user_authorized():
            raise RuntimeError(
                "Telethon session is not authorized. Run `python login.py` first."
            )
        me = await self.client.get_me()
        log.info("Userbot logged in as %s", getattr(me, "username", None) or me.id)

        try:
            await self.bot.bot.send_message(
                self.config.owner_id,
                "🤖 OnTgAgent is online. Send /help to get started.",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not message owner on startup: %s", exc)

        log.info("Starting poll loop (every %ss) and bot.", self.config.poll_interval)
        try:
            await asyncio.gather(self._poll_loop(), self.bot.start_polling())
        finally:
            await self.client.disconnect()
            await self.bot.bot.session.close()
            await self.db.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = Config.load()
    app = App(config)
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        log.info("Shutting down.")


if __name__ == "__main__":
    main()
