"""The confirmation bot: DMs you each rewritten draft with approve / edit /
reject buttons, handles channel management commands, and publishes approved
posts to your target channel.
"""

from __future__ import annotations

import html
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .config import Config
from .db import Database, Draft
from .reader import Reader

log = logging.getLogger(__name__)

HELP = (
    "🤖 <b>OnTgAgent</b>\n\n"
    "I watch the channels you add, rewrite their newest posts in your style, "
    "and send each draft here for you to approve.\n\n"
    "<b>Commands</b>\n"
    "/add <code>@channel</code> — start monitoring a channel\n"
    "/remove <code>@channel</code> — stop monitoring a channel\n"
    "/list — show monitored channels\n"
    "/help — show this message\n\n"
    "When a draft arrives, use the buttons:\n"
    "✅ Approve — publish it (or mark it approved)\n"
    "✏️ Edit — send me corrected text\n"
    "❌ Reject — discard it"
)


def _draft_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Approve", callback_data=f"approve:{draft_id}"
                ),
                InlineKeyboardButton(
                    text="✏️ Edit", callback_data=f"edit:{draft_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Reject", callback_data=f"reject:{draft_id}"
                ),
            ]
        ]
    )


def _format_draft(draft: Draft, channel_title: str | None) -> str:
    source = html.escape(channel_title or draft.channel)
    body = html.escape(draft.rewritten)
    return (
        f"📝 <b>Draft #{draft.id}</b> — from <b>{source}</b>\n\n"
        f"{body}"
    )


class ConfirmationBot:
    def __init__(self, config: Config, db: Database, reader: Reader):
        self.config = config
        self.db = db
        self.reader = reader
        self.bot = Bot(token=config.bot_token)
        self.dp = Dispatcher()
        # owner_id -> draft_id currently being edited
        self.awaiting_edit: dict[int, int] = {}
        self._register()

    # --- guards -------------------------------------------------------------

    def _is_owner(self, user_id: int | None) -> bool:
        return user_id == self.config.owner_id

    # --- public API used by the poll loop -----------------------------------

    async def send_draft(self, draft: Draft) -> None:
        """Send a freshly created draft to the owner for approval."""
        title = None
        rows = await self.db.list_channels()
        for row in rows:
            if row["identifier"] == draft.channel:
                title = row["title"]
                break
        try:
            await self.bot.send_message(
                self.config.owner_id,
                _format_draft(draft, title),
                parse_mode="HTML",
                reply_markup=_draft_keyboard(draft.id),
                disable_web_page_preview=True,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("Failed to send draft %s: %s", draft.id, exc)

    # --- handler registration ----------------------------------------------

    def _register(self) -> None:
        router = Router()

        @router.message(CommandStart())
        @router.message(Command("help"))
        async def cmd_help(message: Message) -> None:
            if not self._is_owner(message.from_user.id):
                return
            await message.answer(HELP, parse_mode="HTML")

        @router.message(Command("add"))
        async def cmd_add(message: Message) -> None:
            if not self._is_owner(message.from_user.id):
                return
            arg = _command_arg(message.text)
            if not arg:
                await message.answer(
                    "Usage: <code>/add @channel</code>", parse_mode="HTML"
                )
                return
            title = await self.reader.resolve_title(arg)
            if title is None:
                await message.answer(
                    "❌ I couldn't access that channel. Make sure your account "
                    "is subscribed to it and the name is correct."
                )
                return
            added = await self.db.add_channel(arg, title)
            if added:
                await message.answer(
                    f"✅ Now monitoring <b>{html.escape(title)}</b>.\n"
                    f"I'll send you the latest post shortly.",
                    parse_mode="HTML",
                )
            else:
                await self.db.set_channel_title(arg, title)
                await message.answer(
                    f"ℹ️ Already monitoring <b>{html.escape(title)}</b>.",
                    parse_mode="HTML",
                )

        @router.message(Command("remove"))
        async def cmd_remove(message: Message) -> None:
            if not self._is_owner(message.from_user.id):
                return
            arg = _command_arg(message.text)
            if not arg:
                await message.answer(
                    "Usage: <code>/remove @channel</code>", parse_mode="HTML"
                )
                return
            removed = await self.db.remove_channel(arg)
            await message.answer(
                "🗑️ Stopped monitoring it." if removed else "That channel isn't on the list."
            )

        @router.message(Command("list"))
        async def cmd_list(message: Message) -> None:
            if not self._is_owner(message.from_user.id):
                return
            rows = await self.db.list_channels()
            if not rows:
                await message.answer("No channels yet. Add one with /add @channel")
                return
            lines = ["<b>Monitored channels:</b>"]
            for row in rows:
                name = html.escape(row["title"] or row["identifier"])
                lines.append(f"• {name} (<code>{html.escape(row['identifier'])}</code>)")
            await message.answer("\n".join(lines), parse_mode="HTML")

        @router.callback_query(F.data.startswith("approve:"))
        async def cb_approve(callback: CallbackQuery) -> None:
            if not self._is_owner(callback.from_user.id):
                await callback.answer()
                return
            draft_id = int(callback.data.split(":", 1)[1])
            draft = await self.db.get_draft(draft_id)
            if not draft:
                await callback.answer("Draft not found.", show_alert=True)
                return
            await self.db.set_status(draft_id, "approved")
            published = await self._publish(draft)
            await self._finalize(callback, draft_id, "✅ Approved" + (
                " & published." if published else "."
            ))
            await callback.answer("Approved!")

        @router.callback_query(F.data.startswith("reject:"))
        async def cb_reject(callback: CallbackQuery) -> None:
            if not self._is_owner(callback.from_user.id):
                await callback.answer()
                return
            draft_id = int(callback.data.split(":", 1)[1])
            await self.db.set_status(draft_id, "rejected")
            await self._finalize(callback, draft_id, "❌ Rejected.")
            await callback.answer("Rejected.")

        @router.callback_query(F.data.startswith("edit:"))
        async def cb_edit(callback: CallbackQuery) -> None:
            if not self._is_owner(callback.from_user.id):
                await callback.answer()
                return
            draft_id = int(callback.data.split(":", 1)[1])
            self.awaiting_edit[callback.from_user.id] = draft_id
            await callback.message.answer(
                f"✏️ Send me the corrected text for draft #{draft_id}."
            )
            await callback.answer()

        @router.message(F.text & ~F.text.startswith("/"))
        async def on_edit_text(message: Message) -> None:
            if not self._is_owner(message.from_user.id):
                return
            draft_id = self.awaiting_edit.pop(message.from_user.id, None)
            if draft_id is None:
                return  # not in an edit flow — ignore stray text
            await self.db.update_rewritten(draft_id, message.text)
            draft = await self.db.get_draft(draft_id)
            if not draft:
                await message.answer("That draft no longer exists.")
                return
            await message.answer(
                "Updated. Here's the new version:", disable_web_page_preview=True
            )
            await message.answer(
                _format_draft(draft, None),
                parse_mode="HTML",
                reply_markup=_draft_keyboard(draft_id),
                disable_web_page_preview=True,
            )

        self.dp.include_router(router)

    # --- helpers ------------------------------------------------------------

    async def _publish(self, draft: Draft) -> bool:
        """Publish an approved draft to the target channel. Returns success."""
        if not self.config.target_channel:
            return False
        target = self.config.target_channel
        if target.lstrip("-").isdigit():
            target = int(target)  # numeric channel id
        try:
            await self.bot.send_message(
                target, draft.rewritten, disable_web_page_preview=True
            )
            return True
        except Exception as exc:  # noqa: BLE001
            log.exception("Failed to publish draft %s: %s", draft.id, exc)
            await self.bot.send_message(
                self.config.owner_id,
                "⚠️ Approved, but I couldn't publish to the target channel. "
                "Make sure the bot is an admin there with post rights.",
            )
            return False

    async def _finalize(
        self, callback: CallbackQuery, draft_id: int, note: str
    ) -> None:
        """Strip the buttons and append a status line to the draft message."""
        try:
            original = callback.message.html_text
            await callback.message.edit_text(
                f"{original}\n\n<i>{note}</i>",
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception:  # noqa: BLE001 - editing can fail; not critical
            await callback.message.edit_reply_markup(reply_markup=None)

    async def start_polling(self) -> None:
        await self.dp.start_polling(self.bot, handle_signals=False)


def _command_arg(text: str | None) -> str | None:
    if not text:
        return None
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else None
