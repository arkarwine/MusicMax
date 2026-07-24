"""Standalone PyTgCalls worker.

This file is executed directly by the main bot.  It intentionally imports no
project modules so a voice worker does not initialize the bot, database, UI,
download stack, or health monitor.
"""

from __future__ import annotations

import asyncio
import faulthandler
import json
import logging
import os
import sys
from contextlib import suppress

from ntgcalls import ConnectionNotFound
from pyrogram import Client
from pytgcalls import PyTgCalls, exceptions, types
from pytgcalls.pytgcalls_session import PyTgCallsSession


logging.basicConfig(
    format="[%(asctime)s - %(levelname)s] - voice-worker: %(message)s",
    datefmt="%d-%b-%y %H:%M:%S",
    level=logging.INFO,
)
logging.getLogger("pyrogram").setLevel(logging.ERROR)
logging.getLogger("pytgcalls").setLevel(logging.ERROR)
logging.getLogger("ntgcalls").setLevel(logging.CRITICAL)
logger = logging.getLogger("voice-worker")

with suppress(Exception):
    faulthandler.enable(all_threads=True)

os.environ.pop("NODE_CHANNEL_FD", None)
os.environ.pop("NODE_UNIQUE_ID", None)


_AUDIO_QUALITIES = {
    "low": types.AudioQuality.LOW,
    "medium": types.AudioQuality.MEDIUM,
    "high": types.AudioQuality.HIGH,
}
_VIDEO_QUALITIES = {
    "360p": types.VideoQuality.SD_360p,
    "480p": types.VideoQuality.SD_480p,
    "720p": types.VideoQuality.HD_720p,
}


async def _send(
    writer: asyncio.StreamWriter,
    lock: asyncio.Lock,
    payload: dict,
) -> None:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    async with lock:
        writer.write(encoded)
        await writer.drain()


async def _leave_call(calls: PyTgCalls, app: Client, chat_id: int) -> None:
    try:
        await calls.leave_call(chat_id, close=False)
    except (ConnectionNotFound, exceptions.NotInCallError):
        # After a parent or worker crash Telegram can still show the assistant
        # in the call even though this fresh NTgCalls process has no connection.
        with suppress(Exception):
            await app.leave_group_call(chat_id)
    except exceptions.NoActiveGroupCall:
        pass


async def _execute(
    operation: str,
    command: dict,
    calls: PyTgCalls,
    app: Client,
    active_chats: set[int],
):
    chat_id = int(command.get("chat_id", 0))
    peer = command.get("peer")
    if peer:
        await app.storage.update_peers([(
            int(peer["id"]),
            int(peer.get("access_hash") or 0),
            str(peer["type"]),
            None,
        )])
    if operation == "play":
        stream = types.MediaStream(
            media_path=command["media_path"],
            audio_parameters=_AUDIO_QUALITIES.get(
                command.get("audio_quality"),
                types.AudioQuality.MEDIUM,
            ),
            video_parameters=_VIDEO_QUALITIES.get(
                command.get("video_quality"),
                types.VideoQuality.SD_480p,
            ),
            audio_flags=types.MediaStream.Flags.REQUIRED,
            video_flags=(
                types.MediaStream.Flags.AUTO_DETECT
                if command.get("video")
                else types.MediaStream.Flags.IGNORE
            ),
            ffmpeg_parameters=command.get("ffmpeg_parameters"),
        )
        await calls.play(
            chat_id=chat_id,
            stream=stream,
            config=types.GroupCallConfig(auto_start=False),
        )
        active_chats.add(chat_id)
        return True
    if operation == "pause":
        await calls.pause(chat_id)
        return True
    if operation == "resume":
        await calls.resume(chat_id)
        return True
    if operation == "leave":
        await _leave_call(calls, app, chat_id)
        active_chats.discard(chat_id)
        return True
    if operation == "participants":
        return len(await calls.get_participants(chat_id))
    if operation == "ping":
        return float(calls.ping)
    if operation == "shutdown":
        return True
    raise ValueError(f"Unknown voice operation: {operation}")


async def _run(host: str, port: int, token: str) -> None:
    reader, writer = await asyncio.open_connection(host, port)
    send_lock = asyncio.Lock()
    await _send(
        writer,
        send_lock,
        {"kind": "hello", "token": token, "pid": os.getpid()},
    )

    line = await asyncio.wait_for(reader.readline(), timeout=20)
    if not line:
        raise RuntimeError("Voice worker initialization channel closed")
    initialization = json.loads(line.decode("utf-8"))
    if initialization.get("kind") != "initialize":
        raise RuntimeError("Voice worker received an invalid initialization")

    slot = int(initialization["slot"])
    session_string = str(initialization.pop("session_string"))
    app = Client(
        name=f"AnonyVoice{slot}-{os.getpid()}",
        api_id=int(initialization["api_id"]),
        api_hash=str(initialization["api_hash"]),
        session_string=session_string,
        in_memory=True,
    )
    del session_string

    calls = PyTgCalls(app, workers=2, cache_duration=100)
    PyTgCallsSession.notice_displayed = True
    active_chats: set[int] = set()

    @calls.on_update()
    async def update_handler(_, update: types.Update) -> None:
        if isinstance(update, types.StreamEnded):
            if update.stream_type == types.StreamEnded.Type.AUDIO:
                await _send(
                    writer,
                    send_lock,
                    {
                        "kind": "event",
                        "event": "stream_ended",
                        "chat_id": update.chat_id,
                    },
                )
        elif isinstance(update, types.ChatUpdate):
            if update.status in {
                types.ChatUpdate.Status.KICKED,
                types.ChatUpdate.Status.LEFT_GROUP,
                types.ChatUpdate.Status.CLOSED_VOICE_CHAT,
            }:
                active_chats.discard(update.chat_id)
                await _send(
                    writer,
                    send_lock,
                    {
                        "kind": "event",
                        "event": "call_closed",
                        "chat_id": update.chat_id,
                    },
                )

    try:
        await app.start()
        await calls.start()
        await _send(
            writer,
            send_lock,
            {
                "kind": "ready",
                "slot": slot,
                "pid": os.getpid(),
                "user_id": app.me.id,
            },
        )
        logger.info("Assistant %s voice worker ready (pid=%s)", slot, os.getpid())

        while True:
            line = await reader.readline()
            if not line:
                break
            command = {}
            try:
                command = json.loads(line.decode("utf-8"))
                if command.get("kind") != "request":
                    continue
                request_id = command["id"]
                operation = str(command["operation"])
                result = await _execute(
                    operation,
                    command,
                    calls,
                    app,
                    active_chats,
                )
                await _send(
                    writer,
                    send_lock,
                    {
                        "kind": "response",
                        "id": request_id,
                        "ok": True,
                        "result": result,
                    },
                )
                if operation == "shutdown":
                    break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception(
                    "Voice operation failed: %s",
                    command.get("operation", "unknown"),
                )
                await _send(
                    writer,
                    send_lock,
                    {
                        "kind": "response",
                        "id": command.get("id"),
                        "ok": False,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:500],
                    },
                )
    finally:
        for chat_id in tuple(active_chats):
            with suppress(Exception):
                await _leave_call(calls, app, chat_id)
        with suppress(Exception):
            if app.is_connected:
                await app.stop()
        writer.close()
        with suppress(Exception):
            await writer.wait_closed()
        logger.info("Assistant %s voice worker stopped", slot)


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("Usage: voice_worker_process.py HOST PORT TOKEN")
    try:
        asyncio.run(_run(sys.argv[1], int(sys.argv[2]), sys.argv[3]))
    except KeyboardInterrupt:
        pass
    except BaseException:
        logger.critical("Voice worker terminated unexpectedly", exc_info=True)
        raise


if __name__ == "__main__":
    main()
