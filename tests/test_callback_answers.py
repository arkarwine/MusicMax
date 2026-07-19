import unittest
from os import environ
from unittest.mock import AsyncMock, patch

import pyrogram

environ.setdefault("API_ID", "1")
environ.setdefault("API_HASH", "test")
environ.setdefault("BOT_TOKEN", "123:test")
environ.setdefault("OWNER_ID", "1")

from anony.core.bot import Bot


class CallbackAnswerTests(unittest.IsolatedAsyncioTestCase):
    async def test_expired_callback_answer_is_non_fatal(self):
        bot = object.__new__(Bot)
        with patch.object(
            pyrogram.Client,
            "answer_callback_query",
            new=AsyncMock(side_effect=pyrogram.errors.QueryIdInvalid()),
        ):
            self.assertFalse(await bot.answer_callback_query("expired"))


if __name__ == "__main__":
    unittest.main()
