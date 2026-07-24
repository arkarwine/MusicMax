"""Telegram delivery for the playback card.

Voice transport does not belong in the same module as photo fallback,
template rendering, and artwork refresh. Keep this boundary deliberately
boring: render once, try the available artwork, and preserve real newlines.
"""

from __future__ import annotations

import asyncio

from pyrogram import enums
from pyrogram.errors import (
    BadRequest,
    ChatSendMediaForbidden,
    ChatSendPhotosForbidden,
    MessageIdInvalid,
)
from pyrogram.types import InputMediaPhoto, Message

from anony import app, config, db, logger, queue, thumb
from anony.core.play_message import render_play_message
from anony.helpers import Media, Track, buttons


async def _deliver(
    chat_id: int,
    message: Message,
    media: Media | Track,
    text: str,
    keyboard,
    override,
    artwork,
) -> None:
    candidates = []
    for candidate in (artwork, override):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    candidates.append(None)

    async def send(*, edit: bool):
        last_error = None
        for candidate in candidates:
            try:
                if edit and candidate:
                    return await app._edit_plain_media(
                        chat_id,
                        message.id,
                        InputMediaPhoto(
                            media=candidate,
                            caption=text,
                            parse_mode=enums.ParseMode.HTML,
                        ),
                        reply_markup=keyboard,
                    )
                if edit:
                    return await app._edit_plain_message(
                        chat_id,
                        message.id,
                        text,
                        parse_mode=enums.ParseMode.HTML,
                        reply_markup=keyboard,
                    )
                if candidate:
                    return await app._send_plain_photo(
                        chat_id=chat_id,
                        photo=candidate,
                        caption=text,
                        parse_mode=enums.ParseMode.HTML,
                        reply_markup=keyboard,
                    )
                return await app._send_plain_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=enums.ParseMode.HTML,
                    reply_markup=keyboard,
                )
            except MessageIdInvalid:
                raise
            except (
                BadRequest,
                ChatSendMediaForbidden,
                ChatSendPhotosForbidden,
            ) as exc:
                last_error = exc
        raise RuntimeError("Could not deliver the play card") from last_error

    try:
        sent = await send(edit=True)
    except MessageIdInvalid:
        sent = await send(edit=False)
    media.message_id = sent.id


async def show_play_card(
    chat_id: int,
    message: Message,
    media: Media | Track,
    language: dict,
    language_code: str,
    artwork_source,
) -> None:
    default_template = language["play_message_template"]
    rendered = render_play_message(
        config.play_message_template(language_code) or default_template,
        default_template,
        title=media.title or language["unknown_track"],
        url=media.url,
        duration=media.duration or "--:--",
        requester=media.user or language["someone"],
    )
    if rendered.used_default:
        logger.warning(
            "Custom %s /play template failed at render time; "
            "using the localized default.",
            language_code,
        )

    artwork = (
        artwork_source
        if config.THUMB_GEN
        and artwork_source
        and artwork_source != config.DEFAULT_THUMB
        else None
    )
    override = None
    if artwork is None:
        override_url = config.play_image_url()
        if override_url:
            override = await thumb.play_image(override_url)
            if override is None:
                logger.warning("Could not cache PLAY_IMAGE; using its remote URL.")
                override = override_url
        if override is None and artwork_source:
            override = artwork_source

    # Telegram rich paragraph blocks collapse whitespace on some clients.
    # Standard captions preserve the template's real newline characters.
    await _deliver(
        chat_id,
        message,
        media,
        rendered.fallback_html,
        buttons.controls(chat_id, playing=True),
        override,
        artwork,
    )


async def refresh_play_card_artwork(
    chat_id: int,
    message_id: int,
    media: Media | Track,
    language: dict,
    language_code: str,
    artwork_task: asyncio.Task,
) -> None:
    try:
        artwork = await artwork_task
        current = queue.get_current(chat_id)
        if (
            not artwork
            or current is None
            or getattr(current, "id", None) != getattr(media, "id", None)
            or not await db.get_call(chat_id)
        ):
            return
        card_id = getattr(media, "message_id", 0) or message_id
        if not card_id:
            return
        message = await app.get_messages(chat_id, card_id)
        if message:
            await show_play_card(
                chat_id,
                message,
                media,
                language,
                language_code,
                artwork,
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.debug(
            "Could not refresh play card artwork in chat %s",
            chat_id,
            exc_info=True,
        )
