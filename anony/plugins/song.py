# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import time
from html import escape

from pyrogram import filters, types

from anony import app, config, lang, logger, thumb, yt
from anony.ui import StatusMessage


_song_prompts: dict[tuple[int, int], tuple[int, float]] = {}
_PROMPT_TTL = 300


def _reply_input(message: types.Message) -> str | None:
    reply = message.reply_to_message
    if not reply:
        return None
    return (reply.text or reply.caption or "").strip() or None


def _command_input(message: types.Message) -> str | None:
    if len(message.command) > 1:
        return " ".join(message.command[1:]).strip() or None
    return _reply_input(message)


async def _send_existing_audio(message: types.Message, audio) -> None:
    await app.send_audio(
        chat_id=message.chat.id,
        audio=audio.file_id,
        title=audio.title,
        performer=audio.performer,
        duration=audio.duration,
        reply_to_message_id=message.id,
        disable_notification=True,
    )


async def _deliver_song(message: types.Message, query: str | None) -> None:
    reply = message.reply_to_message
    if not query and reply and reply.audio:
        return await _send_existing_audio(message, reply.audio)
    if not query:
        return await message.reply_text(message.lang["song_input_invalid"])

    status = await StatusMessage.begin(message, message.lang["song_searching"])
    try:
        track = await yt.search(query, status.id)
        if not track:
            return await status.update(message.lang["song_not_found"])
        if track.duration_sec > config.DURATION_LIMIT:
            return await status.update(
                message.lang["song_duration_limit"].format(
                    config.DURATION_LIMIT // 60
                )
            )

        await status.update(message.lang["song_downloading"])
        song = await yt.download_song(track.id)
        if not song:
            return await status.update(message.lang["song_failed"])

        await status.update(message.lang["song_uploading"])
        cover = await thumb.audio_cover(track)
        await app.send_audio(
            chat_id=message.chat.id,
            audio=song["file_path"],
            caption=message.lang["song_caption"].format(
                escape(song["url"], quote=True)
            ),
            title=song["title"][:64],
            performer=song["performer"][:64],
            duration=song["duration"],
            thumb=cover,
            reply_to_message_id=message.id,
            disable_notification=True,
        )
        try:
            await status.remove()
        except Exception:
            pass
    except Exception:
        logger.exception("Could not deliver a requested song")
        await status.update(message.lang["song_failed"])


@app.on_message(filters.command(["song"]) & ~app.bl_users)
@lang.language()
async def _song(_, message: types.Message):
    if not message.from_user:
        return
    query = _command_input(message)
    if query or (message.reply_to_message and message.reply_to_message.audio):
        return await _deliver_song(message, query)

    now = time.monotonic()
    for key, (_, expires) in list(_song_prompts.items()):
        if expires <= now:
            _song_prompts.pop(key, None)

    prompt = await message.reply_text(
        message.lang["song_prompt"],
        reply_markup=types.ForceReply(
            selective=True,
            placeholder=message.lang["song_prompt_placeholder"],
        ),
    )
    _song_prompts[(message.chat.id, prompt.id)] = (
        message.from_user.id,
        now + _PROMPT_TTL,
    )


@app.on_message(filters.reply & ~app.bl_users, group=1)
@lang.language()
async def _song_prompt_reply(_, message: types.Message):
    if not message.reply_to_message or not message.from_user:
        return
    key = (message.chat.id, message.reply_to_message.id)
    flow = _song_prompts.get(key)
    if not flow:
        return
    user_id, expires = flow
    if message.from_user.id != user_id:
        return
    _song_prompts.pop(key, None)
    if expires <= time.monotonic():
        return await message.reply_text(message.lang["song_prompt_expired"])
    try:
        await message.reply_to_message.delete()
    except Exception:
        pass
    query = (message.text or message.caption or "").strip() or None
    await _deliver_song(message, query)
