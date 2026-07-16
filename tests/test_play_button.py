import ast
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


spec = importlib.util.spec_from_file_location(
    "play_button_config_under_test",
    ROOT / "config.py",
)
config_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config_module)


class PlaybackButtonConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = config_module.Config()
        self.config.PLAY_BUTTON_TEXT = ""
        self.config.PLAY_BUTTON_URL = ""

    def test_button_requires_valid_text_and_url(self):
        self.assertIsNone(self.config.playback_button())

        self.config.PLAY_BUTTON_TEXT = "Open channel"
        self.assertIsNone(self.config.playback_button())

        self.config.PLAY_BUTTON_URL = "@anonxmusic"
        self.assertEqual(
            self.config.playback_button(),
            ("Open channel", "https://t.me/anonxmusic"),
        )

        self.config.PLAY_BUTTON_URL = "not a url"
        self.assertIsNone(self.config.playback_button())

    def test_runtime_values_can_be_updated_and_disabled(self):
        self.assertEqual(
            self.config.set_runtime("play_button_text", " Open channel "),
            "Open channel",
        )
        self.assertEqual(
            self.config.set_runtime("play_button_url", "@anonxmusic"),
            "https://t.me/anonxmusic",
        )
        self.assertEqual(
            self.config.playback_button(),
            ("Open channel", "https://t.me/anonxmusic"),
        )

        self.config.set_runtime("play_button_url", "-")
        self.assertIsNone(self.config.playback_button())
        self.assertEqual(
            self.config.runtime_display("play_button_url"),
            "disabled",
        )

    def test_controls_append_the_configured_url_button(self):
        tree = ast.parse(
            (ROOT / "anony/helpers/_inline.py").read_text(encoding="utf-8")
        )
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "playback_button"
        ]
        url_keywords = [
            keyword
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            for keyword in node.keywords
            if keyword.arg == "url"
        ]

        self.assertEqual(len(calls), 1)
        self.assertTrue(url_keywords)


if __name__ == "__main__":
    unittest.main()
