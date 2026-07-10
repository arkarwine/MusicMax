# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import asyncio

from pyrogram import enums, errors, types


class Feedback:
    """Consistent, optionally transient Telegram feedback."""

    def __init__(self) -> None:
        self.tasks: set[asyncio.Task] = set()

    async def _cleanup_enabled(self, message: types.Message) -> bool:
        if not message.chat or message.chat.type == enums.ChatType.PRIVATE:
            return False
        from anony import db

        return await db.get_feedback_cleanup(message.chat.id)

    def _schedule_delete(self, message: types.Message, delay: int) -> None:
        async def delete_later() -> None:
            await asyncio.sleep(delay)
            try:
                await message.delete()
            except (errors.MessageDeleteForbidden, errors.MessageIdInvalid):
                pass
            except Exception:
                pass

        task = asyncio.create_task(delete_later())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def close(self) -> None:
        for task in list(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()

    async def keep_or_clean(
        self,
        message: types.Message,
        *,
        durable: bool = False,
        error: bool = False,
    ) -> types.Message:
        if not durable and await self._cleanup_enabled(message):
            self._schedule_delete(message, 20 if error else 8)
        return message

    async def send(
        self,
        update: types.Message,
        text: str,
        *,
        durable: bool = False,
        error: bool = False,
        quote: bool = False,
        reply_markup=None,
    ) -> types.Message:
        sent = await update.reply_text(
            text,
            quote=quote,
            reply_markup=reply_markup,
            disable_notification=True,
        )
        return await self.keep_or_clean(sent, durable=durable, error=error)

    async def edit(
        self,
        message: types.Message,
        text: str,
        *,
        durable: bool = False,
        error: bool = False,
        reply_markup=None,
    ) -> types.Message:
        edited = await message.edit_text(text, reply_markup=reply_markup)
        return await self.keep_or_clean(edited, durable=durable, error=error)

    @staticmethod
    async def toast(
        query: types.CallbackQuery,
        text: str = "",
        *,
        alert: bool = False,
    ) -> None:
        try:
            await query.answer(text, show_alert=alert)
        except errors.QueryIdInvalid:
            pass
