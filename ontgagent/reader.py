"""The userbot side: reads the latest posts from monitored channels.

Uses Telethon logged in as your personal account, because a bot cannot read
arbitrary channels it does not administer.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

from telethon import TelegramClient
from telethon.errors import RPCError

from .db import Database, Draft
from .rewriter import Rewriter

log = logging.getLogger(__name__)

# Called with a freshly created Draft so the bot can send it for approval.
OnDraft = Callable[[Draft], Awaitable[None]]


def _normalize(identifier: str) -> str | int:
    """Turn a user-supplied channel reference into something Telethon accepts."""
    ident = identifier.strip()
    if ident.startswith("https://t.me/"):
        ident = ident[len("https://t.me/"):]
    if ident.startswith("t.me/"):
        ident = ident[len("t.me/"):]
    ident = ident.lstrip("@")
    # Numeric channel id, e.g. -1001234567890
    if ident.lstrip("-").isdigit():
        return int(ident)
    return ident


class Reader:
    def __init__(self, client: TelegramClient, db: Database, rewriter: Rewriter):
        self.client = client
        self.db = db
        self.rewriter = rewriter

    async def resolve_title(self, identifier: str) -> str | None:
        """Return the channel's display title, or None if it can't be reached."""
        try:
            entity = await self.client.get_entity(_normalize(identifier))
            return getattr(entity, "title", None) or getattr(entity, "username", None)
        except (RPCError, ValueError) as exc:
            log.warning("Could not resolve %s: %s", identifier, exc)
            return None

    async def poll_once(self, on_draft: OnDraft) -> None:
        """Poll every monitored channel once and emit drafts for new posts."""
        channels = await self.db.list_channels()
        for row in channels:
            identifier = row["identifier"]
            last_id = row["last_msg_id"]
            try:
                await self._poll_channel(identifier, last_id, on_draft)
            except (RPCError, ValueError) as exc:
                log.warning("Error polling %s: %s", identifier, exc)

    async def _poll_channel(
        self, identifier: str, last_id: int, on_draft: OnDraft
    ) -> None:
        entity = await self.client.get_entity(_normalize(identifier))
        messages = await self.client.get_messages(entity, limit=50)
        if not messages:
            return

        # First time we see this channel: only take the single latest post so we
        # don't flood you with the channel's entire history.
        if last_id == 0:
            newest = messages[0]
            await self.db.set_last_msg_id(identifier, newest.id)
            await self._emit(identifier, newest, on_draft)
            return

        # Subsequent polls: everything newer than last seen, oldest first.
        fresh = [m for m in messages if m.id > last_id]
        fresh.sort(key=lambda m: m.id)
        for msg in fresh:
            await self._emit(identifier, msg, on_draft)
            await self.db.set_last_msg_id(identifier, msg.id)

    async def _emit(self, identifier: str, msg, on_draft: OnDraft) -> None:
        text = (msg.message or "").strip()
        if not text:
            # Nothing to rewrite (pure media / sticker / poll). Skip it.
            return
        try:
            rewritten = await self.rewriter.rewrite(text)
        except Exception as exc:  # noqa: BLE001 - never let one post kill the loop
            log.exception("Rewrite failed for %s/%s: %s", identifier, msg.id, exc)
            return

        draft_id = await self.db.create_draft(identifier, msg.id, text, rewritten)
        if draft_id is None:
            return  # already processed this exact post
        draft = await self.db.get_draft(draft_id)
        if draft:
            await on_draft(draft)
