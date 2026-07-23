# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from secrets import token_urlsafe
from time import monotonic, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pyrogram import enums, errors, filters, types

from anony import app, config, db, lang, logger, supervisor
from anony.helpers import buttons, feedback
from anony.ui import callbacks


broadcasting = asyncio.Lock()
_pending: dict[str, "BroadcastDraft"] = {}


@dataclass
class BroadcastDraft:
    token: str
    creator_id: int
    source_chat_id: int
    source_message_id: int
    source_media_group_id: str | None
    include_users: bool = False
    include_groups: bool = True
    copy_mode: bool = True
    daily: bool = False
    daily_minute: int = 0
    repeat_limit: int | None = None

    @property
    def selected(self) -> bool:
        return self.include_users or self.include_groups

    @property
    def mode_key(self) -> str:
        return "gcast_mode_copy" if self.copy_mode else "gcast_mode_forward"


def _tz():
    if config.PROJECT_TIMEZONE in {"Asia/Yangon", "Asia/Rangoon"}:
        return timezone(timedelta(hours=6, minutes=30), "Asia/Yangon")
    try:
        return ZoneInfo(config.PROJECT_TIMEZONE)
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=6, minutes=30), "Asia/Yangon")


def _minute_label(minute: int) -> str:
    minute %= 1440
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _repeat_label(_lang: dict, repeat_limit: int | None) -> str:
    if repeat_limit is None:
        return _lang["gcast_repeat_forever"]
    return _lang["gcast_repeat_times"].format(repeat_limit)


def _audience_label(include_users: bool, include_groups: bool) -> str:
    if include_users and include_groups:
        return "All"
    if include_users:
        return "Users"
    if include_groups:
        return "Groups"
    return "None"


def _next_daily_epoch(minute: int, tz: ZoneInfo, *, after: datetime | None = None) -> int:
    now = after or datetime.now(tz)
    candidate = now.replace(
        hour=minute // 60,
        minute=minute % 60,
        second=0,
        microsecond=0,
    )
    if candidate <= now:
        candidate += timedelta(days=1)
    return int(candidate.astimezone(timezone.utc).timestamp())


async def _counts(draft: BroadcastDraft) -> tuple[int, int, int]:
    users = len(await db.get_users()) if draft.include_users else 0
    groups = len(await db.get_chats()) if draft.include_groups else 0
    return users, groups, users + groups


def _dashboard_text(_lang: dict, draft: BroadcastDraft, users: int, groups: int) -> str:
    total = users + groups
    lines = [
        _lang["gcast_dashboard"],
        "",
        _lang["gcast_dashboard_audience"].format(
            _lang["on"] if draft.include_users else _lang["off"],
            _lang["on"] if draft.include_groups else _lang["off"],
            total,
        ),
        "",
    ]
    if draft.daily:
        delivery = _lang["gcast_dashboard_delivery_daily"].format(
            _lang[draft.mode_key],
            _lang["on"],
            _minute_label(draft.daily_minute),
            _repeat_label(_lang, draft.repeat_limit),
        )
    else:
        delivery = _lang["gcast_dashboard_delivery_now"].format(
            _lang[draft.mode_key],
            _lang["off"],
        )
    lines.append(delivery)
    return "\n".join(lines)


def _dashboard_markup(_lang: dict, draft: BroadcastDraft) -> types.InlineKeyboardMarkup:
    style_on = enums.ButtonStyle.SUCCESS
    token = draft.token
    rows = [
        [
            buttons.ikb(
                text=_lang["gcast_users_button"].format(
                    _lang["on"] if draft.include_users else _lang["off"]
                ),
                callback_data=callbacks.broadcast("toggle", token, "users"),
                style=style_on if draft.include_users else enums.ButtonStyle.DEFAULT,
            ),
            buttons.ikb(
                text=_lang["gcast_groups_button"].format(
                    _lang["on"] if draft.include_groups else _lang["off"]
                ),
                callback_data=callbacks.broadcast("toggle", token, "groups"),
                style=style_on if draft.include_groups else enums.ButtonStyle.DEFAULT,
            ),
        ],
        [
            buttons.ikb(
                text=_lang["gcast_daily_button"].format(
                    _lang["on"] if draft.daily else _lang["off"]
                ),
                callback_data=callbacks.broadcast("toggle", token, "daily"),
                style=style_on if draft.daily else enums.ButtonStyle.DEFAULT,
            )
        ],
        [
            buttons.ikb(
                text=_lang["gcast_mode_button"].format(_lang[draft.mode_key]),
                callback_data=callbacks.broadcast("toggle", token, "mode"),
            )
        ],
    ]
    if draft.daily:
        rows.append([
            buttons.ikb(
                text=_lang["gcast_time_button"].format(_minute_label(draft.daily_minute)),
                callback_data=callbacks.broadcast("time", token),
            ),
            buttons.ikb(
                text=_lang["gcast_repeat_button"].format(
                    _repeat_label(_lang, draft.repeat_limit)
                ),
                callback_data=callbacks.broadcast("repeat", token),
            ),
        ])
    rows.append([
        buttons.ikb(
            text=_lang["gcast_send_button"],
            callback_data=callbacks.broadcast("send", token),
            style=enums.ButtonStyle.SUCCESS,
        )
    ])
    return buttons.ikm(rows)


def _time_text(_lang: dict, draft: BroadcastDraft) -> str:
    return _lang["gcast_time_menu"].format(
        config.PROJECT_TIMEZONE,
        _minute_label(draft.daily_minute),
    )


def _time_markup(_lang: dict, token: str) -> types.InlineKeyboardMarkup:
    return buttons.ikm([
        [
            buttons.ikb(text="−1h", callback_data=callbacks.broadcast("timeadd", token, -60)),
            buttons.ikb(text="+1h", callback_data=callbacks.broadcast("timeadd", token, 60)),
        ],
        [
            buttons.ikb(text="−15m", callback_data=callbacks.broadcast("timeadd", token, -15)),
            buttons.ikb(text="+15m", callback_data=callbacks.broadcast("timeadd", token, 15)),
        ],
        [
            buttons.ikb(text="−5m", callback_data=callbacks.broadcast("timeadd", token, -5)),
            buttons.ikb(text="+5m", callback_data=callbacks.broadcast("timeadd", token, 5)),
        ],
        [
            buttons.ikb(text="−1m", callback_data=callbacks.broadcast("timeadd", token, -1)),
            buttons.ikb(text="+1m", callback_data=callbacks.broadcast("timeadd", token, 1)),
        ],
        [buttons.ikb(text=_lang["back"], callback_data=callbacks.broadcast("view", token))],
    ])


def _repeat_text(_lang: dict, draft: BroadcastDraft) -> str:
    return _lang["gcast_repeat_menu"].format(_repeat_label(_lang, draft.repeat_limit))


def _repeat_markup(_lang: dict, token: str) -> types.InlineKeyboardMarkup:
    return buttons.ikm([
        [
            buttons.ikb(text="−10", callback_data=callbacks.broadcast("repeatadd", token, -10)),
            buttons.ikb(text="+10", callback_data=callbacks.broadcast("repeatadd", token, 10)),
        ],
        [
            buttons.ikb(text="−5", callback_data=callbacks.broadcast("repeatadd", token, -5)),
            buttons.ikb(text="+5", callback_data=callbacks.broadcast("repeatadd", token, 5)),
        ],
        [
            buttons.ikb(text="−1", callback_data=callbacks.broadcast("repeatadd", token, -1)),
            buttons.ikb(text="+1", callback_data=callbacks.broadcast("repeatadd", token, 1)),
        ],
        [buttons.ikb(text=_lang["gcast_repeat_forever"], callback_data=callbacks.broadcast("repeatforever", token))],
        [buttons.ikb(text=_lang["back"], callback_data=callbacks.broadcast("view", token))],
    ])


async def _show_dashboard(message_or_query, draft: BroadcastDraft, _lang: dict):
    users, groups, _ = await _counts(draft)
    text = _dashboard_text(_lang, draft, users, groups)
    markup = _dashboard_markup(_lang, draft)
    if isinstance(message_or_query, types.CallbackQuery):
        return await message_or_query.message.edit_text(text, reply_markup=markup)
    return await message_or_query.reply_text(text, reply_markup=markup)


async def _resolve_album(source_chat_id: int, source_message_id: int):
    try:
        msg = await app.get_messages(source_chat_id, source_message_id)
    except Exception:
        return None, None
    album = None
    if getattr(msg, "media_group_id", None):
        album = sorted(
            await app.get_media_group(source_chat_id, source_message_id),
            key=lambda item: item.id,
        )
    return msg, album


async def _send_to_target(chat_id: int, msg, album, *, copy_mode: bool) -> None:
    if album:
        if copy_mode:
            await msg.copy_media_group(chat_id)
        else:
            await app.forward_messages(
                chat_id=chat_id,
                from_chat_id=msg.chat.id,
                message_ids=[item.id for item in album],
            )
    elif copy_mode:
        await msg.copy(chat_id, reply_markup=msg.reply_markup)
    else:
        await msg.forward(chat_id)


async def _run_broadcast(
    *,
    draft: BroadcastDraft,
    status_message: types.Message | None,
    _lang: dict,
) -> tuple[int, int, Path | None]:
    groups = set(await db.get_chats()) if draft.include_groups else set()
    users = set(await db.get_users()) if draft.include_users else set()
    targets = list(groups | users)
    msg, album = await _resolve_album(draft.source_chat_id, draft.source_message_id)
    if not msg:
        raise RuntimeError("source message is no longer available")

    group_delivered = user_delivered = 0
    group_failed = user_failed = 0
    started = monotonic()
    last_progress_edit = started
    error_path: Path | None = None

    def progress_text(final: bool = False) -> str:
        total_targets = len(groups) + len(users)
        total_delivered = group_delivered + user_delivered
        total_failed = group_failed + user_failed
        key = "gcast_end" if final else "gcast_start"
        args = [
            len(groups), group_delivered, group_failed,
            len(users), user_delivered, user_failed,
            total_targets, total_delivered, total_failed,
            _lang[draft.mode_key],
        ]
        if final:
            elapsed = max(monotonic() - started, 0)
            args.append(f"{elapsed:.1f}s")
        return _lang[key].format(*args)

    if status_message:
        await status_message.edit_text(progress_text())

    for chat in targets:
        delivered = False
        error = None
        for attempt in range(2):
            try:
                await _send_to_target(chat, msg, album, copy_mode=draft.copy_mode)
                delivered = True
                break
            except errors.FloodWait as fw:
                if attempt == 0:
                    await asyncio.sleep(fw.value + 1)
                    continue
                error = fw
            except Exception as ex:
                error = ex
                break

        if delivered:
            if chat in groups:
                group_delivered += 1
            else:
                user_delivered += 1
            await asyncio.sleep(0.2)
        else:
            if chat in groups:
                group_failed += 1
            else:
                user_failed += 1
            if error_path is None:
                error_path = Path(f"broadcast-errors-{int(time())}.txt")
            with error_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{chat} - {error}\n")

        processed = group_delivered + user_delivered + group_failed + user_failed
        now = monotonic()
        if status_message and processed < len(targets) and (
            processed % 25 == 0 or now - last_progress_edit >= 5
        ):
            try:
                await status_message.edit_text(progress_text())
            except Exception as exc:
                logger.debug("Could not update broadcast progress: %s", exc)
            last_progress_edit = now

    if status_message:
        await status_message.edit_text(progress_text(final=True))

    return group_delivered + user_delivered, group_failed + user_failed, error_path


@app.on_message(filters.command(["broadcast"]) & app.sudoers)
@lang.language()
async def _broadcast(_, message: types.Message):
    if not message.reply_to_message:
        return await message.reply_text(message.lang["gcast_usage"])

    if broadcasting.locked():
        return await message.reply_text(message.lang["gcast_active"])

    now = datetime.now(_tz())
    command = set(message.command[1:])
    token = token_urlsafe(6).replace("-", "_")[:8]
    draft = BroadcastDraft(
        token=token,
        creator_id=message.from_user.id,
        source_chat_id=message.reply_to_message.chat.id,
        source_message_id=message.reply_to_message.id,
        source_media_group_id=getattr(message.reply_to_message, "media_group_id", None),
        include_users="-user" in command,
        include_groups="-nochat" not in command,
        copy_mode="-forward" not in command,
        daily_minute=now.hour * 60 + now.minute,
    )
    _pending[token] = draft
    await _show_dashboard(message, draft, message.lang)


@app.on_message(filters.command(["broadcasts"]) & app.sudoers)
@lang.language()
async def _broadcasts(_, message: types.Message):
    jobs = await db.list_broadcast_jobs(limit=10)
    if not jobs:
        return await message.reply_text(message.lang["gcast_jobs_empty"])
    rows = []
    for job in jobs:
        repeat = (
            message.lang["gcast_repeat_forever"]
            if job["repeat_limit"] is None
            else message.lang["gcast_repeat_left"].format(
                max(int(job["repeat_limit"]) - int(job["sent_count"]), 0)
            )
        )
        rows.append(
            message.lang["gcast_job_row"].format(
                job["job_id"],
                job["status"],
                _audience_label(job["include_users"], job["include_groups"]),
                message.lang["gcast_mode_copy"] if job["copy_mode"] else message.lang["gcast_mode_forward"],
                _minute_label(job["daily_minute"]),
                repeat,
            )
        )
    await message.reply_text(message.lang["gcast_jobs"].format("\n".join(rows)))


@app.on_message(filters.command(["broadcaststop"]) & app.sudoers)
@lang.language()
async def _broadcaststop(_, message: types.Message):
    if len(message.command) < 2 or not message.command[1].isdigit():
        return await message.reply_text(message.lang["gcast_stop_usage"])
    job_id = int(message.command[1])
    await db.set_broadcast_job_status(job_id, "cancelled")
    await message.reply_text(message.lang["gcast_stopped"].format(job_id))


@app.on_callback_query(filters.regex(r"^broadcast ") & app.sudoers)
@lang.language()
async def _broadcast_callback(_, query: types.CallbackQuery):
    parts = query.data.split()
    if len(parts) < 3:
        return await feedback.toast(query, query.lang["play_expired"])
    action, token = parts[1], parts[2]
    draft = _pending.get(token)
    if not draft or draft.creator_id != query.from_user.id:
        return await feedback.toast(query, query.lang["play_expired"])

    await query.answer()
    if action == "view":
        return await _show_dashboard(query, draft, query.lang)
    if action == "toggle" and len(parts) >= 4:
        target = parts[3]
        if target == "users":
            draft.include_users = not draft.include_users
        elif target == "groups":
            draft.include_groups = not draft.include_groups
        elif target == "daily":
            draft.daily = not draft.daily
        elif target == "mode":
            draft.copy_mode = not draft.copy_mode
        return await _show_dashboard(query, draft, query.lang)
    if action == "time":
        return await query.message.edit_text(
            _time_text(query.lang, draft), reply_markup=_time_markup(query.lang, token)
        )
    if action == "timeadd" and len(parts) >= 4:
        draft.daily_minute = (draft.daily_minute + int(parts[3])) % 1440
        return await query.message.edit_text(
            _time_text(query.lang, draft), reply_markup=_time_markup(query.lang, token)
        )
    if action == "repeat":
        return await query.message.edit_text(
            _repeat_text(query.lang, draft), reply_markup=_repeat_markup(query.lang, token)
        )
    if action == "repeatforever":
        draft.repeat_limit = None
        return await query.message.edit_text(
            _repeat_text(query.lang, draft), reply_markup=_repeat_markup(query.lang, token)
        )
    if action == "repeatadd" and len(parts) >= 4:
        current = draft.repeat_limit or 0
        draft.repeat_limit = max(1, min(999, current + int(parts[3])))
        return await query.message.edit_text(
            _repeat_text(query.lang, draft), reply_markup=_repeat_markup(query.lang, token)
        )
    if action != "send":
        return await feedback.toast(query, query.lang["play_expired"])

    if not draft.selected:
        return await query.answer(query.lang["gcast_no_audience"], show_alert=True)

    if draft.daily:
        job_id = await db.create_broadcast_job(
            source_chat_id=draft.source_chat_id,
            source_message_id=draft.source_message_id,
            source_media_group_id=draft.source_media_group_id,
            include_users=draft.include_users,
            include_groups=draft.include_groups,
            copy_mode=draft.copy_mode,
            daily_minute=draft.daily_minute,
            timezone_name=config.PROJECT_TIMEZONE,
            repeat_limit=draft.repeat_limit,
            next_run_at=_next_daily_epoch(draft.daily_minute, _tz()),
            created_by=query.from_user.id,
        )
        _pending.pop(token, None)
        return await query.message.edit_text(
            query.lang["gcast_daily_saved"].format(
                job_id,
                _minute_label(draft.daily_minute),
                _repeat_label(query.lang, draft.repeat_limit),
            )
        )

    async with broadcasting:
        await query.message.edit_reply_markup(reply_markup=None)
        try:
            _, failed, error_path = await _run_broadcast(
                draft=draft,
                status_message=query.message,
                _lang=query.lang,
            )
            if error_path:
                await app.send_document(
                    chat_id=query.message.chat.id,
                    document=str(error_path),
                    caption=query.lang["gcast_errors"].format(failed),
                )
                error_path.unlink(missing_ok=True)
        finally:
            _pending.pop(token, None)


async def _daily_worker():
    while True:
        await asyncio.sleep(30)
        try:
            jobs = await db.get_due_broadcast_jobs(int(time()), limit=3)
            for job in jobs:
                await db.set_broadcast_job_status(job["job_id"], "running")
                draft = BroadcastDraft(
                    token=f"job{job['job_id']}",
                    creator_id=job["created_by"],
                    source_chat_id=job["source_chat_id"],
                    source_message_id=job["source_message_id"],
                    source_media_group_id=job["source_media_group_id"],
                    include_users=job["include_users"],
                    include_groups=job["include_groups"],
                    copy_mode=job["copy_mode"],
                    daily=True,
                    daily_minute=job["daily_minute"],
                    repeat_limit=job["repeat_limit"],
                )
                try:
                    async with broadcasting:
                        await _run_broadcast(
                            draft=draft,
                            status_message=None,
                            _lang=lang.languages.get("en", {}),
                        )
                except Exception:
                    logger.exception("Daily broadcast job %s failed", job["job_id"])
                    await db.set_broadcast_job_status(
                        job["job_id"],
                        "active",
                        next_run_at=int(time()) + 300,
                    )
                    continue
                sent_count = int(job["sent_count"]) + 1
                repeat_limit = job["repeat_limit"]
                if repeat_limit is not None and sent_count >= int(repeat_limit):
                    next_run_at = None
                else:
                    try:
                        tz = ZoneInfo(job["timezone"] or "Asia/Yangon")
                    except ZoneInfoNotFoundError:
                        tz = timezone(timedelta(hours=6, minutes=30), "Asia/Yangon")
                    next_run_at = _next_daily_epoch(
                        int(job["daily_minute"]),
                        tz,
                        after=datetime.now(tz),
                    )
                await db.complete_broadcast_job_run(
                    job["job_id"], next_run_at=next_run_at
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Daily broadcast worker failed")


supervisor.spawn("daily-broadcasts", _daily_worker, restart=True)
