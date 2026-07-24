import importlib.util
import logging
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock


ROOT = Path(__file__).parents[1]


class Worker:
    def __init__(self, alive: bool):
        self.is_alive = alive


class AssistantFailoverTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.userbot = types.SimpleNamespace(
            accepting_slots={1, 2, 3},
            clients={1: "assistant-one", 2: "assistant-two", 3: "assistant-three"},
            is_accepting=lambda slot: slot in {1, 2, 3},
        )
        self.anon = types.SimpleNamespace(
            clients={
                1: Worker(True),
                2: Worker(False),
            }
        )
        fake_anony = types.ModuleType("anony")
        fake_anony.__path__ = []
        fake_anony.config = types.SimpleNamespace(
            DATABASE_PATH=str(Path(self.temp.name) / "test.db")
        )
        fake_anony.logger = logging.getLogger("test-assistant-failover")
        fake_anony.userbot = self.userbot
        fake_anony.anon = self.anon
        fake_core = types.ModuleType("anony.core")
        fake_core.__path__ = []
        self.previous_modules = {
            name: sys.modules.get(name)
            for name in ("anony", "anony.core")
        }
        sys.modules["anony"] = fake_anony
        sys.modules["anony.core"] = fake_core
        spec = importlib.util.spec_from_file_location(
            "assistant_failover_database_under_test",
            ROOT / "anony/core/database.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.db = module.SQLiteDB()

    async def asyncTearDown(self):
        self.temp.cleanup()
        for name, previous in self.previous_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous

    async def test_ready_slots_require_both_clients(self):
        self.assertEqual(self.db.ready_assistant_slots(), (1,))

    async def test_get_client_reassigns_a_chat_with_a_dead_worker(self):
        self.db.assistant[-1001] = 2

        async def assign(chat_id, slot=None):
            self.db.assistant[chat_id] = slot
            return slot

        self.db.set_assistant = AsyncMock(side_effect=assign)

        client = await self.db.get_client(-1001)

        self.assertEqual(client, "assistant-one")
        self.db.set_assistant.assert_awaited_once_with(-1001, 1)

    async def test_excluded_failed_slot_is_not_selected_again(self):
        self.anon.clients[2].is_alive = True
        self.db.assistant[-1001] = 1

        async def assign(chat_id, slot=None):
            self.db.assistant[chat_id] = slot
            return slot

        self.db.set_assistant = AsyncMock(side_effect=assign)

        client = await self.db.get_client(-1001, excluded={1})

        self.assertEqual(client, "assistant-two")
        self.db.set_assistant.assert_awaited_once_with(-1001, 2)


if __name__ == "__main__":
    unittest.main()
