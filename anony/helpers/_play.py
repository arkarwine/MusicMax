# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import asyncio

from pyrogram import enums, errors, types

from anony import anon, app, config, db, logger, queue, userbot, yt
from anony.helpers import feedback, utils


async def _prime_assistant_peer(client, chat_id: int, username: str | None) -> bool:
    """Ensure the assistant session knows the chat before PyTgCalls uses its ID."""
    try:
        await client.resolve_peer(chat_id)
        return True
    except errors.PeerIdInvalid:
        pass
    except Exception:
        logger.debug(
            "Assistant peer cache lookup failed for %s",
            chat_id,
            exc_info=True,
        )

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


async def _invite_assistant(client, m: types.Message, status) -> str:
    chat_id = m.chat.id
    temporary_link = None

    async def fresh_invite() -> str:
        nonlocal temporary_link
        invite = await app.create_chat_invite_link(
            chat_id,
            name="Music assistant",
            member_limit=1,
        )
        temporary_link = invite.invite_link
        return temporary_link

    async def revoke_invite() -> None:
        if not temporary_link:
            return
        try:
            await app.revoke_chat_invite_link(chat_id, temporary_link)
        except Exception:
            logger.debug(
                "Could not revoke temporary invite for chat %s",
                chat_id,
                exc_info=True,
            )

    if m.chat.username:
        invite_link = f"@{m.chat.username}"
    else:
        try:
            invite_link = await fresh_invite()
        except errors.ChatAdminRequired:
            return "invite_admin_required"
        except Exception:
            logger.exception("Could not create an assistant invite for chat %s", chat_id)
            return "invite_failed"

    invite_text = m.lang["play_invite"].format(client.name)
    if status.text != invite_text:
        try:
            await status.edit_text(invite_text)
        except errors.MessageNotModified:
            pass
    join_pending = False
    try:
        try:
            await client.join_chat(invite_link)
        except (errors.InviteHashExpired, errors.InviteHashInvalid):
            logger.info("Refreshing an invalid invite link for chat %s", chat_id)
            invite_link = await fresh_invite()
            await client.join_chat(invite_link)
    except errors.UserAlreadyParticipant:
        pass
    except errors.InviteRequestSent:
        join_pending = True
        for _ in range(5):
            try:
                await app.approve_chat_join_request(chat_id, client.id)
                join_pending = False
                break
            except (errors.HideRequesterMissing, errors.UserNotParticipant):
                await asyncio.sleep(1)
            except Exception:
                logger.exception(
                    "Could not approve assistant join request for chat %s", chat_id
                )
                break
    except errors.ChatAdminRequired:
        await revoke_invite()
        return "join_admin_required"
    except Exception:
        logger.exception("Assistant could not join chat %s", chat_id)
        await revoke_invite()
        return "join_failed"

    for _ in range(5):
        if await _prime_assistant_peer(client, chat_id, m.chat.username):
            await status.delete()
            await revoke_invite()
            return "ready"
        await asyncio.sleep(1)

    if join_pending:
        logger.warning("Assistant join request is still pending in chat %s", chat_id)
        result = "join_pending"
    else:
        logger.error("Assistant could not resolve chat %s after joining", chat_id)
        result = "peer_failed"
    await revoke_invite()
    return result


async def assistant_membership(
    chat_id: int, username: str | None, client=None
) -> tuple[object, str]:
    """Return the selected assistant and its membership state."""
    if client is None:
        client = await db.get_client(chat_id)
    try:
        member = await app.get_chat_member(chat_id, client.id)
        if member.status == enums.ChatMemberStatus.BANNED:
            return client, "banned"
        if member.status == enums.ChatMemberStatus.RESTRICTED and not getattr(
            member, "is_member", False
        ):
            return client, "banned"
        if member.status in {
            enums.ChatMemberStatus.OWNER,
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.MEMBER,
        } or (
            member.status == enums.ChatMemberStatus.RESTRICTED
            and getattr(member, "is_member", False)
        ):
            return (
                (client, "ready")
                if await _prime_assistant_peer(client, chat_id, username)
                else (client, "unknown")
            )
    except (errors.UserNotParticipant, errors.PeerIdInvalid):
        pass
    except Exception:
        logger.debug(
            "Bot could not inspect assistant %s in chat %s",
            client.id,
            chat_id,
            exc_info=True,
        )

    if not await _prime_assistant_peer(client, chat_id, username):
        return client, "absent"

    try:
        member = await client.get_chat_member(chat_id, client.id)
    except errors.UserNotParticipant:
        return client, "absent"
    except errors.PeerIdInvalid:
        return client, "unknown"

    if member.status in {
        enums.ChatMemberStatus.OWNER,
        enums.ChatMemberStatus.ADMINISTRATOR,
        enums.ChatMemberStatus.MEMBER,
    }:
        return client, "ready"
    if member.status == enums.ChatMemberStatus.RESTRICTED and getattr(
        member, "is_member", False
    ):
        return client, "ready"
    if member.status in {
        enums.ChatMemberStatus.BANNED,
        enums.ChatMemberStatus.RESTRICTED,
        enums.ChatMemberStatus.LEFT,
    }:
        return client, "absent"
    return client, "unknown"


async def ensure_assistant(m: types.Message) -> bool:
    chat_id = m.chat.id
    available_slots = [
        slot
        for slot in sorted(userbot.accepting_slots)
        if slot in anon.clients
    ]
    if not available_slots:
        if getattr(m, "outgoing", False):
            await feedback.error_edit(m, m.lang["play_session_required"])
        else:
            await feedback.error(m, m.lang["play_session_required"])
        return False

    selected = await db.get_client(chat_id)
    selected_slot = next(
        slot for slot, client in userbot.clients.items() if client is selected
    )
    slots = [selected_slot] + [
        slot
        for slot in available_slots
        if slot != selected_slot
    ]
    status = None
    results = []

    for slot in slots:
        client = userbot.clients[slot]
        client, membership = await assistant_membership(
            chat_id, m.chat.username, client
        )

        if membership == "ready":
            await db.set_assistant(chat_id, slot)
            if status:
                await status.delete()
            return True

        if membership == "unknown":
            results.append("peer_failed")
            continue

        if membership == "banned":
            try:
                await app.unban_chat_member(chat_id=chat_id, user_id=client.id)
            except errors.ChatAdminRequired:
                results.append("banned_unban_required")
                continue
            except Exception:
                logger.exception(
                    "Could not unban assistant %s in chat %s", client.id, chat_id
                )
                results.append("unban_failed")
                continue
        else:
            try:
                await app.unban_chat_member(chat_id=chat_id, user_id=client.id)
            except errors.UserNotParticipant:
                pass
            except errors.ChatAdminRequired:
                # The account was not confirmed banned. Continue with the join;
                # invite permissions may still be sufficient.
                pass
            except Exception:
                logger.debug(
                    "Assistant %s did not require unbanning in chat %s",
                    client.id,
                    chat_id,
                    exc_info=True,
                )

        if status is None:
            status = await m.reply_text(m.lang["play_invite"].format(client.name))
        result = await _invite_assistant(client, m, status)
        if result == "ready":
            await db.set_assistant(chat_id, slot)
            return True
        results.append(result)
        if result == "invite_admin_required":
            break

    if status is None:
        status = await m.reply_text(m.lang["play_invite"].format(app.name))
    if results and all(result == "banned_unban_required" for result in results):
        await status.edit_text(m.lang["play_unban_required"])
    elif "invite_admin_required" in results or "join_admin_required" in results:
        await status.edit_text(m.lang["admin_required"])
    elif "join_pending" in results:
        await status.edit_text(m.lang["play_invite_pending"])
    elif "peer_failed" in results:
        await status.edit_text(m.lang["play_peer_error"])
    else:
        await status.edit_text(
            m.lang["play_invite_error"].format("All assistants unavailable")
        )
    return False


async def recover_playback(m: types.Message) -> bool:
    from anony.core.recovery import recovery

    return await recovery.play(m.chat.id, source=m)


def checkUB(play):
    async def wrapper(_, m: types.Message):
        if not m.from_user:
            return await feedback.error(m, m.lang["play_user_invalid"])

        chat_id = m.chat.id
        if m.chat.type != enums.ChatType.SUPERGROUP:
            await m.reply_text(m.lang["play_chat_invalid"])
            return await app.leave_chat(chat_id)

        assigned = db.assistant.get(chat_id)
        if (
            chat_id in db.active_calls
            and assigned is not None
            and not userbot.is_accepting(assigned)
        ):
            return await feedback.warning(m, m.lang["play_session_locked"])

        arguments = m.command[1:]
        query_arguments = [
            arg for arg in arguments if arg not in {"-f", "-v", "-a"}
        ]
        if not m.reply_to_message and not query_arguments:
            return await feedback.error(m, m.lang["play_usage"])

        if len(queue.get_queue(chat_id)) >= config.QUEUE_LIMIT:
            return await feedback.error(
                m,
                m.lang["play_queue_full"].format(config.QUEUE_LIMIT),
            )

        force = m.command[0].endswith("force") or "-f" in arguments
        explicit_audio = "-a" in arguments
        explicit_video = m.command[0].startswith("v") or "-v" in arguments
        default_video = await db.get_default_video(chat_id)
        video = (
            not explicit_audio
            and (explicit_video or default_video)
            and config.VIDEO_PLAY
        )
        url = utils.get_url(m)
        if url and yt.invalid(url):
            return await feedback.error(
                m,
                m.lang["play_not_found"].format(config.SUPPORT_CHAT),
            )
        m3u8 = url and not yt.valid(url)

        play_mode = await db.get_play_mode(chat_id)
        if play_mode or force:
            adminlist = await db.get_admins(chat_id)
            if (
                m.from_user.id not in adminlist
                and not await db.is_auth(chat_id, m.from_user.id)
                and m.from_user.id not in app.sudoers
            ):
                return await feedback.error(m, m.lang["play_admin"])

        if await db.get_cmd_delete(chat_id):
            try:
                await m.delete()
            except Exception:
                pass

        return await play(_, m, force, m3u8, video, url)

    return wrapper
