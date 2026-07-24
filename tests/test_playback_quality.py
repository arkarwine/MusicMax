import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parents[1]

CONFIG_SPEC = importlib.util.spec_from_file_location(
    "playback_config_under_test",
    ROOT / "config.py",
)
config_module = importlib.util.module_from_spec(CONFIG_SPEC)
CONFIG_SPEC.loader.exec_module(config_module)

class PlaybackConfigurationTests(unittest.TestCase):
    def test_resource_friendly_defaults(self):
        with patch.dict(
            "os.environ",
            {
                "AUDIO_QUALITY": "",
                "VIDEO_QUALITY": "",
                "VIDEO_FPS": "",
            },
        ):
            config = config_module.Config()
        self.assertEqual(config.AUDIO_QUALITY, "medium")
        self.assertEqual(config.VIDEO_QUALITY, "360p")
        self.assertEqual(config.VIDEO_FPS, 20)

    def test_runtime_values_are_validated_and_exported(self):
        config = config_module.Config()
        self.assertEqual(config.set_runtime("audio_quality", "high"), "high")
        self.assertEqual(config.set_runtime("video_quality", "360P"), "360p")
        self.assertEqual(config.set_runtime("video_fps", "24"), "24")
        with self.assertRaises(ValueError):
            config.set_runtime("audio_quality", "studio")
        with self.assertRaises(ValueError):
            config.set_runtime("video_quality", "1080p")
        with self.assertRaises(ValueError):
            config.set_runtime("video_fps", "29")

    def test_calls_use_configured_quality(self):
        calls = (ROOT / "anony/core/calls.py").read_text(encoding="utf-8")
        worker = (
            ROOT / "anony/core/voice_worker_process.py"
        ).read_text(encoding="utf-8")
        self.assertIn("audio_quality=config.AUDIO_QUALITY", calls)
        self.assertIn("video_quality=config.VIDEO_QUALITY", calls)
        self.assertIn("video_fps=config.VIDEO_FPS", calls)
        self.assertIn('"medium": types.AudioQuality.MEDIUM', worker)
        self.assertIn('"360p": (640, 360)', worker)
        self.assertIn("VideoParameters(width, height, fps, False)", worker)


if __name__ == "__main__":
    unittest.main()
