import importlib.util
import sys
import types as stdlib_types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from pyrogram import enums, types


ROOT = Path(__file__).parents[1]


def load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


callbacks = load_module("ui_callbacks_under_test", "anony/ui/callbacks.py")

fake_anony = stdlib_types.ModuleType("anony")
fake_anony.__path__ = []
fake_core = stdlib_types.ModuleType("anony.core")
fake_core.__path__ = []
fake_custom_emoji = stdlib_types.ModuleType("anony.core.custom_emoji")
fake_custom_emoji.custom_emoji_button = (
    lambda text, **kwargs: types.InlineKeyboardButton(text=text, **kwargs)
)
saved_modules = {
    name: sys.modules.get(name)
    for name in ("anony", "anony.core", "anony.core.custom_emoji")
}
sys.modules.update({
    "anony": fake_anony,
    "anony.core": fake_core,
    "anony.core.custom_emoji": fake_custom_emoji,
})
try:
    keyboards = load_module("ui_keyboards_under_test", "anony/ui/keyboards.py")
finally:
    for name, previous in saved_modules.items():
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous

messages = load_module("ui_messages_under_test", "anony/ui/messages.py")


class CallbackBuilderTests(unittest.TestCase):
    def test_existing_callback_shapes_are_preserved(self):
        self.assertEqual(
            callbacks.controls("pause", -100123),
            "controls pause -100123",
        )
        self.assertEqual(
            callbacks.controls("status", -100123, "q"),
            "controls status -100123 q",
        )
        self.assertEqual(callbacks.help(), "help")
        self.assertEqual(callbacks.help("back"), "help back")
        self.assertEqual(callbacks.language_change("my"), "lang_change my")
        self.assertEqual(
            callbacks.settings(-100123, "language"),
            "settings -100123 language",
        )
        self.assertEqual(
            callbacks.settings_language(-100123, "en"),
            "settings_lang -100123 en",
        )
        self.assertEqual(callbacks.session("view", 2, 0), "session view 2 0")
        self.assertEqual(
            callbacks.runtime_config("toggle", "auto_end"),
            "runtime_config toggle auto_end",
        )
        self.assertEqual(callbacks.stats("refresh"), "stats refresh")
        self.assertEqual(callbacks.trending(), "trending view")
        self.assertEqual(callbacks.setup(), "setup check")

    def test_invalid_or_oversized_tokens_are_rejected(self):
        with self.assertRaises(ValueError):
            callbacks.build("help", "two words")
        with self.assertRaises(ValueError):
            callbacks.build("x", "a" * 64)


class KeyboardPrimitiveTests(unittest.TestCase):
    def test_grid_preserves_order(self):
        items = [
            keyboards.button(str(index), callback_data=str(index))
            for index in range(5)
        ]
        rows = keyboards.grid(items, columns=2)
        self.assertEqual(
            [[button.text for button in row] for row in rows],
            [["0", "1"], ["2", "3"], ["4"]],
        )

    def test_navigation_and_confirmation_preserve_labels_and_styles(self):
        back = keyboards.back_row("‹ Back", "help back")
        home = keyboards.home_row("⬅️ Home")
        confirmation = keyboards.confirmation_keyboard(
            confirm_text="🗑 Remove permanently",
            confirm_callback="session confirm_remove 2 0",
            cancel_text="⬅️ Keep session",
            cancel_callback="session view 2 0",
        )

        self.assertEqual(back[0].callback_data, "help back")
        self.assertEqual(home[0].callback_data, "help home")
        confirm, cancel = confirmation.inline_keyboard[0]
        self.assertEqual(confirm.text, "🗑 Remove permanently")
        self.assertEqual(confirm.style, enums.ButtonStyle.DANGER)
        self.assertEqual(cancel.text, "⬅️ Keep session")
        self.assertEqual(cancel.callback_data, "session view 2 0")

    def test_pagination_matches_session_dashboard_shape(self):
        row = keyboards.pagination_row(
            page=1,
            page_count=4,
            callback_for_page=lambda page: callbacks.session("page", page),
            indicator_callback=callbacks.session("noop"),
        )
        self.assertEqual([button.text for button in row], ["‹", "2 / 4", "›"])
        self.assertEqual(
            [button.callback_data for button in row],
            ["session page 0", "session noop", "session page 2"],
        )


class StatusMessageTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_message_reuses_one_message(self):
        sent = stdlib_types.SimpleNamespace(
            id=42,
            edit_text=AsyncMock(return_value="edited"),
            edit_media=AsyncMock(return_value="media"),
            delete=AsyncMock(),
        )
        source = stdlib_types.SimpleNamespace(reply_text=AsyncMock(return_value=sent))

        status = await messages.StatusMessage.begin(source, "Searching…")
        self.assertEqual(status.id, 42)
        source.reply_text.assert_awaited_once_with("Searching…")

        await status.update("Downloading…")
        sent.edit_text.assert_awaited_once_with("Downloading…", reply_markup=None)
        await status.remove()
        sent.delete.assert_awaited_once_with()


if __name__ == "__main__":
    unittest.main()
