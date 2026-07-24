import asyncio
import importlib.util
import logging
import sys
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock


ROOT = Path(__file__).parents[1]


@dataclass
class FakeTrack:
    id: str
    channel_name: str | None = None
    duration: str = "00:00"
    duration_sec: int = 0
    title: str | None = None
    url: str | None = None
    file_path: str | None = None
    message_id: int = 0
    time: int = 0
    thumbnail: str | None = None
    user: str | None = None
    view_count: str | None = None
    video: bool = False


class FakeSearch:
    calls = 0

    def __init__(self, query, **kwargs):
        type(self).calls += 1

    async def next(self):
        return {"result": [{
            "id": "abcdefghijk",
            "channel": {"name": "Artist"},
            "duration": "3:20",
            "title": "Track",
            "thumbnails": [{"url": "https://example.com/thumb.jpg"}],
            "link": "https://youtube.com/watch?v=abcdefghijk",
            "viewCount": {"short": "1M"},
        }]}


class YouTubePerformanceTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved = {
            name: sys.modules.get(name)
            for name in ("yt_dlp", "py_yt", "anony", "anony.helpers")
        }
        fake_ytdlp = types.ModuleType("yt_dlp")
        fake_ytdlp.utils = types.SimpleNamespace(
            DownloadError=RuntimeError,
            ExtractorError=RuntimeError,
        )
        fake_py_yt = types.ModuleType("py_yt")
        fake_py_yt.Playlist = object
        fake_py_yt.VideosSearch = FakeSearch
        fake_anony = types.ModuleType("anony")
        fake_anony.__path__ = []
        fake_anony.logger = logging.getLogger(__name__)
        fake_helpers = types.ModuleType("anony.helpers")
        fake_helpers.Track = FakeTrack
        fake_helpers.utils = types.SimpleNamespace(
            to_seconds=lambda value: 200 if value == "3:20" else 0
        )
        sys.modules.update({
            "yt_dlp": fake_ytdlp,
            "py_yt": fake_py_yt,
            "anony": fake_anony,
            "anony.helpers": fake_helpers,
        })
        spec = importlib.util.spec_from_file_location(
            "youtube_performance_under_test",
            ROOT / "anony/core/youtube.py",
        )
        cls.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.module
        spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("youtube_performance_under_test", None)
        for name, previous in cls.saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous

    async def test_search_results_are_cached_without_sharing_message_state(self):
        FakeSearch.calls = 0
        youtube = self.module.YouTube()

        first = await youtube.search(" attention   song ", 10)
        second = await youtube.search("ATTENTION SONG", 20)

        self.assertEqual(FakeSearch.calls, 1)
        self.assertEqual(first.message_id, 10)
        self.assertEqual(second.message_id, 20)
        self.assertIsNot(first, second)

    async def test_concurrent_searches_share_one_request(self):
        FakeSearch.calls = 0
        youtube = self.module.YouTube()

        first, second = await asyncio.gather(
            youtube.search("same track", 10),
            youtube.search("SAME TRACK", 20),
        )

        self.assertEqual(FakeSearch.calls, 1)
        self.assertEqual(first.message_id, 10)
        self.assertEqual(second.message_id, 20)
        self.assertFalse(youtube._search_tasks)

    async def test_duplicate_downloads_share_one_task(self):
        youtube = self.module.YouTube()

        async def download_once(*args):
            await asyncio.sleep(0.02)
            return "downloads/singleflight.webm"

        youtube._download_once = AsyncMock(side_effect=download_once)
        results = await asyncio.gather(
            youtube.download("singleflight"),
            youtube.download("singleflight"),
        )

        self.assertEqual(youtube._download_once.await_count, 1)
        self.assertEqual(results, [
            "downloads/singleflight.webm",
            "downloads/singleflight.webm",
        ])
        self.assertFalse(youtube._download_tasks)

    async def test_named_download_reuses_search_result_and_direct_downloader(self):
        FakeSearch.calls = 0
        youtube = self.module.YouTube()
        youtube.download = AsyncMock(return_value="downloads/abcdefghijk.webm")

        result = await youtube.download_search(" attention   song ", 30)

        self.assertEqual(FakeSearch.calls, 1)
        youtube.download.assert_awaited_once_with("abcdefghijk", video=False)
        self.assertEqual(result.id, "abcdefghijk")
        self.assertEqual(result.file_path, "downloads/abcdefghijk.webm")
        self.assertEqual(result.message_id, 30)

    def test_downloader_has_bounded_network_behavior(self):
        source = (ROOT / "anony/core/youtube.py").read_text(encoding="utf-8")
        for option in (
            '"socket_timeout": 10',
            '"retries": 1',
            '"fragment_retries": 1',
            '"extractor_retries": 1',
            '"concurrent_fragment_downloads": 4',
        ):
            self.assertIn(option, source)
        self.assertIn("asyncio.wait_for", source)
        self.assertIn('"bestaudio[ext=webm][acodec=opus]/bestaudio/best"', source)
        self.assertIn("ydl.prepare_filename(info)", source)
        self.assertIn('Path("downloads").glob(f"{video_id}.*")', source)
        self.assertIn('async def download_search', source)


if __name__ == "__main__":
    unittest.main()
