"""Async SQLite storage for monitored channels, seen posts and drafts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    identifier   TEXT PRIMARY KEY,   -- @username or numeric id as given by the user
    title        TEXT,
    last_msg_id  INTEGER NOT NULL DEFAULT 0,
    added_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS drafts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    channel      TEXT NOT NULL,
    source_id    INTEGER NOT NULL,      -- source message id in the channel
    original     TEXT NOT NULL,
    rewritten    TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(channel, source_id)
);
"""


@dataclass
class Draft:
    id: int
    channel: str
    source_id: int
    original: str
    rewritten: str
    status: str


class Database:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database is not connected. Call connect() first.")
        return self._db

    # --- channels -----------------------------------------------------------

    async def add_channel(self, identifier: str, title: str | None = None) -> bool:
        """Add a channel to monitor. Returns False if it already existed."""
        cur = await self.db.execute(
            "INSERT OR IGNORE INTO channels (identifier, title) VALUES (?, ?)",
            (identifier, title),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def remove_channel(self, identifier: str) -> bool:
        cur = await self.db.execute(
            "DELETE FROM channels WHERE identifier = ?", (identifier,)
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def list_channels(self) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            "SELECT identifier, title, last_msg_id FROM channels ORDER BY added_at"
        )
        return await cur.fetchall()

    async def set_last_msg_id(self, identifier: str, msg_id: int) -> None:
        await self.db.execute(
            "UPDATE channels SET last_msg_id = ? WHERE identifier = ?",
            (msg_id, identifier),
        )
        await self.db.commit()

    async def set_channel_title(self, identifier: str, title: str) -> None:
        await self.db.execute(
            "UPDATE channels SET title = ? WHERE identifier = ?",
            (title, identifier),
        )
        await self.db.commit()

    # --- drafts -------------------------------------------------------------

    async def create_draft(
        self, channel: str, source_id: int, original: str, rewritten: str
    ) -> int | None:
        """Insert a new pending draft. Returns its id, or None if it existed."""
        cur = await self.db.execute(
            """INSERT OR IGNORE INTO drafts (channel, source_id, original, rewritten)
               VALUES (?, ?, ?, ?)""",
            (channel, source_id, original, rewritten),
        )
        await self.db.commit()
        if cur.rowcount == 0:
            return None
        return cur.lastrowid

    async def get_draft(self, draft_id: int) -> Draft | None:
        cur = await self.db.execute(
            "SELECT * FROM drafts WHERE id = ?", (draft_id,)
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return Draft(
            id=row["id"],
            channel=row["channel"],
            source_id=row["source_id"],
            original=row["original"],
            rewritten=row["rewritten"],
            status=row["status"],
        )

    async def update_rewritten(self, draft_id: int, rewritten: str) -> None:
        await self.db.execute(
            "UPDATE drafts SET rewritten = ? WHERE id = ?", (rewritten, draft_id)
        )
        await self.db.commit()

    async def set_status(self, draft_id: int, status: str) -> None:
        await self.db.execute(
            "UPDATE drafts SET status = ? WHERE id = ?", (status, draft_id)
        )
        await self.db.commit()
