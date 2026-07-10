# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import asyncio
from pathlib import Path

from pyrogram import enums, errors, types

from anony import app, config, db, logger, queue, yt
from anony.helpers import utils


async def _prime_assistant_peer(client, chat_id: int, username: str | None) -> bool:
    """Ensure the assistant session knows the chat before PyTgCalls uses its ID."""
    identifiers = [f"@{username}", chat_id] if username else [chat_id]
    for identifier in identifiers:
        try:
            await client.get_chat(identifier)
            await client.resolve_peer(chat_id)
            return True
        except errors.PeerIdInvalid:
            continue
        except Exception:
            logger.debug(
                "Assistant peer lookup failed for %s via %s",
                chat_id,
                identifier,
                exc_info=True,
            )

    try:
        async for dialog in client.get_dialogs():
            if dialog.chat.id == chat_id:
                await client.resolve_peer(chat_id)
                return True
    except Exception:
        logger.debug(
            "Assistant dialog refresh failed for chat %s", chat_id, exc_info=True
        )
    return False


async def _invite_assistant(client, m: types.Message) -> bool:
    chat_id = m.chat.id
    if m.chat.username:
        invite_link = f"@{m.chat.username}"
    else:
        try:
            chat = await app.get_chat(chat_id)
            invite_link = chat.invite_link or await app.export_chat_invite_link(chat_id)
        except errors.ChatAdminRequired:
            await m.reply_text(m.lang["admin_required"])
            return False
        except Exception:
            logger.exception("Could not create an assistant invite for chat %s", chat_id)
            await m.reply_text(m.lang["play_invite_error"].format("Invite unavailable"))
            return False

    status = await m.reply_text(m.lang["play_invite"].format(app.name))
    try:
        await client.join_chat(invite_link)
    except errors.UserAlreadyParticipant:
        pass
    except errors.InviteRequestSent:
        try:
            await app.approve_chat_join_request(chat_id, client.id)
        except errors.HideRequesterMissing:
            pass
        except Exception:
            logger.exception(
                "Could not approve assistant join request for chat %s", chat_id
            )
            await status.edit_text(
                m.lang["play_invite_error"].format("Approval unavailable")
            )
            return False
    except Exception:
        logger.exception("Assistant could not join chat %s", chat_id)
        await status.edit_text(m.lang["play_invite_error"].format("Join unavailable"))
        return False

    for _ in range(5):
        if await _prime_assistant_peer(client, chat_id, m.chat.username):
            await status.delete()
            return True
        await asyncio.sleep(1)

    logger.error("Assistant joined chat %s but could not resolve its peer", chat_id)
    await status.edit_text(m.lang["play_peer_error"])
    return False


async def ensure_assistant(m: types.Message) -> bool:
    chat_id = m.chat.id
    client = await db.get_client(chat_id)
    needs_invite = False
    try:
        member = await app.get_chat_member(chat_id, client.id)
        if member.status in [
            enums.ChatMemberStatus.BANNED,
            enums.ChatMemberStatus.RESTRICTED,
        ]:
            try:
                await app.unban_chat_member(chat_id=chat_id, user_id=client.id)
            except Exception:
                await m.reply_text(
                    m.lang["play_banned"].format(
                        app.name,
                        client.id,
                        client.mention,
                        f"@{client.username}" if client.username else None,
                    )
                )
                return False
            needs_invite = True
        elif member.status == enums.ChatMemberStatus.LEFT:
            needs_invite = True
    except errors.ChatAdminRequired:
        await m.reply_text(m.lang["admin_required"])
        return False
    except (errors.UserNotParticipant, errors.PeerIdInvalid):
        needs_invite = True

    if needs_invite:
        return await _invite_assistant(client, m)
    if not await _prime_assistant_peer(client, chat_id, m.chat.username):
        logger.warning("Assistant could not resolve peer for chat %s", chat_id)
        await m.reply_text(m.lang["play_peer_error"])
        return False
    return True


async def recover_playback(m: types.Message) -> bool:
    from anony import anon
    from anony.helpers import Track

    media = queue.get_current(m.chat.id)
    if not media or not await ensure_assistant(m):
        return False

    sent = await m.reply_text(m.lang["recovery_resuming"])
    remote_file = bool(
        media.file_path and media.file_path.startswith(("http://", "https://"))
    )
    if not remote_file and (
        not media.file_path or not Path(media.file_path).exists()
    ):
        if isinstance(media, Track):
            media.file_path = await yt.download(media.id, video=media.video)
        if not media.file_path:
            await db.mark_playback_waiting(m.chat.id, media.time)
            await sent.edit_text(m.lang["recovery_file_missing"])
            return False

    media.message_id = sent.id
    await anon.play_media(
        m.chat.id,
        sent,
        media,
        seek_time=media.time,
        recovering=True,
    )
    return await db.get_call(m.chat.id)


def checkUB(play):
    async def wrapper(_, m: types.Message):
        if not m.from_user:
            return await m.reply_text(m.lang["play_user_invalid"])

        chat_id = m.chat.id
        if m.chat.type != enums.ChatType.SUPERGROUP:
            await m.reply_text(m.lang["play_chat_invalid"])
            return await app.leave_chat(chat_id)

        arguments = m.command[1:]
        query_arguments = [arg for arg in arguments if arg not in {"-f", "-v"}]
        if not m.reply_to_message and not query_arguments:
            return await m.reply_text(m.lang["play_usage"])

        if len(queue.get_queue(chat_id)) >= config.QUEUE_LIMIT:
            return await m.reply_text(m.lang["play_queue_full"].format(config.QUEUE_LIMIT))

        force = m.command[0].endswith("force") or "-f" in arguments
        video = (m.command[0].startswith("v") or "-v" in arguments) and config.VIDEO_PLAY
        url = utils.get_url(m)
        if url and yt.invalid(url):
            return await m.reply_text(m.lang["play_not_found"].format(config.SUPPORT_CHAT))
        m3u8 = url and not yt.valid(url)

        play_mode = await db.get_play_mode(chat_id)
        if play_mode or force:
            adminlist = await db.get_admins(chat_id)
            if (
                m.from_user.id not in adminlist
                and not await db.is_auth(chat_id, m.from_user.id)
                and m.from_user.id not in app.sudoers
            ):
                return await m.reply_text(m.lang["play_admin"])

        if chat_id not in db.active_calls:
            if not await ensure_assistant(m):
                return

        if await db.get_cmd_delete(chat_id):
            try:
                await m.delete()
            except Exception:
                pass

        return await play(_, m, force, m3u8, video, url)

    return wrapper
