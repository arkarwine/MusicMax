import asyncio
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image


ROOT = Path(__file__).parents[1]
ANONY_STUB = types.ModuleType("anony")
ANONY_STUB.config = types.SimpleNamespace(DEFAULT_THUMB="default.jpg")
HELPERS_STUB = types.ModuleType("anony.helpers")
HELPERS_STUB.Track = object

original_anony = sys.modules.get("anony")
original_helpers = sys.modules.get("anony.helpers")
sys.modules["anony"] = ANONY_STUB
sys.modules["anony.helpers"] = HELPERS_STUB
try:
    spec = importlib.util.spec_from_file_location(
        "thumbnail_under_test",
        ROOT / "anony/helpers/_thumbnails.py",
    )
    thumbnail_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(thumbnail_module)
finally:
    if original_anony is None:
        sys.modules.pop("anony", None)
    else:
        sys.modules["anony"] = original_anony
    if original_helpers is None:
        sys.modules.pop("anony.helpers", None)
    else:
        sys.modules["anony.helpers"] = original_helpers


class PlayImageCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_requests_reuse_a_local_valid_jpeg(self):
        thumbnail = object.__new__(thumbnail_module.Thumbnail)
        thumbnail._play_image_lock = asyncio.Lock()
        downloads = []

        async def save_thumb(output_path, url):
            downloads.append(url)
            Image.new("RGBA", (40, 20), (20, 40, 60, 128)).save(
                output_path,
                "PNG",
            )
            await asyncio.sleep(0)
            return output_path

        thumbnail.save_thumb = save_thumb
        previous_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            os.chdir(temp_dir)
            try:
                first, second = await asyncio.gather(
                    thumbnail.play_image("https://example.com/play.png"),
                    thumbnail.play_image("https://example.com/play.png"),
                )
                third = await thumbnail.play_image(
                    "https://example.com/play.png"
                )
                self.assertEqual(first, second)
                self.assertEqual(second, third)
                self.assertEqual(downloads, ["https://example.com/play.png"])
                with Image.open(first) as cached:
                    self.assertEqual(cached.format, "JPEG")
                    self.assertEqual(cached.mode, "RGB")
            finally:
                os.chdir(previous_cwd)

    async def test_generated_artwork_is_deduplicated_compact_jpeg(self):
        thumbnail = thumbnail_module.Thumbnail()
        downloads = []

        async def save_thumb(output_path, url):
            downloads.append(url)
            Image.new("RGB", (640, 360), (30, 60, 90)).save(
                output_path,
                "JPEG",
            )
            await asyncio.sleep(0)
            return output_path

        thumbnail.save_thumb = save_thumb
        song = SimpleNamespace(
            id="abcdefghijk",
            thumbnail="https://example.com/track.jpg",
            channel_name="Artist",
            view_count="1M",
            title="Track",
            duration="3:20",
        )
        previous_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            os.chdir(temp_dir)
            try:
                first, second = await asyncio.gather(
                    thumbnail.generate(song),
                    thumbnail.generate(song),
                )
                self.assertEqual(first, second)
                self.assertEqual(downloads, [song.thumbnail])
                self.assertTrue(first.endswith(".jpg"))
                with Image.open(first) as artwork:
                    self.assertEqual(artwork.format, "JPEG")
                    self.assertEqual(artwork.mode, "RGB")
                    self.assertEqual(artwork.size, (1280, 720))
            finally:
                os.chdir(previous_cwd)


if __name__ == "__main__":
    unittest.main()
