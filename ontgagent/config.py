"""Loads configuration from environment / .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


def _default_style() -> str:
    return (
        "Rewrite the post in a clear, natural voice. Keep roughly the same "
        "length, keep the original language, remove spam and 'subscribe to our "
        "channel' calls to action, and fix any awkward phrasing."
    )


@dataclass
class Config:
    # userbot (reader)
    api_id: int
    api_hash: str
    session_name: str

    # confirmation bot
    bot_token: str
    owner_id: int
    target_channel: str | None

    # rewriting
    anthropic_api_key: str
    claude_model: str

    # behaviour
    poll_interval: int
    fetch_limit: int
    db_path: str
    style_file: str

    @classmethod
    def load(cls) -> "Config":
        return cls(
            api_id=int(_require("API_ID")),
            api_hash=_require("API_HASH"),
            session_name=os.getenv("SESSION_NAME", "sessions/userbot"),
            bot_token=_require("BOT_TOKEN"),
            owner_id=int(_require("OWNER_ID")),
            target_channel=(os.getenv("TARGET_CHANNEL") or "").strip() or None,
            anthropic_api_key=_require("ANTHROPIC_API_KEY"),
            claude_model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5"),
            poll_interval=int(os.getenv("POLL_INTERVAL", "120")),
            fetch_limit=int(os.getenv("FETCH_LIMIT", "10")),
            db_path=os.getenv("DB_PATH", "data/ontgagent.db"),
            style_file=os.getenv("STYLE_FILE", "style.txt"),
        )

    def read_style(self) -> str:
        """Return the user's style description, falling back to a default."""
        path = Path(self.style_file)
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
        return _default_style()
