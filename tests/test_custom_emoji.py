import importlib.util
import unittest
from pathlib import Path

from pyrogram import enums


SPEC = importlib.util.spec_from_file_location(
    "custom_emoji_under_test",
    Path(__file__).parents[1] / "anony" / "core" / "custom_emoji.py",
)
custom_emoji = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(custom_emoji)


class CustomEmojiTextTests(unittest.TestCase):
    def tearDown(self):
        custom_emoji.set_custom_emoji_supported(False)

    def test_strip_handles_quotes_entities_multiline_and_multiple_tags(self):
        text = (
            '<b>A</b> <tg-emoji emoji-id="1">▶</tg-emoji>\n'
            "<tg-emoji emoji-id='2&amp;'>⏹</tg-emoji> <i>B</i>"
        )
        self.assertEqual(
            custom_emoji.strip_custom_emoji_tags(text),
            "<b>A</b> ▶\n⏹ <i>B</i>",
        )

    def test_render_retains_tags_only_when_supported(self):
        text = '<tg-emoji emoji-id="1">▶</tg-emoji> <b>Play</b>'
        custom_emoji.set_custom_emoji_supported(False)
        self.assertEqual(
            custom_emoji.render_custom_emoji_text(text), "▶ <b>Play</b>"
        )
        custom_emoji.set_custom_emoji_supported(True)
        self.assertEqual(custom_emoji.render_custom_emoji_text(text), text)

    def test_localized_marker_survives_template_operations(self):
        text = custom_emoji.localized_text("<b>{0}</b>")
        formatted = text.format("Hello") + "!"
        self.assertTrue(custom_emoji.is_localized_text(formatted))
        self.assertEqual(formatted, "<b>Hello</b>!")


class CustomEmojiButtonTests(unittest.TestCase):
    def tearDown(self):
        custom_emoji.set_custom_emoji_supported(False)
        custom_emoji.set_custom_emoji_button_icons_supported(True)

    def test_button_uses_icon_without_duplicate_fallback(self):
        custom_emoji.set_custom_emoji_supported(True)
        button = custom_emoji.custom_emoji_button(
            '<tg-emoji emoji-id="5465443221003836735">▷</tg-emoji> Play',
            callback_data="play",
            style=enums.ButtonStyle.SUCCESS,
        )
        self.assertEqual(button.text, " Play")
        self.assertEqual(
            str(button.icon_custom_emoji_id), "5465443221003836735"
        )
        self.assertEqual(button.style, enums.ButtonStyle.SUCCESS)

        markup = custom_emoji.types.InlineKeyboardMarkup([[button]])
        fallback = custom_emoji.keyboard_without_custom_icons(markup)
        rebuilt = fallback.inline_keyboard[0][0]
        self.assertEqual(rebuilt.text, "▷ Play")
        self.assertIsNone(rebuilt.icon_custom_emoji_id)
        self.assertEqual(rebuilt.style, enums.ButtonStyle.SUCCESS)

    def test_invalid_id_and_unsupported_mode_use_fallback(self):
        custom_emoji.set_custom_emoji_supported(True)
        invalid = custom_emoji.custom_emoji_button(
            '<tg-emoji emoji-id="invalid">▷</tg-emoji> Play'
        )
        self.assertEqual(invalid.text, "▷ Play")
        self.assertIsNone(invalid.icon_custom_emoji_id)

        custom_emoji.set_custom_emoji_supported(False)
        unsupported = custom_emoji.custom_emoji_button(
            '<tg-emoji emoji-id="123">▷</tg-emoji> Play'
        )
        self.assertEqual(unsupported.text, "▷ Play")
        self.assertIsNone(unsupported.icon_custom_emoji_id)

    def test_icon_only_button_has_valid_invisible_text_and_clean_fallback(self):
        custom_emoji.set_custom_emoji_button_icons_supported(True)
        custom_emoji.set_custom_emoji_supported(True)
        button = custom_emoji.custom_emoji_button(
            '<tg-emoji emoji-id="123">▷</tg-emoji>', callback_data="play"
        )
        self.assertEqual(button.text, "\u2063")

        markup = custom_emoji.types.InlineKeyboardMarkup([[button]])
        fallback = custom_emoji.keyboard_without_custom_icons(markup)
        self.assertEqual(fallback.inline_keyboard[0][0].text, "▷")

    def test_button_rejection_state_is_cached(self):
        custom_emoji.set_custom_emoji_supported(True)
        custom_emoji.set_custom_emoji_button_icons_supported(False)
        button = custom_emoji.custom_emoji_button(
            '<tg-emoji emoji-id="123">▷</tg-emoji>', callback_data="play"
        )
        self.assertEqual(button.text, "▷")
        self.assertIsNone(button.icon_custom_emoji_id)


if __name__ == "__main__":
    unittest.main()
