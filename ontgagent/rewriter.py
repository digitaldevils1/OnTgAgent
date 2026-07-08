"""Rewrites channel posts into the user's style.

Two interchangeable backends are supported:

* **Anthropic direct** (default) — set ``ANTHROPIC_API_KEY`` / ``CLAUDE_MODEL``.
* **Any OpenAI-compatible gateway** such as **Runware** — set
  ``RUNWARE_API_KEY``, ``RUNWARE_BASE_URL`` and ``RUNWARE_MODEL``. Whenever
  ``RUNWARE_API_KEY`` is present it takes priority over the Anthropic backend.
"""

from __future__ import annotations

import logging
import os

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
        self.style = style

        runware_key = os.getenv("RUNWARE_API_KEY", "").strip()
        if runware_key:
            # OpenAI-compatible gateway (Runware and similar).
            from openai import AsyncOpenAI

            base_url = os.getenv(
                "RUNWARE_BASE_URL", "https://api.runware.ai/v1"
            ).strip()
            self.backend = "openai"
            self.model = os.getenv(
                "RUNWARE_MODEL", "anthropic:claude-sonnet-4-6@0"
            ).strip()
            self.client = AsyncOpenAI(api_key=runware_key, base_url=base_url)
            log.info(
                "Rewriter: OpenAI-compatible backend at %s (model %s)",
                base_url,
                self.model,
            )
        else:
            # Anthropic API directly.
            self.backend = "anthropic"
            self.model = model
            self.client = AsyncAnthropic(api_key=api_key)
            log.info("Rewriter: Anthropic backend (model %s)", self.model)

    async def rewrite(self, original: str) -> str:
        if self.backend == "openai":
            return await self._rewrite_openai(original)
        return await self._rewrite_anthropic(original)

    async def _rewrite_anthropic(self, original: str) -> str:
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

    async def _rewrite_openai(self, original: str) -> str:
        response = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=1500,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT.format(style=self.style)},
                {"role": "user", "content": USER_TEMPLATE.format(original=original)},
            ],
        )
        result = (response.choices[0].message.content or "").strip()
        if not result:
            log.warning("Rewriter returned empty text; falling back to original.")
            return original
        return result
