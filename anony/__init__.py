# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import time
import asyncio
import logging
from logging.handlers import RotatingFileHandler

logging.basicConfig(
    format="[%(asctime)s - %(levelname)s] - %(name)s: %(message)s",
    datefmt="%d-%b-%y %H:%M:%S",
    handlers=[
        RotatingFileHandler("log.txt", maxBytes=10485760, backupCount=5),
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


__version__ = "3.0.3"

from config import Config  # noqa: E402

config = Config()
config.check()
tasks = []
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

from anony.core.telegram import Telegram  # noqa: E402
from anony.core.youtube import YouTube  # noqa: E402
tg = Telegram()
yt = YouTube()

from anony.helpers import Queue, Thumbnail  # noqa: E402
queue = Queue()
thumb = Thumbnail()

from anony.core.calls import TgCall  # noqa: E402
anon = TgCall()


async def stop() -> None:
    logger.info("Stopping...")
    for task in tasks:
        task.cancel()
        try:
            await task
        except asyncio.exceptions.CancelledError:
            pass

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

    await close_component("bot", app.exit())
    await close_component("assistants", userbot.exit(), timeout=20)
    await close_component("database", db.close())
    await close_component("thumbnail downloader", thumb.close())

    logger.info("Stopped.\n")
