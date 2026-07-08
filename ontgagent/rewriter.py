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

SYSTEM_PROMPT = """Ты — редактор контента для соцсетей. Ты переписываешь посты \
из Telegram-каналов так, чтобы они соответствовали личному стилю автора, \
описанному ниже.

Правила:
- Сохраняй суть, факты, ссылки и любые @упоминания из оригинала.
- Меняй формулировки, тон и структуру под стиль автора.
- НЕ придумывай факты, которых нет в оригинальном посте.
- Убирай кросс-промо, призывы «подпишись на канал» и реферальные/спам-ссылки, \
относящиеся к ИСХОДНОМУ каналу (а не к самой новости).
- По умолчанию пиши на русском языке, если в стиле автора не сказано иное.
- Выводи ТОЛЬКО готовый текст поста, готовый к публикации. Без вступлений, без \
фраз вроде «Вот переписанный пост», без кавычек вокруг текста и без пояснений.

Стиль автора:
{style}"""

USER_TEMPLATE = """Перепиши следующий пост из Telegram в стиле автора.

--- ОРИГИНАЛ ПОСТА ---
{original}
--- КОНЕЦ ОРИГИНАЛА ---"""


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
