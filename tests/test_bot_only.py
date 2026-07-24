import importlib.util
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


ROOT = Path(__file__).parents[1]


fake_anony = types.ModuleType("anony")
fake_anony.__path__ = []
fake_anony.config = SimpleNamespace(
    API_ID=1,
    API_HASH="hash",
    SESSIONS=(),
)
fake_anony.logger = MagicMock()

saved_anony = sys.modules.get("anony")
sys.modules["anony"] = fake_anony
try:
    spec = importlib.util.spec_from_file_location(
        "bot_only_userbot_under_test",
        ROOT / "anony/core/userbot.py",
    )
    userbot_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(userbot_module)
finally:
    if saved_anony is None:
        sys.modules.pop("anony", None)
    else:
        sys.modules["anony"] = saved_anony


class BotOnlyUserbotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fake_anony.logger.reset_mock()

    async def test_boot_continues_without_configured_sessions(self):
        db = SimpleNamespace(
            ensure_assistant_session=AsyncMock(),
            get_assistant_sessions=AsyncMock(return_value=[]),
        )
        fake_anony.db = db

        manager = userbot_module.Userbot()
        with patch.dict(sys.modules, {"anony": fake_anony}):
            await manager.boot()

        self.assertEqual(manager.clients, {})
        db.ensure_assistant_session.assert_not_awaited()
        fake_anony.logger.warning.assert_called_once_with(
            "No assistant session is configured; continuing in bot-only mode."
        )

    async def test_boot_continues_when_every_saved_session_fails(self):
        db = SimpleNamespace(
            ensure_assistant_session=AsyncMock(),
            get_assistant_sessions=AsyncMock(
                return_value=[
                    {
                        "slot": 1,
                        "session_string": "broken",
                        "enabled": True,
                    }
                ]
            ),
            update_assistant_session=AsyncMock(),
        )
        fake_anony.db = db

        manager = userbot_module.Userbot()
        manager._start_client = AsyncMock(side_effect=RuntimeError("bad session"))
        with patch.dict(sys.modules, {"anony": fake_anony}):
            await manager.boot()

        self.assertEqual(manager.clients, {})
        db.update_assistant_session.assert_awaited_once_with(1, enabled=False)
        fake_anony.logger.warning.assert_called_with(
            "No assistant session could be started; continuing in bot-only mode."
        )

    async def test_last_idle_session_can_be_disabled(self):
        client = AsyncMock()
        voice_client = AsyncMock()
        db = SimpleNamespace(
            get_assistant_session=AsyncMock(
                return_value={"slot": 1, "enabled": True}
            ),
            active_chats_for_assistant=MagicMock(return_value=[]),
            release_assistant_slot=AsyncMock(),
            update_assistant_session=AsyncMock(),
        )
        fake_anony.db = db
        fake_anony.anon = SimpleNamespace(clients={1: voice_client})

        manager = userbot_module.Userbot()
        manager.clients[1] = client
        with patch.dict(sys.modules, {"anony": fake_anony}):
            await manager.disable_session(1)

        self.assertEqual(manager.clients, {})
        self.assertEqual(fake_anony.anon.clients, {})
        voice_client.stop.assert_awaited_once()
        client.stop.assert_awaited_once()
        db.release_assistant_slot.assert_awaited_once_with(1)
        db.update_assistant_session.assert_awaited_once_with(1, enabled=False)

    async def test_busy_session_locks_without_interrupting_current_call(self):
        client = AsyncMock()
        voice_client = AsyncMock()
        db = SimpleNamespace(
            get_assistant_session=AsyncMock(
                return_value={"slot": 1, "enabled": True}
            ),
            active_chats_for_assistant=MagicMock(return_value=[-1001]),
            release_assistant_slot=AsyncMock(),
            update_assistant_session=AsyncMock(),
        )
        fake_anony.db = db
        fake_anony.anon = SimpleNamespace(clients={1: voice_client})

        manager = userbot_module.Userbot()
        manager.clients[1] = client
        with patch.dict(sys.modules, {"anony": fake_anony}):
            draining = await manager.disable_session(1)

        self.assertTrue(draining)
        self.assertFalse(manager.is_accepting(1))
        self.assertIn(1, manager.clients)
        self.assertIn(1, fake_anony.anon.clients)
        voice_client.stop.assert_not_awaited()
        client.stop.assert_not_awaited()
        db.release_assistant_slot.assert_not_awaited()
        db.update_assistant_session.assert_awaited_once_with(1, enabled=False)

    async def test_locked_session_disconnects_after_last_call(self):
        client = AsyncMock()
        voice_client = AsyncMock()
        db = SimpleNamespace(
            get_assistant_session=AsyncMock(
                return_value={"slot": 1, "enabled": False}
            ),
            active_chats_for_assistant=MagicMock(return_value=[]),
            release_assistant_slot=AsyncMock(),
        )
        fake_anony.db = db
        fake_anony.anon = SimpleNamespace(clients={1: voice_client})

        manager = userbot_module.Userbot()
        manager.clients[1] = client
        manager.locked.add(1)
        with patch.dict(sys.modules, {"anony": fake_anony}):
            finished = await manager.finish_draining(1)

        self.assertTrue(finished)
        self.assertEqual(manager.clients, {})
        self.assertEqual(fake_anony.anon.clients, {})
        voice_client.stop.assert_awaited_once()
        client.stop.assert_awaited_once()
        db.release_assistant_slot.assert_awaited_once_with(1)

    async def test_enable_unlocks_a_draining_session_in_place(self):
        client = AsyncMock()
        voice_client = AsyncMock()
        db = SimpleNamespace(
            get_assistant_session=AsyncMock(
                return_value={"slot": 1, "enabled": False}
            ),
            update_assistant_session=AsyncMock(),
        )
        fake_anony.db = db
        fake_anony.anon = SimpleNamespace(
            clients={1: voice_client},
            add_client=AsyncMock(),
        )

        manager = userbot_module.Userbot()
        manager.clients[1] = client
        manager.locked.add(1)
        with patch.dict(sys.modules, {"anony": fake_anony}):
            result = await manager.enable_session(1)

        self.assertIs(result, client)
        self.assertTrue(manager.is_accepting(1))
        fake_anony.anon.add_client.assert_not_awaited()
        db.update_assistant_session.assert_awaited_once_with(1, enabled=True)


if __name__ == "__main__":
    unittest.main()
