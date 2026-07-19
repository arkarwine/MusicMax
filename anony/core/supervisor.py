"""Observable lifecycle management for background asyncio work."""

from __future__ import annotations

import asyncio
import sys
import threading
from dataclasses import dataclass
from time import monotonic
from typing import Awaitable, Callable


CoroutineFactory = Callable[[], Awaitable[object]]


@dataclass(slots=True)
class WorkerState:
    name: str
    recurring: bool
    state: str = "starting"
    failures: int = 0
    restarts: int = 0
    last_error: str | None = None
    last_failure_at: float | None = None


class RuntimeSupervisor:
    """Run detached work without losing its exceptions."""

    def __init__(self, logger, *, backoff=(1, 5, 30), stable_after=60) -> None:
        self.logger = logger
        self.backoff = tuple(backoff)
        self.stable_after = stable_after
        self.tasks: dict[str, asyncio.Task] = {}
        self.workers: dict[str, WorkerState] = {}
        self.closing = False
        self._reported_at: dict[str, float] = {}

    def _unique_name(self, name: str) -> str:
        if name not in self.tasks:
            return name
        number = 2
        while f"{name}#{number}" in self.tasks:
            number += 1
        return f"{name}#{number}"

    def spawn(
        self,
        name: str,
        coroutine_factory: CoroutineFactory,
        *,
        restart: bool = True,
    ) -> asyncio.Task:
        if self.closing:
            raise RuntimeError("Runtime supervisor is closing")
        if name in self.tasks and not self.tasks[name].done():
            raise RuntimeError(f"Worker already running: {name}")
        state = WorkerState(name=name, recurring=restart)
        self.workers[name] = state
        task = asyncio.create_task(
            self._run(state, coroutine_factory, restart),
            name=f"anony:{name}",
        )
        self.tasks[name] = task
        task.add_done_callback(lambda done, key=name: self._finished(key, done))
        return task

    def spawn_once(self, name: str, coroutine: Awaitable[object]) -> asyncio.Task:
        unique = self._unique_name(name)
        used = False

        def factory() -> Awaitable[object]:
            nonlocal used
            if used:
                raise RuntimeError("One-time coroutine was reused")
            used = True
            return coroutine

        return self.spawn(unique, factory, restart=False)

    async def _run(
        self,
        state: WorkerState,
        factory: CoroutineFactory,
        restart: bool,
    ) -> object | None:
        consecutive = 0
        while True:
            started = monotonic()
            state.state = "running"
            try:
                result = await factory()
            except asyncio.CancelledError:
                state.state = "stopped"
                raise
            except Exception as exc:
                runtime = monotonic() - started
                consecutive = 1 if runtime >= self.stable_after else consecutive + 1
                state.failures += 1
                state.last_error = f"{type(exc).__name__}: {exc}"
                state.last_failure_at = monotonic()
                state.state = "failed"
                self.logger.exception("Background task %s failed", state.name)
                if not restart or self.closing:
                    return None
            else:
                if not restart or self.closing:
                    state.state = "completed"
                    return result
                consecutive = 1
                state.failures += 1
                state.last_error = "Worker exited unexpectedly"
                state.last_failure_at = monotonic()
                state.state = "failed"
                self.logger.error("Background task %s exited unexpectedly", state.name)

            delay = self.backoff[min(consecutive - 1, len(self.backoff) - 1)]
            state.state = "backoff"
            state.restarts += 1
            self.logger.warning(
                "Restarting background task %s in %s second(s)", state.name, delay
            )
            await asyncio.sleep(delay)

    def _finished(self, name: str, task: asyncio.Task) -> None:
        self.tasks.pop(name, None)
        if task.cancelled():
            return
        try:
            task.exception()
        except asyncio.CancelledError:
            return
        except Exception:
            self.logger.exception("Could not retrieve task result for %s", name)

    def snapshot(self) -> dict:
        failed = [
            state.name
            for state in self.workers.values()
            if state.state in {"failed", "backoff"}
        ]
        return {
            "healthy": not failed,
            "running": sum(s.state == "running" for s in self.workers.values()),
            "failed": failed,
            "workers": {
                name: {
                    "state": state.state,
                    "failures": state.failures,
                    "restarts": state.restarts,
                    "last_error": state.last_error,
                }
                for name, state in self.workers.items()
            },
        }

    def report_exception(
        self,
        key: str,
        message: str,
        *args,
        interval: int = 300,
    ) -> bool:
        """Log a repeated operational failure at a bounded frequency."""
        now = monotonic()
        if now - self._reported_at.get(key, float("-inf")) < interval:
            return False
        self._reported_at[key] = now
        self.logger.warning(message, *args, exc_info=True)
        return True

    async def close(self) -> None:
        self.closing = True
        active = list(self.tasks.values())
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)
        self.tasks.clear()


def install_exception_handlers(loop, logger) -> None:
    """Send otherwise-unhandled loop and thread failures to normal logs."""

    previous_loop_handler = loop.get_exception_handler()

    def loop_handler(current_loop, context) -> None:
        exception = context.get("exception")
        message = context.get("message", "Unhandled asyncio exception")
        if exception:
            logger.error(message, exc_info=(type(exception), exception, exception.__traceback__))
        else:
            logger.error("%s: %r", message, context)
        if previous_loop_handler:
            previous_loop_handler(current_loop, context)

    loop.set_exception_handler(loop_handler)

    previous_sys_hook = sys.excepthook

    def sys_hook(exc_type, exc_value, traceback) -> None:
        logger.critical(
            "Unhandled main-thread exception",
            exc_info=(exc_type, exc_value, traceback),
        )
        if previous_sys_hook is not sys.__excepthook__:
            previous_sys_hook(exc_type, exc_value, traceback)

    sys.excepthook = sys_hook

    previous_thread_hook = threading.excepthook

    def thread_hook(args) -> None:
        logger.error(
            "Unhandled exception in thread %s",
            args.thread.name if args.thread else "unknown",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        if previous_thread_hook is not threading.__excepthook__:
            previous_thread_hook(args)

    threading.excepthook = thread_hook
