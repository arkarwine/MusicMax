# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import asyncio
import platform
import time
from datetime import datetime, timezone
from html import escape
from importlib import metadata
from pathlib import Path

import psutil
from pyrogram import enums, filters, types

from anony import anon, app, boot, config, db, health, lang, userbot, yt
from anony.helpers import admin_check, buttons, feedback


async def build_setup_text(m: types.Message) -> tuple[str, bool]:
    bot_member = await app.get_chat_member(m.chat.id, app.id)
    bot_admin = bot_member.status in {
        enums.ChatMemberStatus.OWNER,
        enums.ChatMemberStatus.ADMINISTRATOR,
    }
    can_invite = bot_member.status == enums.ChatMemberStatus.OWNER or bool(
        bot_member.privileges and bot_member.privileges.can_invite_users
    )

    if not bot_admin:
        requirement = m.lang["setup_bot_missing"]
    elif not can_invite:
        requirement = m.lang["setup_invite_missing"]
    else:
        return m.lang["setup_ready"], True
    return m.lang["setup_required"].format(requirement), False


@app.on_message(filters.command(["setup"]) & filters.group & ~app.bl_users)
@lang.language()
@admin_check
async def _setup(_, m: types.Message):
    text, ready = await build_setup_text(m)
    await m.reply_text(
        text,
        reply_markup=buttons.setup_markup(m.lang, ready, m.chat.id),
        disable_notification=True,
    )


@app.on_callback_query(filters.regex(r"^setup check$") & ~app.bl_users)
@lang.language()
@admin_check
async def _setup_callback(_, query: types.CallbackQuery):
    action = query.data.split()[1]
    query.message.lang = query.lang
    if action == "check":
        text, ready = await build_setup_text(query.message)
        await feedback.toast(query, query.lang["setup_checked"])
        markup = buttons.setup_markup(query.lang, ready, query.message.chat.id)
        if query.message.caption is not None:
            return await query.edit_message_caption(
                caption=text,
                reply_markup=markup,
            )
        return await query.edit_message_text(text, reply_markup=markup)


def _status_uptime() -> str:
    elapsed = max(int(time.time() - boot), 0)
    days, remainder = divmod(elapsed, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    value = f"{hours:02d}h {minutes:02d}m {seconds:02d}s"
    return f"{days}d {value}" if days else value


def _package_version(*names: str) -> str:
    for name in names:
        try:
            return metadata.version(name)
        except Exception:
            continue
    return "unavailable"


def _system_percent(getter) -> str:
    try:
        return f"{getter():.1f}%"
    except Exception:
        return "unavailable"


async def _bot_latency() -> str:
    started = time.perf_counter()
    try:
        await asyncio.wait_for(app.get_me(), timeout=5)
    except Exception:
        return "unavailable"
    return f"{(time.perf_counter() - started) * 1000:.0f} ms"


@app.on_message(filters.command(["status"]) & app.sudoers)
@lang.language()
async def _status(_, m: types.Message):
    cookie_dir = Path(yt.cookie_dir)
    try:
        cookies = len(list(cookie_dir.glob("*.txt"))) if cookie_dir.exists() else 0
    except OSError:
        cookies = "unavailable"
    try:
        saved_sessions = len(await db.get_recovery_sessions())
    except Exception:
        saved_sessions = "unavailable"
    try:
        logging_enabled = await db.is_logger()
    except Exception:
        logging_enabled = False

    snapshot = health.snapshot()
    alert_enabled = await db.health_alerts_enabled(m.from_user.id)
    update_age = max(int(time.time()) - snapshot["last_update_at"], 0)
    external_watchdog = (
        f"{config.WATCHDOG_MODE} · "
        f"quiet {config.WATCHDOG_UPDATE_STALE_SECONDS}s · "
        f"proof {config.WATCHDOG_ASSISTANT_PROBE_STALE_SECONDS}s"
        if config.EXTERNAL_WATCHDOG
        else "off"
    )
    try:
        runtime_health = await db.get_runtime_health()
    except Exception:
        runtime_health = {}
    last_restart = runtime_health.get("watchdog_last_restart_at", {})
    if last_restart.get("value"):
        try:
            restart_age = max(int(time.time()) - int(last_restart["value"]), 0)
        except (TypeError, ValueError):
            restart_age = 0
        restart_reason = runtime_health.get("watchdog_last_reason", {}).get(
            "value", "unknown"
        )
        external_restart = f"{restart_age}s ago · {restart_reason[:80]}"
    else:
        external_restart = "none"
    failed_workers = snapshot["workers"]["failed"]
    reliability = "Healthy" if snapshot["healthy"] else "Needs attention"
    worker_summary = (
        f'{snapshot["workers"]["running"]} running'
    )
    active_handlers = int(snapshot.get("active_handler_count") or 0)
    oldest_handler_at = int(snapshot.get("oldest_active_handler_at") or 0)
    if active_handlers and oldest_handler_at:
        handler_age = max(int(time.time()) - oldest_handler_at, 0)
        handler_summary = (
            f"{active_handlers} active · "
            f"{snapshot.get('oldest_active_handler') or 'unknown'} · {handler_age}s"
        )
    else:
        handler_summary = "idle"

    assistant_probe_at = int(snapshot.get("assistant_probe_at") or 0)
    assistant_probe_age = max(int(time.time()) - assistant_probe_at, 0) if assistant_probe_at else None
    assistant_probe_status = str(snapshot.get("assistant_probe_status") or "unknown")
    assistant_probe_detail = str(snapshot.get("assistant_probe_detail") or "")
    if assistant_probe_status == "ok" and assistant_probe_age is not None:
        assistant_proof = f"reachable · {assistant_probe_age}s ago"
    elif assistant_probe_status in {"startup", "unknown"}:
        assistant_proof = "pending"
    elif assistant_probe_age is not None:
        assistant_proof = f"{assistant_probe_status} · {assistant_probe_age}s ago"
    else:
        assistant_proof = assistant_probe_status
    if assistant_probe_detail and assistant_probe_status not in {"ok", "startup", "unknown"}:
        assistant_proof = f"{assistant_proof} · {assistant_probe_detail[:50]}"

    database_ready = db.connection is not None
    assistants = len(userbot.clients)
    bot_ready = bool(getattr(app, "is_connected", False))
    if bot_ready and database_ready and assistants:
        state_key = "status_operational"
        state_icon = "🟢"
    elif bot_ready or database_ready:
        state_key = "status_limited"
        state_icon = "🟠"
    else:
        state_key = "status_unavailable"
        state_icon = "🔴"

    voice_latency = await anon.ping()
    text = m.lang["status_sudo"].format(
        cpu=_system_percent(lambda: psutil.cpu_percent(interval=0)),
        memory=_system_percent(lambda: psutil.virtual_memory().percent),
        storage=_system_percent(lambda: psutil.disk_usage("/").percent),
        bot_latency=await _bot_latency(),
        voice_latency=f"{voice_latency:.2f} ms" if voice_latency else "unavailable",
        database=m.lang[
            "status_connected" if database_ready else "status_disconnected"
        ],
        assistants=assistants,
        active_calls=len(db.active_calls),
        saved_sessions=saved_sessions,
        cookies=cookies,
        logging=m.lang[
            "status_enabled" if logging_enabled else "status_disabled"
        ],
        log_destination=escape(str(app.logger or "none")),
        uptime=_status_uptime(),
        python=platform.python_version(),
        pyrogram=_package_version("kurigram", "pyrogram"),
        pytgcalls=_package_version("py-tgcalls", "pytgcalls"),
        state_icon=state_icon,
        state=m.lang[state_key],
        updated=datetime.now(timezone.utc).strftime("%d %b · %H:%M"),
        supervisor=reliability,
        workers=worker_summary,
        failed_workers=", ".join(failed_workers) if failed_workers else "none",
        last_update=f"{update_age}s ago · {snapshot['last_update_kind']}",
        handlers=handler_summary,
        assistant_proof=assistant_proof,
        external_watchdog=external_watchdog,
        external_restart=external_restart,
        previous_exit=snapshot["previous_result"],
        health_alerts=m.lang[
            "health_alerts_on" if alert_enabled else "health_alerts_off"
        ],
    )
    await m.reply_text(text, disable_notification=True)


@app.on_message(filters.command(["backupdb"]) & app.sudoers)
@lang.language()
async def _backupdb(_, m: types.Message):
    sent = await m.reply_text(m.lang["backup_start"], disable_notification=True)
    path = await db.backup()
    await m.reply_document(
        document=str(path),
        caption=m.lang["backup_done"].format(path.name),
        disable_notification=True,
    )
    await sent.delete()
