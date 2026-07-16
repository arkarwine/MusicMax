import importlib.util
import logging
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pyrogram import enums, types


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "rich_messages_under_test",
    ROOT / "anony/core/rich_messages.py",
)
rich_messages = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = rich_messages
SPEC.loader.exec_module(rich_messages)

def heading(level: int, text: str) -> str:
    return f"<h{level}>{rich_messages.unicode_heading(text)}</h{level}>"
def centered_heading(
    text: str, *, divider: bool = True, icon: str | None = None
) -> str:
    icon = rich_messages.heading_icon(text) if icon is None else icon
    result = (
        '<table><tr><th align="center">'
        + (f"{icon} " if icon else "")
        + rich_messages.unicode_heading(text)
        + "</th></tr></table>"
    )
    return result

def table_header(text: str) -> str:
    return f'<th align="center">{rich_messages.unicode_heading(text)}</th>'






class HeadingPromotionTests(unittest.TestCase):
    def test_heading_font_uses_title_case_small_caps(self):
        self.assertEqual(
            rich_messages.unicode_heading("bot insights"),
            "Bᴏᴛ Iɴsɪɢʜᴛs",
        )
        self.assertEqual(
            rich_messages.unicode_heading("what would you like to do?"),
            "Wʜᴀᴛ Wᴏᴜʟᴅ Yᴏᴜ Lɪᴋᴇ Tᴏ Dᴏ?",
        )
    def test_primary_play_heading_and_track_entity(self):
        title = "Cyberpunk: Edgerunners | I Really Want to Stay at Your House"
        source = (
            '🎵 <b>Nᴏᴡ Pʟᴀʏɪɴɢ</b>\n\n'
            f'<b><a href="https://t.me/example">{title}</a></b>\n'
            '<blockquote>3:15 · requested by <a href=tg://user?id=7935506256>Arkar</a></blockquote>'
        )

        result = rich_messages.promote_heading(source)

        play_heading = (
            "<h1>🎵 " + rich_messages.unicode_heading("Now playing") + "</h1>"
        )
        self.assertTrue(result.startswith(play_heading))
        self.assertIn(
            f'<b><a href="https://t.me/example">{title}</a></b>',
            result,
        )
        self.assertNotIn("<h2>", result)
        self.assertNotIn("<table", result[:result.index("</h1>")])
        self.assertIn(
            '<a href="tg://user?id=7935506256">Arkar</a>', result
        )
        self.assertNotIn("href=tg://", result)
        self.assertEqual(result[:result.index("</h1>")].count("🎵"), 1)

    def test_action_and_setup_heading_levels(self):
        queued = rich_messages.promote_heading(
            "✅ <b>Queued · #3</b>\n\nTrack"
        )
        setup = rich_messages.promote_heading(
            "⚠️ <b>One thing left</b>\n\nAllow invitations"
        )

        self.assertTrue(queued.startswith(centered_heading("Added to queue · #3")))
        self.assertTrue(setup.startswith(centered_heading("Setup required")))

    def test_playlist_and_session_action_cards_use_compact_headings(self):
        playlist = rich_messages.promote_heading(
            "<u><b>Added 12 tracks from the playlist to queue:</b></u>\n\n"
        )
        remove = rich_messages.promote_heading(
            "🗑 <b>Remove session 2?</b>\n\nThis cannot be undone."
        )
        prompt = rich_messages.promote_heading(
            "🎵 <b>Which song would you like?</b>\n\nReply with a title."
        )

        self.assertTrue(playlist.startswith(
            centered_heading("Added 12 tracks from the playlist to queue", divider=False)
        ))
        self.assertTrue(remove.startswith(centered_heading("Remove session 2?")))
        self.assertTrue(prompt.startswith(
            centered_heading("Which song would you like?")
        ))

    def test_stats_summary_uses_localized_table_rows(self):
        source = (
            "<b>Bot insights</b>\n\n"
            "<blockquote>👥 <b>6 total</b>\n"
            "├ 2 people\n"
            "└ 4 groups</blockquote>\n\n"
            "<blockquote>🎵 <b>12 plays today</b>\n"
            "├ 3 active chats\n"
            "└ 4 daily average</blockquote>\n\n"
        )

        result = rich_messages.promote_heading(source)

        self.assertIn("<table bordered striped>", result)
        self.assertEqual(result.count("<table bordered striped>"), 2)
        self.assertIn('<tr><td colspan="2">👥 <b>6 total</b></td></tr>', result)
        self.assertIn(
            '<tr><td><b>People</b></td><td align="center">2</td></tr>', result
        )
        self.assertIn(
            '<tr><td><b>Groups</b></td><td align="center">4</td></tr>', result
        )
        self.assertNotIn("<blockquote>", result)
        self.assertEqual(result.count("<hr/>"), 0)

    def test_stats_activity_uses_period_columns(self):
        source = (
            "<b>Bot insights</b>\n\n"
            "<blockquote>Overview · Value\n"
            "\u251c Users: 2\n"
            "\u2514 Lifetime plays: <b>450</b></blockquote>\n\n"
            "<blockquote>Activity · Today · 7 days · 30 days\n"
            "\u251c Plays: <code>3</code> \u00b7 <code>12</code> "
            "\u00b7 <code>450</code>\n"
            "\u2514 New chats: <code>1</code> \u00b7 <code>4</code> "
            "\u00b7 <code>80</code></blockquote>"
        )

        result = rich_messages.promote_heading(source)

        self.assertIn(
            "<tr>" + table_header("Overview") + table_header("Value") + "</tr>", result
        )
        self.assertEqual(result.count("<table bordered striped>"), 2)
        self.assertEqual(result.count("<hr/>"), 0)
        self.assertIn(
            "<tr>" + table_header("Activity") + table_header("Today")
            + table_header("7 days") + table_header("30 days")
            + "</tr>",
            result,
        )
        self.assertIn(
            '<tr><td><b>Plays</b></td><td align="center">3</td>', result
        )




    def test_queue_separates_current_track_from_upcoming_tracks(self):
        source = (
            "☰ <b>Queue</b>\n\n"
            '<b><a href="https://example.com">Current track</a></b>\n'
            "<blockquote>Requested by someone</blockquote>\n"
            "<blockquote expandable>2 · Next track</blockquote>"
        )

        result = rich_messages.promote_heading(source)

        self.assertEqual(result.count("<hr/>"), 1)
        self.assertIn("</blockquote><hr/><blockquote>", result)

    def test_configuration_and_status_use_tables(self):
        configuration = rich_messages.promote_heading(
            "<b>Runtime configuration</b>\n\n"
            "<b>Queue limit</b>\n<code>15</code>\n\n"
            "<b>Auto end</b> •\n<code>on</code>\n\n"
            "<blockquote>Use the controls below.</blockquote>"
        )
        status = rich_messages.promote_heading(
            "<b>Advanced status</b>\n\n"
            "<blockquote>⚙️ <b>System</b>\n"
            "├ CPU: <code>12%</code>\n└ Memory: <code>34%</code></blockquote>\n\n"
            "<blockquote>🟢 <b>Ready</b>\n"
            "└ Updated 14 Jul · 17:29 UTC</blockquote>"
        )

        self.assertEqual(configuration.count("<hr/>"), 1)
        self.assertIn(
            "<table striped><tr>" + table_header("Setting")
            + table_header("Value") + "</tr>", configuration
        )
        self.assertIn("<tr><td>Queue limit</td><td><code>15</code></td></tr>", configuration)
        self.assertIn("<tr><td>Auto end •</td><td><code>on</code></td></tr>", configuration)
        self.assertIn("</table><hr/><blockquote>", configuration)
        self.assertEqual(status.count("<table striped>"), 2)
        self.assertEqual(status.count("<details>"), 2)
        self.assertIn("<details><summary>⚙️ <b>System</b></summary>", status)
        self.assertIn("<details><summary>🟢 <b>Ready</b></summary>", status)
        self.assertIn(
            '<tr><td colspan="2">Updated 14 Jul · 17:29 UTC</td></tr>',
            status,
        )
        self.assertIn(
            "<tr><td><b>CPU</b></td><td><code>12%</code></td></tr>", status
        )
        self.assertIn(
            "<tr><td><b>Memory</b></td><td><code>34%</code></td></tr>", status
        )
        self.assertNotIn("<blockquote>", status)
        self.assertEqual(status.count("<hr/>"), 0)

    def test_active_streams_use_a_bordered_table(self):
        source = (
            f"<b>{rich_messages.unicode_heading('Active streams')}</b>\n\n"
            "<blockquote># · Chat · Track\n"
            "├ 1 | <code>-1001</code> | First track\n"
            "└ 2 | <code>-1002</code> | No queued track"
            "</blockquote>"
        )

        result = rich_messages.promote_heading(source)

        self.assertTrue(result.startswith(centered_heading("Active streams")))
        self.assertIn("<table bordered striped>", result)
        self.assertIn(
            "<tr>" + table_header("#") + table_header("Chat")
            + table_header("Track") + "</tr>",
            result,
        )
        self.assertIn(
            '<tr><td align="center">1</td>'
            '<td align="center"><code>-1001</code></td><td>First track</td></tr>',
            result,
        )
        self.assertIn(
            '<tr><td align="center">2</td>'
            '<td align="center"><code>-1002</code></td>'
            "<td>No queued track</td></tr>",
            result,
        )

    def test_trending_uses_rank_track_and_play_columns(self):
        source = (
            "🔥 <b>Trending tracks</b>\n"
            "<blockquote>Most played · last 30 days</blockquote>\n"
            '1️⃣ <a href="https://example.com/one">First track</a>  '
            "<code>12 plays</code>\n"
            "2️⃣ Second track  <code>8 plays</code>"
        )

        result = rich_messages.promote_heading(source)

        self.assertIn("<table striped>", result)
        self.assertIn(
            "<tr>" + table_header("Rank") + table_header("Track")
            + table_header("Plays") + "</tr>",
            result,
        )
        self.assertIn(
            '<tr><td><b>1️⃣</b></td><td><a href="https://example.com/one">'
            "First track</a></td><td><code>12</code></td></tr>",
            result,
        )
        self.assertIn(
            "<tr><td><b>2️⃣</b></td><td>Second track</td>"
            "<td><code>8</code></td></tr>",
            result,
        )
        self.assertNotIn("<code>12 plays</code>", result)

    def test_sudo_access_uses_a_bordered_role_table(self):
        source = (
            "<b>Sudo access</b>\n\n"
            "<blockquote>Role · Account\n"
            '├ Owner: <a href="tg://user?id=1">Owner</a>\n'
            '└ Sudo user: <a href="tg://user?id=2">Helper</a>'
            "</blockquote>"
        )

        result = rich_messages.promote_heading(source)

        self.assertTrue(result.startswith(centered_heading("Sudo access")))
        self.assertIn("<table bordered striped>", result)
        self.assertIn(
            "<tr>" + table_header("Role") + table_header("Account")
            + "</tr>",
            result,
        )
        self.assertIn(
            '<tr><td><b>Owner</b></td><td align="center">'
            '<a href="tg://user?id=1">Owner</a></td></tr>',
            result,
        )
        self.assertIn(
            '<tr><td><b>Sudo user</b></td><td align="center">'
            '<a href="tg://user?id=2">Helper</a></td></tr>',
            result,
        )

    def test_sessions_dashboard_and_detail_use_tables(self):
        dashboard = rich_messages.promote_heading(
            "🤖 <b>Assistants</b> · 2 active / 5 total\n\n"
            "Choose an account."
        )
        detail = rich_messages.promote_heading(
            "<b>Assistant session 3</b>\n"
            "<b>Account:</b> @helper\n"
            "Session 3 · Active · startup\n"
            "<code>123456</code> · 2 active calls\n\n"
            "<blockquote expandable><b>Action failed</b>\n"
            "RuntimeError · At least one session must remain active.</blockquote>"
        )

        self.assertIn(
            "<tr><td><b>Active</b></td><td><code>2</code></td></tr>", dashboard
        )
        self.assertIn(
            "<tr><td><b>Disabled</b></td><td><code>3</code></td></tr>", dashboard
        )
        self.assertIn(
            "<tr><td><b>Total</b></td><td><code>5</code></td></tr>", dashboard
        )
        self.assertIn("Choose an account.", dashboard)
        self.assertIn(
            "<tr><td><b>Session</b></td><td><code>3</code></td></tr>", detail
        )
        self.assertIn("<tr><td><b>State</b></td><td>Active</td></tr>", detail)
        self.assertIn("<tr><td><b>Account</b></td><td>@helper</td></tr>", detail)
        self.assertIn("<tr><td><b>Source</b></td><td>Startup</td></tr>", detail)
        self.assertIn(
            "<tr><td><b>User ID</b></td><td><code>123456</code></td></tr>", detail
        )
        self.assertIn(
            "<tr><td><b>Active calls</b></td><td><code>2</code></td></tr>", detail
        )
        self.assertIn("<blockquote><b>Action failed</b>", detail)
        self.assertIn("RuntimeError", detail)

    def test_welcome_is_a_centered_borderless_table(self):
        result = rich_messages.promote_heading(
            "👋 <b>Welcome, ArKar</b>\n\nYour music room."
        )

        self.assertTrue(result.startswith(centered_heading("Welcome, ArKar")))
        self.assertNotIn("<table bordered", result)

    def test_plain_body_newlines_are_explicit_but_preformatted_lines_are_not(self):
        result = rich_messages.promote_heading(
            "<b>Controls</b>\n\n"
            "First line\nSecond line\n\n"
            "<pre>raw\nlines</pre>\nTail"
        )

        self.assertIn(
            "First line<br>Second line<pre>raw\nlines</pre>Tail",
            result,
        )
        self.assertNotIn("<pre>raw<br>lines</pre>", result)

    def test_help_session_and_access_headings(self):
        help_text = rich_messages.promote_heading(
            "<b>Commands in the 🛠 Controls category:</b>\n\n/setup"
        )
        session = rich_messages.promote_heading(
            "<b>𝗔𝘀𝘀𝗶𝘀𝘁𝗮𝗻𝘁 𝗦𝗲𝘀𝘀𝗶𝗼𝗻 2</b>\n\nState: active"
        )
        access = rich_messages.promote_heading(
            "👤 <b>Pʟᴀʏʙᴀᴄᴋ Aᴄᴄᴇss · 4</b>\n"
        )

        self.assertTrue(help_text.startswith(centered_heading("Controls")))
        self.assertTrue(session.startswith(
            centered_heading("Assistant Session 2")
        ))
        self.assertTrue(access.startswith(
            centered_heading("Playback access", divider=False)
        ))

    def test_non_heading_and_burmese_body_are_unchanged(self):
        self.assertIsNone(rich_messages.promote_heading("Searching…"))
        self.assertIsNone(rich_messages.promote_heading("မြန်မာ စာသား"))


class SerializationTests(unittest.TestCase):
    def test_keyboard_serialization_removes_pyrogram_type_markers(self):
        markup = types.InlineKeyboardMarkup([[
            types.InlineKeyboardButton("Play", callback_data="play")
        ]])

        result = rich_messages.bot_api_dict(markup)

        self.assertNotIn("_", result)
        self.assertNotIn("_", result["inline_keyboard"][0][0])
        self.assertEqual(
            result["inline_keyboard"][0][0]["callback_data"], "play"
        )
        self.assertNotIn("style", result["inline_keyboard"][0][0])

    def test_keyboard_styles_use_bot_api_values(self):
        markup = types.InlineKeyboardMarkup([[
            types.InlineKeyboardButton(
                "Remove",
                callback_data="remove",
                style=enums.ButtonStyle.DANGER,
            )
        ]])

        result = rich_messages.bot_api_dict(markup)

        self.assertEqual(
            result["inline_keyboard"][0][0]["style"], "danger"
        )

    def test_media_sources_use_documented_rich_references(self):
        service = rich_messages.RichMessageService(
            AsyncMock(), "token", logging.getLogger(__name__)
        )
        with ExitStack() as stack:
            url_message, url_files = service._rich_message(
                "<h1>Welcome</h1>",
                rich_messages.RichMedia("https://example.com/art.jpg", "photo"),
                stack,
            )

        self.assertEqual(url_files, {})
        self.assertTrue(
            url_message["html"].startswith(
                '<img src="tg://photo?id=hero"/>\n<h1>Welcome</h1>'
            )
        )
        self.assertEqual(
            url_message["media"][0]["media"]["media"],
            "https://example.com/art.jpg",
        )

    def test_media_can_follow_the_first_table(self):
        service = rich_messages.RichMessageService(
            AsyncMock(), "token", logging.getLogger(__name__)
        )
        with ExitStack() as stack:
            message, _ = service._rich_message(
                "<table><tr><td>Title</td></tr></table><hr/><p>Body</p>",
                rich_messages.RichMedia(
                    "https://example.com/art.jpg",
                    "photo",
                    "after_first_block",
                ),
                stack,
            )

        html = message["html"]
        self.assertLess(
            html.index("</table>"),
            html.index('<img src="tg://photo?id=hero"/>'),
        )
        self.assertLess(html.index("<hr/>"), html.index('<img src="tg://photo?id=hero"/>'))
        self.assertLess(html.index('<img src="tg://photo?id=hero"/>'), html.index("<p>"))

    def test_media_can_follow_a_native_heading(self):
        service = rich_messages.RichMessageService(
            AsyncMock(), "token", logging.getLogger(__name__)
        )
        with ExitStack() as stack:
            message, _ = service._rich_message(
                "<h1>🎵 Nᴏᴡ Pʟᴀʏɪɴɢ</h1><p>Body</p>",
                rich_messages.RichMedia(
                    "https://example.com/art.jpg",
                    "photo",
                    "after_first_block",
                ),
                stack,
            )

        html = message["html"]
        self.assertLess(
            html.index("</h1>"),
            html.index('<img src="tg://photo?id=hero"/>'),
        )
        self.assertLess(
            html.index('<img src="tg://photo?id=hero"/>'),
            html.index("<p>"),
        )

    def test_local_media_uses_multipart_attachment(self):
        service = rich_messages.RichMessageService(
            AsyncMock(), "token", logging.getLogger(__name__)
        )
        with tempfile.TemporaryDirectory() as directory:
            artwork = Path(directory) / "art.jpg"
            artwork.write_bytes(b"image")
            with ExitStack() as stack:
                message, files = service._rich_message(
                    "<h2>Track</h2>",
                    rich_messages.RichMedia(artwork, "photo"),
                    stack,
                )
                self.assertEqual(
                    message["media"][0]["media"]["media"],
                    "attach://rich_media_0",
                )
                self.assertEqual(files["rich_media_0"][1], "art.jpg")
                self.assertFalse(files["rich_media_0"][0].closed)

    def test_native_blocks_and_block_media_are_supported(self):
        service = rich_messages.RichMessageService(
            AsyncMock(), "token", logging.getLogger(__name__)
        )
        blocks = [
            {"type": "heading", "text": "Queue", "size": 1},
            {"type": "paragraph", "text": "Nothing queued"},
        ]

        with ExitStack() as stack:
            message, files = service._rich_message(
                blocks,
                rich_messages.RichMedia("photo-file-id", "photo"),
                stack,
            )

        self.assertEqual(files, {})
        self.assertEqual(message["blocks"][0]["type"], "photo")
        self.assertEqual(
            message["blocks"][0]["photo"],
            {"type": "photo", "media": "photo-file-id"},
        )
        self.assertEqual(message["blocks"][1:], blocks)
        self.assertNotIn("media", message)

    def test_invalid_rich_content_is_rejected_per_message(self):
        service = rich_messages.RichMessageService(
            AsyncMock(), "token", logging.getLogger(__name__)
        )
        with ExitStack() as stack, self.assertRaises(ValueError):
            service._rich_message({"unsupported": True}, None, stack)


class RichMessageServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_returns_bound_pyrogram_message(self):
        bound = SimpleNamespace(id=81)
        client = SimpleNamespace(get_messages=AsyncMock(return_value=bound))
        service = rich_messages.RichMessageService(
            client, "token", logging.getLogger(__name__)
        )
        service._request = AsyncMock(return_value={"message_id": 81})
        markup = types.InlineKeyboardMarkup([[
            types.InlineKeyboardButton("Open", callback_data="open")
        ]])

        result = await service.send(
            -1001,
            "<h1>Queue</h1>",
            fallback_text="<b>Queue</b>",
            reply_markup=markup,
            reply_parameters={"message_id": 4},
            message_thread_id=7,
        )

        self.assertIs(result, bound)
        method, payload, files = service._request.await_args.args
        self.assertEqual(method, "sendRichMessage")
        self.assertEqual(payload["chat_id"], -1001)
        self.assertEqual(payload["message_thread_id"], 7)
        self.assertEqual(payload["reply_parameters"], {"message_id": 4})
        self.assertEqual(
            payload["reply_markup"]["inline_keyboard"][0][0]["callback_data"],
            "open",
        )
        self.assertEqual(files, {})
        client.get_messages.assert_awaited_once_with(-1001, 81)

    async def test_per_message_failure_falls_back_without_disabling(self):
        service = rich_messages.RichMessageService(
            AsyncMock(), "token", logging.getLogger(__name__)
        )
        service._request = AsyncMock(return_value=None)

        result = await service.send(1, "<h3>Request failed</h3>")

        self.assertIsNone(result)
        self.assertTrue(service.capable)

    async def test_only_permanent_method_failure_disables_rich_messages(self):
        class Response:
            status = 404

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return None

            async def json(self, **_):
                return {
                    "ok": False,
                    "error_code": 404,
                    "description": "Not Found: method not found",
                }

        class Session:
            closed = False

            def post(self, *_args, **_kwargs):
                return Response()

        service = rich_messages.RichMessageService(
            AsyncMock(), "token", logging.getLogger(__name__)
        )
        service.session = Session()

        result = await service._request(
            "sendRichMessage",
            {"chat_id": 1, "rich_message": {"html": "<h1>Queue</h1>"}},
            {},
        )

        self.assertIsNone(result)
        self.assertFalse(service.capable)

    async def test_disabled_service_does_not_open_a_session(self):
        service = rich_messages.RichMessageService(
            AsyncMock(), "token", logging.getLogger(__name__), enabled=False
        )

        self.assertIsNone(await service.send(1, "<h1>Queue</h1>"))
        self.assertIsNone(service.session)


class LocaleHeadingTests(unittest.TestCase):
    def test_burmese_keeps_body_with_english_fallback_heading(self):
        import types as stdlib_types

        fake_anony = stdlib_types.ModuleType("anony")
        fake_anony.__path__ = []
        fake_anony.app = object()
        fake_anony.db = object()
        fake_anony.logger = logging.getLogger(__name__)
        fake_core = stdlib_types.ModuleType("anony.core")
        fake_core.__path__ = []
        fake_custom = stdlib_types.ModuleType("anony.core.custom_emoji")
        fake_rich = stdlib_types.ModuleType("anony.core.rich_messages")
        fake_rich.unicode_heading = rich_messages.unicode_heading


        class LocalizedText(str):
            def format(self, *args, **kwargs):
                return type(self)(super().format(*args, **kwargs))

        fake_custom.localized_text = LocalizedText
        module_names = (
            "anony",
            "anony.core",
            "anony.core.custom_emoji",
            "language_headings_under_test",
            "anony.core.rich_messages",
        )
        saved = {name: sys.modules.get(name) for name in module_names}
        sys.modules.update({
            "anony": fake_anony,
            "anony.core": fake_core,
            "anony.core.custom_emoji": fake_custom,
            "anony.core.rich_messages": fake_rich,
        })
        try:
            spec = importlib.util.spec_from_file_location(
                "language_headings_under_test",
                ROOT / "anony/core/lang.py",
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            languages = module.Language().languages
        finally:
            for name, previous in saved.items():
                if previous is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = previous

        self.assertTrue(languages["my"]["play_media"].startswith(
            f"<b>{rich_messages.unicode_heading('Now playing')}</b>"
        ))
        self.assertIn("ခေါင်းစဉ်", languages["my"]["play_media"])
        self.assertTrue(languages["my"]["help_menu"].startswith(
            f"<b>{rich_messages.unicode_heading('What would you like to do?')}</b>"
        ))
        self.assertEqual(
            languages["my"]["heading_stats"],
            rich_messages.unicode_heading("Bot insights"),
        )
        self.assertNotIn("{9}", languages["en"]["stats_caption"])
        self.assertNotIn("{6}", languages["en"]["stats_caption"])
        self.assertNotIn("{9}", languages["my"]["stats_caption"])
        self.assertNotIn("{6}", languages["my"]["stats_caption"])
        self.assertTrue(
            rich_messages.promote_heading(languages["my"]["play_media"])
            .startswith(
                "<h1>🎵 " + rich_messages.unicode_heading("Now playing") + "</h1>"
            )
        )
        self.assertTrue(
            rich_messages.promote_heading(languages["my"]["help_menu"])
            .startswith(centered_heading("What would you like to do?"))
        )


class BroadcastTableTests(unittest.TestCase):
    def test_completion_uses_bordered_delivery_table(self):
        source = (
            "<b>Broadcast complete</b>\n\n"
            "<blockquote>Audience · Targets · Delivered · Failed\n"
            "├ Groups: <code>6</code> · <code>5</code> · <code>1</code>\n"
            "├ Users: <code>4</code> · <code>4</code> · <code>0</code>\n"
            "└ Total: <code>10</code> · <code>9</code> · <code>1</code>"
            "</blockquote>\n\nForward mode · 2.4s"
        )

        result = rich_messages.promote_heading(source)

        self.assertTrue(result.startswith(centered_heading("Broadcast complete")))
        self.assertIn("<table bordered striped>", result)
        self.assertIn(
            "<tr>" + table_header("Audience") + table_header("Targets")
            + table_header("Delivered") + table_header("Failed") + "</tr>",
            result,
        )
        self.assertIn(
            '<tr><td><b>Total</b></td>'
            '<td align="center"><code>10</code></td>'
            '<td align="center"><code>9</code></td>'
            '<td align="center"><code>1</code></td></tr>',
            result,
        )
        self.assertIn("<footer>Forward mode · 2.4s</footer>", result)
        self.assertNotIn("<blockquote>", result)

    def test_progress_uses_live_delivery_columns(self):
        source = (
            "<b>Broadcast in progress</b>\n\n"
            "<blockquote>Audience · Targets · Delivered · Failed\n"
            "├ Groups: <code>6</code> · <code>3</code> · <code>1</code>\n"
            "├ Users: <code>4</code> · <code>2</code> · <code>0</code>\n"
            "└ Total: <code>10</code> · <code>5</code> · <code>1</code>"
            "</blockquote>\n\nCopy mode"
        )

        result = rich_messages.promote_heading(source)

        self.assertTrue(
            result.startswith(centered_heading("Broadcast in progress"))
        )
        self.assertIn("<table bordered striped>", result)
        self.assertIn(
            "<tr>" + table_header("Audience") + table_header("Targets")
            + table_header("Delivered") + table_header("Failed") + "</tr>",
            result,
        )
        self.assertIn(
            '<tr><td><b>Total</b></td>'
            '<td align="center"><code>10</code></td>'
            '<td align="center"><code>5</code></td>'
            '<td align="center"><code>1</code></td></tr>',
            result,
        )
        self.assertIn("<footer>Copy mode</footer>", result)


if __name__ == "__main__":
    unittest.main()
