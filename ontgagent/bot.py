"""Бот подтверждения: присылает вам каждый переписанный черновик с кнопками
одобрить / изменить / отклонить, обрабатывает команды управления каналами и
публикует одобренные посты в ваш целевой канал.
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
    "Я слежу за каналами, которые вы добавите, переписываю их свежие посты "
    "в вашем стиле и присылаю каждый черновик сюда на подтверждение.\n\n"
    "<b>Команды</b>\n"
    "/add <code>@канал</code> — начать следить за каналом\n"
    "/remove <code>@канал</code> — перестать следить за каналом\n"
    "/list — показать список каналов\n"
    "/help — показать это сообщение\n\n"
    "Когда приходит черновик, используйте кнопки:\n"
    "✅ Одобрить — опубликовать (или отметить одобренным)\n"
    "✏️ Изменить — прислать свой вариант текста\n"
    "❌ Отклонить — удалить черновик"
)


def _draft_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Одобрить", callback_data=f"approve:{draft_id}"
                ),
                InlineKeyboardButton(
                    text="✏️ Изменить", callback_data=f"edit:{draft_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить", callback_data=f"reject:{draft_id}"
                ),
            ]
        ]
    )


def _format_draft(draft: Draft, channel_title: str | None) -> str:
    source = html.escape(channel_title or draft.channel)
    body = html.escape(draft.rewritten)
    return f"📝 <b>Черновик #{draft.id}</b> — из <b>{source}</b>\n\n{body}"


class ConfirmationBot:
    def __init__(self, config: Config, db: Database, reader: Reader):
        self.config = config
        self.db = db
        self.reader = reader
        self.bot = Bot(token=config.bot_token)
        self.dp = Dispatcher()
        # owner_id -> draft_id, который сейчас редактируется
        self.awaiting_edit: dict[int, int] = {}
        self._register()

    # --- проверки -----------------------------------------------------------

    def _is_owner(self, user_id: int | None) -> bool:
        return user_id == self.config.owner_id

    # --- публичный метод для цикла опроса ------------------------------------

    async def send_draft(self, draft: Draft) -> None:
        """Отправить свежесозданный черновик владельцу на подтверждение."""
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
            log.exception("Не удалось отправить черновик %s: %s", draft.id, exc)

    # --- регистрация обработчиков -------------------------------------------

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
                    "Использование: <code>/add @канал</code>", parse_mode="HTML"
                )
                return
            title = await self.reader.resolve_title(arg)
            if title is None:
                await message.answer(
                    "❌ Не получилось открыть этот канал. Убедитесь, что ваш "
                    "аккаунт подписан на него и название указано верно."
                )
                return
            added = await self.db.add_channel(arg, title)
            if added:
                await message.answer(
                    f"✅ Теперь слежу за <b>{html.escape(title)}</b>.\n"
                    f"Скоро пришлю последний пост.",
                    parse_mode="HTML",
                )
            else:
                await self.db.set_channel_title(arg, title)
                await message.answer(
                    f"ℹ️ Уже слежу за <b>{html.escape(title)}</b>.",
                    parse_mode="HTML",
                )

        @router.message(Command("remove"))
        async def cmd_remove(message: Message) -> None:
            if not self._is_owner(message.from_user.id):
                return
            arg = _command_arg(message.text)
            if not arg:
                await message.answer(
                    "Использование: <code>/remove @канал</code>", parse_mode="HTML"
                )
                return
            removed = await self.db.remove_channel(arg)
            await message.answer(
                "🗑️ Перестал следить за ним."
                if removed
                else "Этого канала нет в списке."
            )

        @router.message(Command("list"))
        async def cmd_list(message: Message) -> None:
            if not self._is_owner(message.from_user.id):
                return
            rows = await self.db.list_channels()
            if not rows:
                await message.answer(
                    "Пока нет каналов. Добавьте: /add @канал"
                )
                return
            lines = ["<b>Отслеживаемые каналы:</b>"]
            for row in rows:
                name = html.escape(row["title"] or row["identifier"])
                lines.append(
                    f"• {name} (<code>{html.escape(row['identifier'])}</code>)"
                )
            await message.answer("\n".join(lines), parse_mode="HTML")

        @router.callback_query(F.data.startswith("approve:"))
        async def cb_approve(callback: CallbackQuery) -> None:
            if not self._is_owner(callback.from_user.id):
                await callback.answer()
                return
            draft_id = int(callback.data.split(":", 1)[1])
            draft = await self.db.get_draft(draft_id)
            if not draft:
                await callback.answer("Черновик не найден.", show_alert=True)
                return
            await self.db.set_status(draft_id, "approved")
            published = await self._publish(draft)
            await self._finalize(
                callback,
                draft_id,
                "✅ Одобрено" + (" и опубликовано." if published else "."),
            )
            await callback.answer("Одобрено!")

        @router.callback_query(F.data.startswith("reject:"))
        async def cb_reject(callback: CallbackQuery) -> None:
            if not self._is_owner(callback.from_user.id):
                await callback.answer()
                return
            draft_id = int(callback.data.split(":", 1)[1])
            await self.db.set_status(draft_id, "rejected")
            await self._finalize(callback, draft_id, "❌ Отклонено.")
            await callback.answer("Отклонено.")

        @router.callback_query(F.data.startswith("edit:"))
        async def cb_edit(callback: CallbackQuery) -> None:
            if not self._is_owner(callback.from_user.id):
                await callback.answer()
                return
            draft_id = int(callback.data.split(":", 1)[1])
            self.awaiting_edit[callback.from_user.id] = draft_id
            await callback.message.answer(
                f"✏️ Пришлите исправленный текст для черновика #{draft_id}."
            )
            await callback.answer()

        @router.message(F.text & ~F.text.startswith("/"))
        async def on_edit_text(message: Message) -> None:
            if not self._is_owner(message.from_user.id):
                return
            draft_id = self.awaiting_edit.pop(message.from_user.id, None)
            if draft_id is None:
                return  # не в режиме редактирования — игнорируем случайный текст
            await self.db.update_rewritten(draft_id, message.text)
            draft = await self.db.get_draft(draft_id)
            if not draft:
                await message.answer("Этого черновика больше нет.")
                return
            await message.answer("Обновил. Вот новая версия:")
            await message.answer(
                _format_draft(draft, None),
                parse_mode="HTML",
                reply_markup=_draft_keyboard(draft_id),
                disable_web_page_preview=True,
            )

        self.dp.include_router(router)

    # --- вспомогательные методы ---------------------------------------------

    async def _publish(self, draft: Draft) -> bool:
        """Опубликовать одобренный черновик в целевой канал. Возвращает успех."""
        if not self.config.target_channel:
            return False
        target = self.config.target_channel
        if target.lstrip("-").isdigit():
            target = int(target)  # числовой id канала
        try:
            await self.bot.send_message(
                target, draft.rewritten, disable_web_page_preview=True
            )
            return True
        except Exception as exc:  # noqa: BLE001
            log.exception("Не удалось опубликовать черновик %s: %s", draft.id, exc)
            await self.bot.send_message(
                self.config.owner_id,
                "⚠️ Одобрено, но не удалось опубликовать в целевой канал. "
                "Убедитесь, что бот — админ канала с правом публикации.",
            )
            return False

    async def _finalize(
        self, callback: CallbackQuery, draft_id: int, note: str
    ) -> None:
        """Убрать кнопки и дописать статус к сообщению с черновиком."""
        try:
            original = callback.message.html_text
            await callback.message.edit_text(
                f"{original}\n\n<i>{note}</i>",
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception:  # noqa: BLE001 - редактирование может не удаться; не критично
            await callback.message.edit_reply_markup(reply_markup=None)

    async def start_polling(self) -> None:
        await self.dp.start_polling(self.bot, handle_signals=False)


def _command_arg(text: str | None) -> str | None:
    if not text:
        return None
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else None
