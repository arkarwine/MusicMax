import importlib.util
import sys
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


ROOT = Path(__file__).parents[1]


@dataclass
class Media:
    id: str
    file_path: str = ""
    video: bool = False
    time: int = 0
    duration_sec: int = 0
    message_id: int = 0


@dataclass
class Track(Media):
    pass


def load_recovery_module(fake_anony, ensure_assistant):
    fake_helpers = types.ModuleType("anony.helpers")
    fake_helpers.Media = Media
    fake_helpers.Track = Track
    fake_play = types.ModuleType("anony.helpers._play")
    fake_play.ensure_assistant = ensure_assistant

    module_names = ("anony", "anony.helpers", "anony.helpers._play")
    saved = {name: sys.modules.get(name) for name in module_names}
    sys.modules["anony"] = fake_anony
    sys.modules["anony.helpers"] = fake_helpers
    sys.modules["anony.helpers._play"] = fake_play
    try:
        spec = importlib.util.spec_from_file_location(
            "playback_recovery_under_test",
            ROOT / "anony/core/recovery.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module, fake_helpers, fake_play
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


class PlaybackRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.events = []
        self.status = SimpleNamespace(id=91, lang=None, edit_text=AsyncMock())
        self.media = Track(
            id="track",
            file_path="https://example.com/audio.webm",
            time=37,
            duration_sec=180,
        )
        self.anon = SimpleNamespace(
            clients={1: object()},
            reset_assistant_call=AsyncMock(
                side_effect=lambda chat_id: self.events.append("reset")
            ),
            play_media=AsyncMock(
                side_effect=lambda *args, **kwargs: self.events.append("play") or True
            ),
            pause=AsyncMock(),
        )
        self.app = SimpleNamespace(
            send_message=AsyncMock(return_value=self.status),
        )
        self.db = SimpleNamespace(
            get_call=AsyncMock(return_value=False),
            get_playback_state=AsyncMock(return_value="paused"),
        )
        self.lang = SimpleNamespace(
            get_lang=AsyncMock(
                return_value={
                    "recovery_checking": "Restoring",
                    "recovery_resuming": "Reconnecting",
                    "recovery_file_missing": "Missing",
                }
            )
        )
        self.queue = SimpleNamespace(get_current=MagicMock(return_value=self.media))
        self.userbot = SimpleNamespace(accepting_slots={1})
        self.yt = SimpleNamespace(download=AsyncMock())
        self.logger = MagicMock()
        fake_anony = types.ModuleType("anony")
        fake_anony.__path__ = []
        for name in (
            "anon",
            "app",
            "db",
            "lang",
            "queue",
            "userbot",
            "yt",
            "logger",
        ):
            setattr(fake_anony, name, getattr(self, name))
        self.ensure_assistant = AsyncMock(return_value=True)
        (
            self.module,
            self.fake_helpers,
            self.fake_play,
        ) = load_recovery_module(fake_anony, self.ensure_assistant)
        self.fake_anony = fake_anony

    def module_context(self):
        return patch.dict(
            sys.modules,
            {
                "anony": self.fake_anony,
                "anony.helpers": self.fake_helpers,
                "anony.helpers._play": self.fake_play,
            },
        )

    async def test_recovery_resets_stale_call_before_playing(self):
        with self.module_context():
            started = await self.module.PlaybackRecovery().play(-1001)

        self.assertTrue(started)
        self.assertEqual(self.events, ["reset", "play"])
        self.anon.play_media.assert_awaited_once()
        call = self.anon.play_media.await_args
        self.assertEqual(call.kwargs["seek_time"], 37)
        self.assertTrue(call.kwargs["new_session"])
        self.assertTrue(call.kwargs["recovery"])

    async def test_recovery_preserves_paused_state(self):
        with self.module_context():
            await self.module.PlaybackRecovery().play(-1001)

        self.anon.pause.assert_awaited_once_with(-1001)

    async def test_startup_waits_for_a_transient_voice_worker(self):
        recovery = self.module.PlaybackRecovery()
        recovery.sessions = [{"chat_id": -1001, "state": "playing"}]
        recovery.play = AsyncMock(return_value=True)
        self.anon.clients.clear()

        async def worker_becomes_ready(_):
            self.anon.clients[1] = object()

        with patch.object(
            self.module.asyncio,
            "sleep",
            new=AsyncMock(side_effect=worker_becomes_ready),
        ) as sleep:
            await recovery.run_startup()

        sleep.assert_awaited_once_with(1)
        recovery.play.assert_awaited_once_with(-1001)

    def test_recovery_failure_path_keeps_the_saved_queue(self):
        source = (ROOT / "anony/core/calls.py").read_text(encoding="utf-8")

        self.assertIn("async def keep_saved_queue", source)
        self.assertIn('await db.save_playback(chat_id, "waiting", media.time)', source)
        self.assertIn(
            'if recovery:\n                return await keep_saved_queue',
            source,
        )


if __name__ == "__main__":
    unittest.main()
