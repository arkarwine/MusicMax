import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "play_message_under_test",
    ROOT / "anony/core/play_message.py",
)
play_message = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = play_message
SPEC.loader.exec_module(play_message)


DEFAULT = (
    "# 🎵 Now playing\n\n"
    "- **Title:** {title_link}\n"
    "- **Duration:** {duration}\n"
    "- **Requested by:** {requester}"
)


class PlayMessageRendererTests(unittest.TestCase):
    def render(self, template=DEFAULT, **overrides):
        values = {
            "title": "Charlie Puth - Attention [Official Video]",
            "url": "https://example.com/watch?v=1&list=2",
            "duration": "3:33",
            "requester": (
                '<a href="tg://user?id=42">Ar &amp; Kar</a>'
            ),
        }
        values.update(overrides)
        return play_message.render_play_message(
            template,
            DEFAULT,
            **values,
        )

    def test_default_template_produces_native_and_legacy_layouts(self):
        rendered = self.render()

        self.assertTrue(
            rendered.rich_html.startswith("<h1>🎵 Now playing</h1>")
        )
        self.assertIn("<ul>", rendered.rich_html)
        self.assertEqual(rendered.rich_html.count("<li>"), 3)
        self.assertIn(
            '<a href="https://example.com/watch?v=1&amp;list=2">'
            "Charlie Puth - Attention...</a>",
            rendered.rich_html,
        )
        self.assertIn(
            '<a href="tg://user?id=42">Ar &amp; Kar</a>',
            rendered.rich_html,
        )
        self.assertTrue(
            rendered.fallback_html.startswith("<b>🎵 Now playing</b>")
        )
        self.assertEqual(rendered.fallback_html.count("• "), 3)
        self.assertFalse(rendered.used_default)

    def test_arbitrary_text_order_omissions_repetitions_and_braces(self):
        template = (
            "## Duration {duration}\n\n"
            "> Listener {requester}\n\n"
            "{title}\n{title}\n{{premium}}"
        )

        rendered = self.render(template)

        self.assertIn("<h2>Duration 3:33</h2>", rendered.rich_html)
        self.assertIn("<blockquote>Listener ", rendered.rich_html)
        self.assertEqual(
            rendered.rich_html.count("Charlie Puth - Attention..."),
            2,
        )
        self.assertIn("{premium}", rendered.rich_html)
        self.assertNotIn("https://example.com", rendered.rich_html)

    def test_metadata_cannot_inject_markdown_or_html(self):
        rendered = self.render(
            "# {title}\n\n{source_url}",
            title="**<script>alert(1)</script>**",
        )

        self.assertNotIn("<script>", rendered.rich_html)
        self.assertIn("&lt;script&gt;", rendered.rich_html)
        self.assertNotIn("<b>", rendered.rich_html)
        self.assertIn(
            "https://example.com/watch?v=1&amp;list=2",
            rendered.rich_html,
        )

    def test_supported_markdown_blocks_and_inline_styles(self):
        template = (
            "# Header\n\n"
            "1. **Bold**\n"
            "2. __Italic__\n\n"
            "~~Gone~~ and `code`\n\n"
            "[Support](https://t.me/example)"
        )

        rendered = self.render(template)

        self.assertIn("<ol><li><b>Bold</b></li>", rendered.rich_html)
        self.assertIn("<li><i>Italic</i></li></ol>", rendered.rich_html)
        self.assertIn("<s>Gone</s> and <code>code</code>", rendered.rich_html)
        self.assertIn(
            '<a href="https://t.me/example">Support</a>',
            rendered.rich_html,
        )

    def test_render_failure_uses_localized_default(self):
        rendered = self.render("{unknown}")

        self.assertTrue(rendered.used_default)
        self.assertIn("<h1>🎵 Now playing</h1>", rendered.rich_html)

    def test_media_selection_covers_every_configuration(self):
        self.assertEqual(
            play_message.select_play_media("cover", "artwork"),
            ("cover", "artwork"),
        )
        self.assertEqual(
            play_message.select_play_media("cover", None),
            ("cover",),
        )
        self.assertEqual(
            play_message.select_play_media(None, "artwork"),
            ("artwork",),
        )
        self.assertEqual(
            play_message.select_play_media(None, None),
            (),
        )
        self.assertEqual(
            play_message.select_play_media("same", "same"),
            ("same",),
        )

    def test_oversized_caption_uses_localized_default(self):
        rendered = self.render("x" * 1025)

        self.assertTrue(rendered.used_default)
        self.assertIn("<b>🎵 Now playing</b>", rendered.fallback_html)


if __name__ == "__main__":
    unittest.main()

