"""Reusable lifecycle for a Telegram processing message."""

from dataclasses import dataclass

from pyrogram import types


@dataclass(slots=True)
class StatusMessage:
    """Retain and update one existing Telegram processing message."""

    message: types.Message

    @classmethod
    async def begin(
        cls,
        source: types.Message,
        text: str,
        *,
        reply_markup=None,
        disable_notification: bool | None = None,
    ) -> "StatusMessage":
        kwargs = {}
        if reply_markup is not None:
            kwargs["reply_markup"] = reply_markup
        if disable_notification is not None:
            kwargs["disable_notification"] = disable_notification
        return cls(await source.reply_text(text, **kwargs))

    @property
    def id(self) -> int:
        return self.message.id

    async def update(self, text: str, *, reply_markup=None) -> types.Message:
        return await self.message.edit_text(text, reply_markup=reply_markup)

    async def edit_media(self, media, *, reply_markup=None) -> types.Message:
        return await self.message.edit_media(media=media, reply_markup=reply_markup)

    async def remove(self) -> None:
        await self.message.delete()
