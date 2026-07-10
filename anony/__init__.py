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

    await app.exit()
    await userbot.exit()
    await db.close()
    await thumb.close()

    logger.info("Stopped.\n")
