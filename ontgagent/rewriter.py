"""Rewrites channel posts into the user's style using the Claude API."""

from __future__ import annotations

import logging

from anthropic import AsyncAnthropic

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a social-media copy editor. You rewrite Telegram \
channel posts so they match a specific author's personal style, described below.

Rules:
- Preserve the core facts, meaning, links and any @mentions of the original.
- Rewrite the wording, tone and structure to match the author's style.
- Do NOT invent facts that are not in the original post.
- Remove cross-promotion, "subscribe to our channel" calls to action, and \
referral/spam links that belong to the SOURCE channel (not to the story itself).
- Output ONLY the finished post text, ready to publish. No preamble, no \
"Here is the rewritten post", no surrounding quotes, no explanations.

The author's style:
{style}"""

USER_TEMPLATE = """Rewrite the following Telegram post in the author's style.

--- ORIGINAL POST ---
{original}
--- END ORIGINAL POST ---"""


class Rewriter:
    def __init__(self, api_key: str, model: str, style: str):
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model
        self.style = style

    async def rewrite(self, original: str) -> str:
        message = await self.client.messages.create(
            model=self.model,
            max_tokens=1500,
            system=SYSTEM_PROMPT.format(style=self.style),
            messages=[
                {"role": "user", "content": USER_TEMPLATE.format(original=original)}
            ],
        )
        parts = [
            block.text
            for block in message.content
            if getattr(block, "type", None) == "text"
        ]
        result = "".join(parts).strip()
        if not result:
            log.warning("Rewriter returned empty text; falling back to original.")
            return original
        return result
