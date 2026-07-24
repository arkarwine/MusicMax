import asyncio
import importlib.util
import logging
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "voice_worker_proxy_under_test",
    ROOT / "anony/core/voice_worker.py",
)
voice_worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(voice_worker)


class VoiceWorkerProtocolTests(unittest.IsolatedAsyncioTestCase):
    def make_client(self):
        return voice_worker.VoiceWorkerClient(
            slot=2,
            session_string="secret-session",
            api_id=1,
            api_hash="hash",
            logger=logging.getLogger("test-voice-worker"),
        )

    async def test_success_response_resolves_only_its_request(self):
        client = self.make_client()
        future = asyncio.get_running_loop().create_future()
        client._pending["2:1"] = future

        client._handle_message({
            "kind": "response",
            "id": "2:1",
            "ok": True,
            "result": 12.5,
        })

        self.assertEqual(await future, 12.5)
        self.assertNotIn("2:1", client._pending)

    async def test_remote_failure_preserves_exception_type(self):
        client = self.make_client()
        future = asyncio.get_running_loop().create_future()
        client._pending["2:2"] = future

        client._handle_message({
            "kind": "response",
            "id": "2:2",
            "ok": False,
            "error_type": "NoActiveGroupCall",
            "error": "No video chat",
        })

        with self.assertRaises(voice_worker.VoiceWorkerError) as raised:
            await future
        self.assertEqual(raised.exception.remote_type, "NoActiveGroupCall")

    async def test_worker_exit_event_is_emitted_once_after_readiness(self):
        events = []
        client = self.make_client()
        client._event_handler = events.append
        client._ever_ready = True
        reader = asyncio.StreamReader()
        reader.feed_eof()
        client._reader = reader

        await client._reader_loop()

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "worker_exit")
        self.assertEqual(events[0]["slot"], 2)

    def test_relabel_updates_public_session_slot(self):
        client = self.make_client()
        client.relabel(1)
        self.assertEqual(client.slot, 1)


class VoiceWorkerArchitectureTests(unittest.TestCase):
    def test_child_process_is_project_independent(self):
        source = (
            ROOT / "anony/core/voice_worker_process.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("from anony", source)
        self.assertNotIn("import anony", source)
        self.assertIn(
            "PyTgCalls(app, workers=2, cache_duration=100)",
            source,
        )

    def test_main_call_controller_contains_no_native_voice_client(self):
        source = (ROOT / "anony/core/calls.py").read_text(encoding="utf-8")
        self.assertNotIn("from pytgcalls", source)
        self.assertNotIn("from ntgcalls", source)
        self.assertIn("VoiceWorkerClient(", source)
        self.assertIn("isolated voice worker", source)

    def test_session_string_is_not_a_process_argument(self):
        source = (
            ROOT / "anony/core/voice_worker.py"
        ).read_text(encoding="utf-8")
        process_call = source[
            source.index("asyncio.create_subprocess_exec"):
            source.index("self._reader, self._writer")
        ]
        self.assertNotIn("session_string", process_call)
        self.assertIn('"session_string": self._session_string', source)


if __name__ == "__main__":
    unittest.main()
