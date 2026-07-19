# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import time
import asyncio
import faulthandler
import logging
import os
from logging.handlers import RotatingFileHandler

# PM2 launches processes with Node IPC variables. Deno interprets
# NODE_CHANNEL_FD as its own IPC channel and yt-dlp's JS challenge solver then
# fails with "fd is not from BiPipe". Python does not use this Node channel.
os.environ.pop("NODE_CHANNEL_FD", None)
os.environ.pop("NODE_UNIQUE_ID", None)

logging.basicConfig(
    format="[%(asctime)s - %(levelname)s] - %(name)s: %(message)s",
    datefmt="%d-%b-%y %H:%M:%S",
    handlers=[
        RotatingFileHandler(
            "log.txt", maxBytes=10485760, backupCount=5, encoding="utf-8"
        ),
        logging.StreamHandler(),
    ],
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("ntgcalls").setLevel(logging.CRITICAL)
logging.getLogger("aiosqlite").setLevel(logging.ERROR)
logging.getLogger("pyrogram").setLevel(logging.ERROR)
logging.getLogger("pytgcalls").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)
try:
    faulthandler.enable(all_threads=True)
except Exception:
    logger.warning("Could not enable fatal-error diagnostics", exc_info=True)


__version__ = "3.0.3"

from config import Config  # noqa: E402

config = Config()
config.check()
tasks = []  # Kept for compatibility with third-party plugins.
from anony.core.supervisor import RuntimeSupervisor  # noqa: E402
supervisor = RuntimeSupervisor(logger)
boot = time.time()

from anony.core.bot import Bot  # noqa: E402
app = Bot()

from anony.core.dir import ensure_dirs  # noqa: E402
ensure_dirs()

from anony.core.userbot import Userbot  # noqa: E402
userbot = Userbot()

from anony.core.database import SQLiteDB  # noqa: E402
db = SQLiteDB()

from anony.core.lang import Language  # noqa: E402
lang = Language()

from anony.core.themes import ThemeManager  # noqa: E402
themes = ThemeManager(config, lang, db, logger)

from anony.core.telegram import Telegram  # noqa: E402
from anony.core.youtube import YouTube  # noqa: E402
tg = Telegram()
yt = YouTube()

from anony.helpers import Queue, Thumbnail, feedback  # noqa: E402
queue = Queue()
thumb = Thumbnail()

from anony.core.calls import TgCall  # noqa: E402
anon = TgCall()

from anony.core.health import HealthMonitor  # noqa: E402
health = HealthMonitor(
    app=app,
    db=db,
    userbot=userbot,
    calls=anon,
    language=lang,
    supervisor=supervisor,
    logger=logger,
)
_stopping = False


async def stop(reason: str = "requested") -> None:
    global _stopping
    if _stopping:
        return
    _stopping = True
    logger.info("Stopping... reason=%s", reason)

    await supervisor.close()
    for task in list(tasks):
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
        tasks.clear()

    if db.connection is not None:
        for chat_id in list(db.active_calls):
            media = queue.get_current(chat_id)
            if media:
                await db.save_queue(chat_id, queue.get_queue(chat_id))
                state = "playing" if await db.playing(chat_id) else "paused"
                await db.save_playback(chat_id, state, media.time)

    async def close_component(name: str, operation, timeout: int = 10) -> None:
        try:
            await asyncio.wait_for(operation, timeout=timeout)
        except TimeoutError:
            logger.warning("Timed out while stopping %s; continuing shutdown.", name)
        except Exception:
            logger.exception("Failed to stop %s cleanly; continuing shutdown.", name)

    await close_component("voice calls", anon.exit(), timeout=20)
    await close_component("feedback cleanup", feedback.close())
    await close_component("bot", app.exit())
    await close_component("assistants", userbot.exit(), timeout=20)
    if db.connection is not None:
        await close_component("process history", health.finish(reason))
        await close_component("database", db.close())
    await close_component("thumbnail downloader", thumb.close())

    logger.info("Stopped. reason=%s\n", reason)
