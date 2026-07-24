"""Async parent-side controller for one isolated voice subprocess."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import secrets
import sys
from contextlib import suppress
from pathlib import Path
from typing import Awaitable, Callable


class VoiceWorkerError(RuntimeError):
    """An operation failed inside a voice worker."""

    def __init__(self, remote_type: str, detail: str = "") -> None:
        self.remote_type = remote_type
        self.detail = detail
        super().__init__(
            f"{remote_type}: {detail}" if detail else remote_type
        )


class VoiceWorkerUnavailable(VoiceWorkerError):
    """The worker process is unavailable or stopped responding."""

    def __init__(self, detail: str) -> None:
        super().__init__("VoiceWorkerUnavailable", detail)


EventHandler = Callable[[dict], Awaitable[None] | None]


class VoiceWorkerClient:
    """Proxy PyTgCalls operations to a standalone child process."""

    START_TIMEOUT = 30

    def __init__(
        self,
        *,
        slot: int,
        session_string: str,
        api_id: int,
        api_hash: str,
        logger,
        event_handler: EventHandler | None = None,
    ) -> None:
        self.slot = slot
        self._session_string = session_string
        self._api_id = api_id
        self._api_hash = api_hash
        self._logger = logger
        self._event_handler = event_handler
        self._process: asyncio.subprocess.Process | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._send_lock = asyncio.Lock()
        self._termination_lock = asyncio.Lock()
        self._request_sequence = 0
        self._ready = False
        self._ever_ready = False
        self._expected_stop = False
        self._consecutive_timeouts = 0

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process else None

    @property
    def is_alive(self) -> bool:
        return bool(
            self._ready
            and self._process
            and self._process.returncode is None
            and self._writer
            and not self._writer.is_closing()
        )

    def relabel(self, slot: int) -> None:
        self.slot = slot

    def set_event_handler(self, handler: EventHandler) -> None:
        self._event_handler = handler

    async def _accept_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        token: str,
        connected: asyncio.Future,
    ) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=10)
            hello = json.loads(line.decode("utf-8"))
            if hello.get("kind") != "hello" or not secrets.compare_digest(
                str(hello.get("token", "")),
                token,
            ):
                raise ValueError("Invalid voice worker handshake")
            if connected.done():
                raise ValueError("Duplicate voice worker connection")
            connected.set_result((reader, writer))
        except Exception as exc:
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()
            if not connected.done():
                connected.set_exception(exc)

    async def start(self) -> "VoiceWorkerClient":
        if self.is_alive:
            return self
        self._expected_stop = False
        self._ever_ready = False
        loop = asyncio.get_running_loop()
        connected = loop.create_future()
        token = secrets.token_urlsafe(32)

        async def accept(reader, writer):
            await self._accept_connection(
                reader,
                writer,
                token,
                connected,
            )

        server = await asyncio.start_server(accept, "127.0.0.1", 0)
        host, port = server.sockets[0].getsockname()[:2]
        worker_path = Path(__file__).with_name("voice_worker_process.py")
        environment = os.environ.copy()
        environment.pop("NODE_CHANNEL_FD", None)
        environment.pop("NODE_UNIQUE_ID", None)

        try:
            self._process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(worker_path),
                str(host),
                str(port),
                token,
                cwd=str(Path.cwd()),
                env=environment,
            )
            self._reader, self._writer = await asyncio.wait_for(
                connected,
                timeout=self.START_TIMEOUT,
            )
        except Exception:
            self._expected_stop = True
            await self._terminate_process()
            raise
        finally:
            # On Python 3.12, wait_closed() also waits for accepted client
            # connections.  This IPC connection is the worker's lifetime
            # channel, so awaiting it here deadlocks the initialization:
            # the parent waits for the child to disconnect while the child
            # waits for the parent to send "initialize".
            server.close()

        ready = loop.create_future()
        self._pending["ready"] = ready
        self._reader_task = asyncio.create_task(
            self._reader_loop(),
            name=f"voice-worker-reader:{self.slot}",
        )
        try:
            await self._send({
                "kind": "initialize",
                "slot": self.slot,
                "api_id": self._api_id,
                "api_hash": self._api_hash,
                "session_string": self._session_string,
            })
            await asyncio.wait_for(ready, timeout=self.START_TIMEOUT)
        except Exception:
            self._expected_stop = True
            await self._terminate_process()
            raise
        finally:
            self._pending.pop("ready", None)

        self._session_string = ""
        self._ready = True
        self._ever_ready = True
        self._logger.info(
            "Voice worker %s started (pid=%s)",
            self.slot,
            self.pid,
        )
        return self

    async def _send(self, payload: dict) -> None:
        if self._writer is None or self._writer.is_closing():
            raise VoiceWorkerUnavailable("IPC channel is closed")
        data = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        async with self._send_lock:
            self._writer.write(data)
            await self._writer.drain()

    async def _reader_loop(self) -> None:
        try:
            while self._reader is not None:
                line = await self._reader.readline()
                if not line:
                    break
                try:
                    message = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._logger.warning(
                        "Voice worker %s sent an invalid IPC message",
                        self.slot,
                    )
                    continue
                self._handle_message(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._logger.exception(
                "Voice worker %s IPC reader failed",
                self.slot,
            )
        finally:
            self._ready = False
            error = VoiceWorkerUnavailable("Worker connection closed")
            for future in tuple(self._pending.values()):
                if not future.done():
                    future.set_exception(error)
            self._pending.clear()
            if self._ever_ready and not self._expected_stop:
                await self._terminate_process()
                self._emit_event({
                    "event": "worker_exit",
                    "slot": self.slot,
                    "pid": self.pid,
                    "returncode": (
                        self._process.returncode
                        if self._process is not None
                        else None
                    ),
                })

    def _handle_message(self, message: dict) -> None:
        kind = message.get("kind")
        if kind == "ready":
            future = self._pending.get("ready")
            if future is not None and not future.done():
                future.set_result(message)
            return
        if kind == "event":
            self._emit_event(message)
            return
        if kind != "response":
            return
        future = self._pending.pop(str(message.get("id")), None)
        if future is None or future.done():
            return
        if message.get("ok"):
            future.set_result(message.get("result"))
        else:
            future.set_exception(
                VoiceWorkerError(
                    str(message.get("error_type") or "VoiceWorkerError"),
                    str(message.get("error") or ""),
                )
            )

    def _emit_event(self, message: dict) -> None:
        if self._event_handler is None:
            return
        try:
            result = self._event_handler(message)
            if inspect.isawaitable(result):
                asyncio.create_task(result)
        except Exception:
            self._logger.exception(
                "Voice worker %s event delivery failed",
                self.slot,
            )

    async def request(
        self,
        operation: str,
        *,
        timeout: float = 15,
        **payload,
    ):
        if not self.is_alive:
            raise VoiceWorkerUnavailable(
                f"Assistant {self.slot} voice worker is not ready"
            )
        self._request_sequence += 1
        request_id = f"{self.slot}:{self._request_sequence}"
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._send({
                "kind": "request",
                "id": request_id,
                "operation": operation,
                **payload,
            })
            result = await asyncio.wait_for(future, timeout=timeout)
            self._consecutive_timeouts = 0
            return result
        except asyncio.TimeoutError as exc:
            self._pending.pop(request_id, None)
            self._consecutive_timeouts += 1
            # One slow Telegram operation must not take every active stream on
            # this assistant down. Ask the worker to cancel only this request;
            # terminate the process only after repeated unanswered commands.
            with suppress(Exception):
                await self._send({
                    "kind": "cancel",
                    "id": request_id,
                })
            if self._consecutive_timeouts >= 3:
                await self.abort(
                    f"{self._consecutive_timeouts} consecutive operations "
                    f"timed out (last={operation}, {timeout:.0f}s)"
                )
            raise VoiceWorkerUnavailable(
                f"{operation} timed out after {timeout:.0f}s"
            ) from exc
        except Exception:
            # A remote exception is still a valid worker response.
            self._consecutive_timeouts = 0
            raise
        finally:
            self._pending.pop(request_id, None)

    async def play(
        self,
        *,
        chat_id: int,
        media_path: str,
        video: bool,
        audio_quality: str,
        video_quality: str,
        video_fps: int,
        ffmpeg_parameters: str | None,
        peer: dict | None,
        timeout: float,
    ) -> bool:
        return bool(await self.request(
            "play",
            timeout=timeout,
            chat_id=chat_id,
            media_path=str(media_path),
            video=video,
            audio_quality=audio_quality,
            video_quality=video_quality,
            video_fps=video_fps,
            ffmpeg_parameters=ffmpeg_parameters,
            peer=peer,
        ))

    async def pause(self, chat_id: int, *, peer: dict | None = None):
        return await self.request("pause", chat_id=chat_id, peer=peer)

    async def resume(self, chat_id: int, *, peer: dict | None = None):
        return await self.request("resume", chat_id=chat_id, peer=peer)

    async def leave_call(
        self,
        chat_id: int,
        close: bool = False,
        *,
        peer: dict | None = None,
    ):
        del close
        return await self.request("leave", chat_id=chat_id, peer=peer)

    async def get_participant_count(
        self,
        chat_id: int,
        *,
        peer: dict | None = None,
    ) -> int:
        return int(await self.request(
            "participants",
            chat_id=chat_id,
            peer=peer,
        ))

    async def measure_ping(self) -> float:
        return float(await self.request("ping", timeout=5))

    async def abort(self, reason: str) -> None:
        if self._expected_stop:
            return
        self._logger.error(
            "Terminating voice worker %s: %s",
            self.slot,
            reason,
        )
        await self._terminate_process()

    async def stop(self) -> None:
        already_stopping = self._expected_stop
        self._expected_stop = True
        if not already_stopping and self.is_alive:
            with suppress(Exception):
                await self.request("shutdown", timeout=5)
        if self._writer is not None:
            self._writer.close()
            with suppress(Exception):
                await self._writer.wait_closed()
        await self._terminate_process(graceful=True)
        if self._reader_task is not None:
            self._reader_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._reader_task
        self._logger.info("Voice worker %s stopped", self.slot)

    async def _terminate_process(self, *, graceful: bool = False) -> None:
        async with self._termination_lock:
            process = self._process
            if process is None:
                return
            if process.returncode is None:
                if graceful:
                    try:
                        await asyncio.wait_for(process.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        pass
                    else:
                        self._ready = False
                        return
                with suppress(ProcessLookupError):
                    process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    with suppress(ProcessLookupError):
                        process.kill()
                    await process.wait()
            self._ready = False
