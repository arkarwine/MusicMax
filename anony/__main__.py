# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import asyncio
import signal
import importlib
from contextlib import suppress

from anony import (anon, app, config, db, health, lang, logger, stop,
                   supervisor, themes, thumb, userbot, yt)
from anony.core.recovery import recovery
from anony.plugins import all_modules


async def idle() -> str:
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    reason = {"value": "requested"}

    def request_stop(sig) -> None:
        reason["value"] = f"signal:{sig.name}"
        logger.warning("Shutdown requested by %s", sig.name)
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, request_stop, sig)
    await stop_event.wait()
    return reason["value"]


async def main():
    from anony.core.supervisor import install_exception_handlers

    install_exception_handlers(asyncio.get_running_loop(), logger)
    try:
        await db.connect()
        await health.begin_run()
        await themes.boot()
        app.logger = await db.get_log_chat()
        await app.boot()
        await userbot.boot()
        await anon.boot()
        await thumb.start()

        for module in all_modules:
            importlib.import_module(f"anony.plugins.{module}")
        logger.info(f"Loaded {len(all_modules)} modules.")

        if config.COOKIES_URL:
            await yt.save_cookies(config.COOKIES_URL)

        sudoers = await db.get_sudoers()
        app.sudoers.update(sudoers)
        app.bl_users.update(await db.get_blacklisted())
        logger.info(f"Loaded {len(app.sudoers)} sudo users.")
        await app.register_sudo_commands(app.sudoers)

        await recovery.restore_queues()
        supervisor.spawn_once("playback-recovery", recovery.run_startup())
        health.start()

        reason = await idle()
    except asyncio.CancelledError:
        await stop("main task cancelled")
        raise
    except BaseException:
        logger.exception("Bot startup or main runtime failed")
        await stop("startup/runtime failure")
        raise
    else:
        await stop(reason)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except BaseException:
        logger.critical("Bot process terminated by an unhandled failure", exc_info=True)
        raise
