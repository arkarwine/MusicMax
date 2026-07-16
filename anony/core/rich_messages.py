"""Bot API 10.2 rich-message transport with safe legacy fallback hooks."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import unicodedata
from contextlib import ExitStack
from dataclasses import dataclass
from enum import Enum
from html import unescape
from io import IOBase
from pathlib import Path

import aiohttp


_TAG_RE = re.compile(r"<[^>]+>")
_TG_EMOJI_RE = re.compile(
    r"<tg-emoji\b[^>]*>(.*?)</tg-emoji\s*>", re.I | re.S
)
_LEADING_HEADING_RE = re.compile(
    r"^\s*(?:(?:<tg-emoji\b[^>]*>.*?</tg-emoji\s*>)|[^\w<\n])+\s*"
    r"(?:<u>)?<b>(?P<title>.*?)</b>(?:</u>)?",
    re.I | re.S,
)
_PLAIN_HEADING_RE = re.compile(
    r"^\s*(?:<u>)?<b>(?P<title>.*?)</b>(?:</u>)?", re.I | re.S
)
_UNDERLINE_HEADING_RE = re.compile(
    r"^\s*<u>(?P<title>.*?)</u>", re.I | re.S
)
_SECONDARY_TRACK_RE = re.compile(
    r"\n\n<b>(<a\b[^>]*>.*?</a>)</b>", re.I | re.S
)
_BLOCKQUOTE_RE = re.compile(
    r"<blockquote>(?P<body>.*?)</blockquote>", re.I | re.S
)
_HEADING_TAG_RE = re.compile(
    r"<h(?P<level>[1-6])>(?P<body>.*?)</h(?P=level)>", re.I | re.S
)
_TABLE_HEADER_RE = re.compile(
    r"(?P<open><th\b[^>]*>)(?P<body>.*?)(?P<close></th>)", re.I | re.S
)
_HTML_TOKEN_RE = re.compile(r"(<[^>]+>|&(?:#\d+|#x[0-9a-f]+|\w+);)", re.I)
_UNQUOTED_HREF_RE = re.compile(
    r'(<a\b[^>]*\bhref\s*=\s*)(?!["\x27])([^\s>]+)', re.I
)
_ADJACENT_BLOCKQUOTES_RE = re.compile(
    r"</blockquote>\s*<blockquote>", re.I
)
_BLOCK_TAGS = (
    r"(?:h[1-6]|blockquote|pre|table|details|ul|ol|footer|aside|"
    r"tg-collage|tg-slideshow)"
)
_BREAKS_AFTER_BLOCK_RE = re.compile(
    rf"((?:</?{_BLOCK_TAGS}\b[^>]*>|<hr\s*/?>))(?:<br>)+", re.I
)
_BREAKS_BEFORE_BLOCK_RE = re.compile(
    rf"(?:<br>)+(?=(?:</?{_BLOCK_TAGS}\b[^>]*>|<hr\s*/?>))", re.I
)

_RUNTIME_SETTING_RE = re.compile(
    r"<b>(?P<label>[^<]+)</b>(?P<marker> •)?\s*\n"
    r"<code>(?P<value>.*?)</code>", re.S
)

_SMALL_CAPS = str.maketrans({
    "ᴀ": "a", "ʙ": "b", "ᴄ": "c", "ᴅ": "d", "ᴇ": "e",
    "ғ": "f", "ɢ": "g", "ʜ": "h", "ɪ": "i", "ᴊ": "j",
    "ᴋ": "k", "ʟ": "l", "ᴍ": "m", "ɴ": "n", "ᴏ": "o",
    "ᴘ": "p", "ǫ": "q", "ʀ": "r", "s": "s", "ᴛ": "t", "ᴜ": "u",
    "ᴠ": "v", "ᴡ": "w", "x": "x", "ʏ": "y", "ᴢ": "z",
})

_TITLE_RENAMES = {
    "now playing": "Now playing",
    "queue": "Queue",
    "what would you like to do?": "What would you like to do?",
    "choose a language": "Choose a language",
    "assistant sessions": "Assistant sessions",
    "assistants": "Assistant sessions",
    "advanced status": "Advanced status",
    "trending tracks": "Trending tracks",
    "runtime configuration": "Runtime configuration",
    "ready to play": "Ready to play",
    "one thing left": "Setup required",
    "setup required": "Setup required",
    "thanks for adding me": "Welcome",
    "welcome": "Welcome",
    "new chat log": "New chat log",
    "new user log": "New user log",
    "list of active streams:": "Active streams",
    "playback access": "Playback access",
    "add an assistant": "Add an assistant",
    "phone number": "Phone number",
    "check telegram": "Check Telegram",
    "two-step verification": "Two-step verification",
    "request failed": "Request failed",
    "bot insights": "Bot insights",
    "settings": "Settings",
    "controls": "Controls",
    "access": "Access",
    "safety": "Safety",
    "bot": "Bot",
    "music": "Music",
    "insights": "Insights",
    "sudo": "Sudo",
    "sudo access": "Sudo access",
    "which song would you like?": "Which song would you like?",
    "sign-in failed": "Sign-in failed",
    "log group configured": "Log group configured",
    "log group cleared": "Log group cleared",
    "could not configure the log group": "Could not configure the log group",
    "online": "Online",
    "pong!": "Pong",
}

_HEADER_ICONS = {
    "Now playing": "🎵",
    "Queue": "☰",
    "What would you like to do?": "🎛️",
    "Choose a language": "🌐",
    "Assistant sessions": "🤖",
    "Advanced status": "⚙️",
    "Trending tracks": "🔥",
    "Runtime configuration": "⚙️",
    "Ready to play": "✅",
    "Setup required": "⚠️",
    "Welcome": "👋",
    "New chat log": "📝",
    "New user log": "📝",
    "Active streams": "🎧",
    "Playback access": "👤",
    "Add an assistant": "➕",
    "Phone number": "📱",
    "Check Telegram": "✉️",
    "Two-step verification": "🔐",
    "Request failed": "⚠️",
    "Bot insights": "📊",
    "Settings": "⚙️",
    "Controls": "🛠️",
    "Access": "🔐",
    "Safety": "🛡️",
    "Bot": "🤖",
    "Music": "🎵",
    "Insights": "📊",
    "Sudo": "⚡",
    "Sudo access": "⚡",
    "Which song would you like?": "🎵",
    "Sign-in failed": "⚠️",
    "Log group configured": "✅",
    "Log group cleared": "✅",
    "Could not configure the log group": "⚠️",
    "Online": "🟢",
    "Pong": "⚡",
}


_PRIMARY = {
    "Now playing", "Queue", "What would you like to do?", "Choose a language",
    "Assistant sessions", "Advanced status", "Trending tracks",
    "Runtime configuration", "Active streams", "Playback access",
    "Bot insights", "Settings", "Welcome",
    "Controls", "Access", "Safety", "Bot", "Music", "Insights", "Sudo", "Sudo access",
}
_EXCLUDED = {"usage:", "output:", "owner:", "sudo users:"}
_HEADING_FONT = str.maketrans({
    "a": "ᴀ", "b": "ʙ", "c": "ᴄ", "d": "ᴅ", "e": "ᴇ",
    "f": "ғ", "g": "ɢ", "h": "ʜ", "i": "ɪ", "j": "ᴊ",
    "k": "ᴋ", "l": "ʟ", "m": "ᴍ", "n": "ɴ", "o": "ᴏ",
    "p": "ᴘ", "q": "ǫ", "r": "ʀ", "s": "s", "t": "ᴛ",
    "u": "ᴜ", "v": "ᴠ", "w": "ᴡ", "x": "x", "y": "ʏ", "z": "ᴢ",
})
_SMALL_CAP_GLYPHS = frozenset(
    glyph for glyph in _HEADING_FONT.values()
    if isinstance(glyph, str) and not glyph.isascii()
)


def unicode_heading(value: str) -> str:
    """Apply title case with Unicode small caps after each initial."""
    if any(char in _SMALL_CAP_GLYPHS for char in value):
        return value
    titled = re.sub(
        r"[A-Za-z]+",
        lambda match: match.group(0)[:1].upper() + match.group(0)[1:].lower(),
        value,
    )
    return titled.translate(_HEADING_FONT)

def heading_icon(title: str) -> str:
    icon = _HEADER_ICONS.get(title)
    if icon:
        return icon
    lowered = title.casefold()
    if lowered.startswith("added "):
        return "✅"
    if lowered.startswith("assistant session"):
        return "🤖"
    if lowered.startswith("remove session"):
        return "🗑️"
    if lowered.startswith("welcome"):
        return "👋"
    if any(word in lowered for word in ("failed", "error", "could not")):
        return "⚠️"
    return ""


def _style_heading(match: re.Match) -> str:
    parts = _HTML_TOKEN_RE.split(match.group("body"))
    body = "".join(
        part if part.startswith(("<", "&")) else unicode_heading(part)
        for part in parts
    )
    return f'<h{match.group("level")}>{body}</h{match.group("level")}>'


def _style_table_header(match: re.Match) -> str:
    opening = match.group("open")
    if not re.search(r"\balign\s*=", opening, re.I):
        opening = opening[:-1] + ' align="center">'
    parts = _HTML_TOKEN_RE.split(match.group("body"))
    body = "".join(
        part if part.startswith(("<", "&")) else unicode_heading(part)
        for part in parts
    )
    return opening + body + match.group("close")


def _center_leading_heading(rich: str) -> str:
    heading = re.match(
        r"<h(?P<level>[1-6])>(?P<body>.*?)</h(?P=level)>",
        rich,
        re.I | re.S,
    )
    if heading is None:
        return rich
    header = (
        '<table><tr><th align="center">'
        + heading.group("body")
        + "</th></tr></table>"
    )
    return header + rich[heading.end():]


def _insert_before_last_blockquote(rich: str) -> str:
    index = rich.rfind("<blockquote>")
    if index < 0:
        return rich
    return rich[:index].rstrip() + "\n<hr/>\n" + rich[index:]


def _add_section_separators(rich: str, title: str) -> str:
    if title == "Queue":
        replacement = "</blockquote>\n<hr/>\n<blockquote>"
        return _ADJACENT_BLOCKQUOTES_RE.sub(replacement, rich, count=1)
    if title == "Runtime configuration":
        return _insert_before_last_blockquote(rich)
    return rich

def _format_runtime_config_table(rich: str) -> str:
    heading_end = rich.find("</h1>")
    divider_start = rich.find("<hr/>", heading_end)
    if heading_end < 0 or divider_start < 0:
        return rich

    heading_end += len("</h1>")
    settings = rich[heading_end:divider_start]
    matches = list(_RUNTIME_SETTING_RE.finditer(settings))
    if not matches or _RUNTIME_SETTING_RE.sub("", settings).strip():
        return rich

    rows = ["<tr><th>Setting</th><th>Value</th></tr>"]
    for match in matches:
        label = match.group("label") + (match.group("marker") or "")
        rows.append(
            f"<tr><td>{label}</td>"
            f"<td><code>{match.group('value')}</code></td></tr>"
        )
    table = "<table striped>" + "".join(rows) + "</table>"
    return (
        rich[:heading_end]
        + "\n"
        + table
        + "\n"
        + rich[divider_start:]
    )



def _legacy_summary_table(rich: str) -> str:
    quotes = list(_BLOCKQUOTE_RE.finditer(rich))
    if not quotes:
        return rich
    section = rich[quotes[0].start():quotes[-1].end()]
    if _BLOCKQUOTE_RE.sub("", section).strip():
        return rich

    rows = []
    for quote in quotes:
        lines = [line.strip() for line in quote.group("body").split("<br>")]
        if len(lines) < 2 or any(not line for line in lines):
            return rich
        details = [re.sub(r"^[\u251c\u2514\u2502]\s*", "", line) for line in lines[1:]]
        rows.append(
            f"<tr><th>{lines[0]}</th><td>{'<br>'.join(details)}</td></tr>"
        )
    table = "<table striped>" + "".join(rows) + "</table>"
    return rich[:quotes[0].start()] + table + rich[quotes[-1].end():]


def _summary_metric_row(line: str, *, center_value: bool = False) -> str:
    line = re.sub(r"^[\u251c\u2514\u2502]\s*", "", line).strip()
    value_attr = ' align="center"' if center_value else ""
    label_value = re.fullmatch(
        r"(?P<label>[^:]+):\s+(?P<value>.+)", line, re.S
    )
    if label_value:
        return (
            f"<tr><td><b>{label_value.group('label').strip()}</b></td>"
            f"<td{value_attr}>"
            f"{label_value.group('value').strip()}</td></tr>"
        )

    leading_value = re.fullmatch(
        r"(?P<value>\d[\d.,]*(?:[KMB])?)\s+(?P<label>.+)",
        line,
        re.IGNORECASE,
    )
    if leading_value:
        label = leading_value.group("label")
        label = label[:1].upper() + label[1:]
        return (
            f"<tr><td><b>{label}</b></td>"
            f"<td{value_attr}>{leading_value.group('value')}</td></tr>"
        )

    trailing_value = re.fullmatch(
        r"(?P<label>.+?)\s+"
        r"(?P<value>\d[\w:.,%+-]*(?:\s+\d[\w:.,%+-]*)*)",
        line,
        re.IGNORECASE,
    )
    if trailing_value:
        return (
            f"<tr><td><b>{trailing_value.group('label')}</b></td>"
            f"<td{value_attr}>{trailing_value.group('value')}</td></tr>"
        )

    return f'<tr><td colspan="2">{line}</td></tr>'


def _summary_table(
    lines: list[str], *, bordered: bool = False,
    center_values: bool = False, expandable: bool = False,
) -> str:
    headers = [part.strip() for part in lines[0].split(" · ")]
    table_tag = "<table bordered striped>" if bordered else "<table striped>"
    value_attr = ' align="center"' if center_values else ""
    period_rows = []
    period_pattern = re.compile(
        r"^[\u251c\u2514\u2502]\s*(?P<label>[^:]+):\s*"
        r"<code>(?P<today>.*?)</code>\s*\u00b7\s*"
        r"<code>(?P<week>.*?)</code>\s*\u00b7\s*"
        r"<code>(?P<month>.*?)</code>$",
        re.I | re.S,
    )
    for line in lines[1:]:
        match = period_pattern.fullmatch(line)
        if match:
            period_rows.append(
                f"<tr><td><b>{match.group('label').strip()}</b></td>"
                f"<td{value_attr}>{match.group('today')}</td>"
                f"<td{value_attr}>{match.group('week')}</td>"
                f"<td{value_attr}>{match.group('month')}</td></tr>"
            )

    if period_rows and len(period_rows) == len(lines) - 1:
        if len(headers) == 4:
            header = "<tr>" + "".join(
                f"<th>{value}</th>" for value in headers
            ) + "</tr>"
        else:
            header = (
                "<tr><th>Activity</th><th>Today</th>"
                "<th>7 days</th><th>30 days</th></tr>"
            )
        rows = header + "".join(period_rows)
        return f"{table_tag}{rows}</table>"

    if expandable:
        rows = []
    elif len(headers) == 2:
        rows = [f"<tr><th>{headers[0]}</th><th>{headers[1]}</th></tr>"]
    else:
        rows = [f'<tr><td colspan="2">{lines[0]}</td></tr>']
    rows.extend(
        _summary_metric_row(line, center_value=center_values)
        for line in lines[1:]
    )
    table = table_tag + "".join(rows) + "</table>"
    if expandable:
        return f"<details><summary>{lines[0]}</summary>{table}</details>"
    return table


def _format_summary_table(
    rich: str, *, bordered: bool = False,
    center_values: bool = False, expandable: bool = False,
) -> str:
    quotes = list(_BLOCKQUOTE_RE.finditer(rich))
    if not quotes:
        return rich
    section = rich[quotes[0].start():quotes[-1].end()]
    if _BLOCKQUOTE_RE.sub("", section).strip():
        return rich

    tables = []
    for quote in quotes:
        lines = [line.strip() for line in quote.group("body").split("<br>")]
        if len(lines) < 2 or any(not line for line in lines):
            return rich
        tables.append(_summary_table(
            lines,
            bordered=bordered,
            center_values=center_values,
            expandable=expandable,
        ))
    return (
        rich[:quotes[0].start()] + "".join(tables)
        + rich[quotes[-1].end():]
    )


def _format_active_streams_table(rich: str) -> str:
    quotes = list(_BLOCKQUOTE_RE.finditer(rich))
    if len(quotes) != 1:
        return rich
    quote = quotes[0]
    lines = [line.strip() for line in quote.group("body").split("<br>")]
    columns = [value.strip() for value in lines[0].split(" · ")]
    if len(lines) < 2 or len(columns) != 3 or columns[0] != "#":
        return rich
    rows = []
    for line in lines[1:]:
        values = re.sub(r"^[\u251c\u2514\u2502]\s*", "", line).split(
            " | ", 2
        )
        if len(values) != 3:
            return rich
        rank, chat, track = (value.strip() for value in values)
        rows.append(
            f'<tr><td align="center">{rank}</td>'
            f'<td align="center">{chat}</td><td>{track}</td></tr>'
        )
    headers = (
        "<tr>" + "".join(f"<th>{column}</th>" for column in columns) + "</tr>"
    )
    table = "<table bordered striped>" + headers + "".join(rows) + "</table>"
    return rich[:quote.start()] + table + rich[quote.end():]



def _format_trending_table(rich: str) -> str:
    intro_end = rich.find("</blockquote>")
    if intro_end < 0:
        return rich
    intro_end += len("</blockquote>")
    lines = [line.strip() for line in rich[intro_end:].splitlines() if line.strip()]
    rows = [
        "<tr><th>Rank</th><th>Track</th><th>Plays</th></tr>"
    ]
    pattern = re.compile(
        r"(?P<rank><tg-emoji\b[^>]*>.*?</tg-emoji\s*>|\S+)\s+"
        r"(?P<title>.*?)\s{2,}<code>(?P<plays>.*?)</code>",
        re.I | re.S,
    )
    for line in lines:
        match = pattern.fullmatch(line)
        if match is None:
            return rich
        plays = match.group("plays").strip()
        count = re.match(r"\d[\d.,]*(?:[KMB])?", plays, re.I)
        if count:
            plays = count.group(0)
        rows.append(
            f"<tr><td><b>{match.group('rank')}</b></td>"
            f"<td>{match.group('title')}</td>"
            f"<td><code>{plays}</code></td></tr>"
        )
    if len(rows) == 1:
        return rich
    return rich[:intro_end] + "<table striped>" + "".join(rows) + "</table>"


def _format_sessions_table(rich: str) -> str:
    heading_end = rich.find("</h1>")
    if heading_end < 0:
        return rich
    heading_end += len("</h1>")
    match = re.fullmatch(
        r"\s*·\s*(?P<active>\d+)\s+active\s*/\s*"
        r"(?P<total>\d+)\s+total\s*(?P<prompt>.*?)\s*",
        rich[heading_end:],
        re.I | re.S,
    )
    if match is None:
        return rich
    active = int(match.group("active"))
    total = int(match.group("total"))
    rows = (
        f"<tr><td><b>Active</b></td><td><code>{active}</code></td></tr>"
        f"<tr><td><b>Disabled</b></td>"
        f"<td><code>{max(total - active, 0)}</code></td></tr>"
        f"<tr><td><b>Total</b></td><td><code>{total}</code></td></tr>"
    )
    prompt = match.group("prompt")
    suffix = f"\n{prompt}" if prompt else ""
    return rich[:heading_end] + f"<table striped>{rows}</table>" + suffix


def _format_session_detail_table(rich: str) -> str:
    heading = re.match(r"(?P<heading><h2>.*?</h2>)", rich, re.I | re.S)
    if heading is None:
        return rich
    match = re.match(
        r"\s*(?:<b>Account:</b> (?P<account>.*?)\n)?"
        r"Session (?P<slot>\d+) · (?P<state>[^\n]+)\n"
        r"<code>(?P<user_id>.*?)</code> · "
        r"(?P<calls>\d+) active calls\s*",
        rich[heading.end():],
        re.I | re.S,
    )
    if match is None:
        return rich
    state = match.group("state")
    startup = state.lower().endswith(" · startup")
    if startup:
        state = state.rsplit(" · ", 1)[0]
    rows = [
        f"<tr><td><b>Session</b></td>"
        f"<td><code>{match.group('slot')}</code></td></tr>"
    ]
    if match.group("account"):
        rows.append(
            f"<tr><td><b>Account</b></td>"
            f"<td>{match.group('account')}</td></tr>"
        )
    rows.extend([
        f"<tr><td><b>State</b></td><td>{state}</td></tr>",
        f"<tr><td><b>Source</b></td>"
        f"<td>{'Startup' if startup else 'Database'}</td></tr>",
        f"<tr><td><b>User ID</b></td>"
        f"<td><code>{match.group('user_id')}</code></td></tr>",
        f"<tr><td><b>Active calls</b></td>"
        f"<td><code>{match.group('calls')}</code></td></tr>",
    ])
    table = "<table striped>" + "".join(rows) + "</table>"
    suffix = rich[heading.end() + match.end():]
    return heading.group("heading") + table + suffix


def _plain_title(value: str) -> str:
    value = _TG_EMOJI_RE.sub(r"\1", value)
    value = unescape(_TAG_RE.sub("", value))
    value = unicodedata.normalize("NFKC", value).translate(_SMALL_CAPS)
    value = "".join(
        char for char in value
        if unicodedata.category(char) not in {"So", "Sk"}
        and char not in {"\ufe0f", "\u200d"}
    )
    return " ".join(value.split()).strip()


def _explicit_rich_breaks(rich: str) -> str:
    """Keep legacy line breaks visible in Telegram rich HTML."""
    parts = _HTML_TOKEN_RE.split(rich)
    rendered = []
    in_pre = False
    for part in parts:
        lowered = part.lower()
        if lowered.startswith("<pre"):
            in_pre = True
        if not in_pre and not part.startswith(("<", "&")):
            part = (
                part.replace("\r\n", "\n")
                .replace("\r", "\n")
                .replace("\n", "<br>")
            )
        rendered.append(part)
        if lowered.startswith("</pre"):
            in_pre = False

    result = "".join(rendered)
    result = _BREAKS_AFTER_BLOCK_RE.sub(r"\1", result)
    return _BREAKS_BEFORE_BLOCK_RE.sub("", result)



def _clean_title(value: str, text: str) -> tuple[str, int] | None:
    title = _plain_title(value)
    lowered = title.casefold()
    if not any("a" <= char.lower() <= "z" for char in title):
        return None
    if lowered in _EXCLUDED:
        return None
    if lowered.startswith("queued · #"):
        return f"Added to queue · #{title.split('#', 1)[1]}", 3
    category = re.fullmatch(r"commands in the\s+(.+?)\s+category:", title, re.I)
    if re.fullmatch(r"assistant session\s+\d+", lowered):
        return title, 2
    if lowered.startswith("playback access"):
        return "Playback access", 1
    if lowered.startswith("added ") and lowered.endswith(
        "tracks from the playlist to queue:"
    ):
        return title.rstrip(":"), 3
    if lowered.startswith("remove session ") or lowered == "assistant session added":
        return title, 3
    if category:
        return _plain_title(category.group(1)).title(), 1
    if lowered.startswith("welcome,"):
        return "Welcome" + title[len("Welcome"):], 1
    if lowered.endswith(" play log"):
        return title[:-8] + " play log", 3
    if lowered.endswith(" stats"):
        return title[:-6] + " stats", 1
    renamed = _TITLE_RENAMES.get(lowered)
    if renamed:
        return renamed, 1 if renamed in _PRIMARY else 3
    if re.search(r"\nSession \d+ ·", text):
        return title, 2
    if "Choose how music works in this group." in text:
        return title, 1
    if re.search(r"\n\n<blockquote>\d+ assistants", text):
        return title, 1
    if any(token in lowered for token in (
        "assistant is banned", "session action failed", "assistant saved as session",
        "updated immediately", "restored.", "added to queue",
    )):
        return title.rstrip("."), 3
    return None


def promote_heading(text: str) -> str | None:
    """Convert a recognized English legacy title into native rich HTML."""
    if not isinstance(text, str) or not text:
        return None
    match = _LEADING_HEADING_RE.match(text) or _PLAIN_HEADING_RE.match(text)
    if match is None:
        match = _UNDERLINE_HEADING_RE.match(text)
    if match is None:
        return None
    heading = _clean_title(match.group("title"), text)
    if heading is None:
        return None
    title, level = heading
    rich = f"<h{level}>{title}</h{level}>" + text[match.end():]
    rich = rich.replace("<blockquote expandable>", "<blockquote>")
    rich = _BLOCKQUOTE_RE.sub(
        lambda match: "<blockquote>"
        + match.group("body").replace("\n", "<br>")
        + "</blockquote>",
        rich,
    )
    rich = _UNQUOTED_HREF_RE.sub(r'\1"\2"', rich)
    if title == "Queue" or title.startswith("Added to queue"):
        rich = _SECONDARY_TRACK_RE.sub(r"\n\n<h2>\1</h2>", rich, count=1)
    rich = _HEADING_TAG_RE.sub(_style_heading, rich)
    icon = heading_icon(title)
    if icon:
        rich = rich.replace(f"<h{level}>", f"<h{level}>{icon} ", 1)
    if title.startswith("Welcome"):
        rich = re.sub(
            r"^<h1>(?P<body>.*?)</h1>",
            r'<table><tr><th align="center">\g<body></th></tr></table>',
            rich,
            count=1,
        )
    if title == "Bot insights":
        rich = _format_summary_table(rich, bordered=True, center_values=True)
    elif title == "Sudo access":
        rich = _format_summary_table(rich, bordered=True, center_values=True)
    elif title == "Advanced status":
        rich = _format_summary_table(rich, expandable=True)
    elif title == "Trending tracks":
        rich = _format_trending_table(rich)
    elif title == "Active streams":
        rich = _format_active_streams_table(rich)
    elif title == "Assistant sessions":
        rich = _format_sessions_table(rich)
    rich = _format_session_detail_table(rich)

    rich = _add_section_separators(rich, title)
    if title == "Runtime configuration":
        rich = _format_runtime_config_table(rich)
    rich = _center_leading_heading(rich)
    rich = _TABLE_HEADER_RE.sub(_style_table_header, rich)
    rich = _explicit_rich_breaks(rich)
    return rich


def bot_api_dict(value):
    """Serialize Pyrogram objects without their diagnostic `_` type keys."""
    if value is None:
        return None
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [bot_api_dict(item) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key == "_" or item is None:
                continue
            converted = bot_api_dict(item)
            if key == "style" and isinstance(converted, str):
                converted = converted.removeprefix("ButtonStyle.").lower()
                if converted == "default":
                    continue
            if converted is not None:
                result[key] = converted
        return result
    return bot_api_dict(json.loads(str(value)))


@dataclass(slots=True)
class RichMedia:
    media: object
    kind: str = "photo"
    placement: str = "before"


class RichMessageService:
    def __init__(self, client, token: str, logger, *, enabled: bool = True):
        self.client = client
        self.token = token
        self.logger = logger
        self.enabled = bool(enabled and token)
        self.capable = True
        self.session: aiohttp.ClientSession | None = None

    async def close(self) -> None:
        if self.session is not None:
            await self.session.close()
            self.session = None

    async def _session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self.session

    @staticmethod
    def _source(media: object) -> object:
        return getattr(media, "media", media)

    def _rich_message(self, content, media: RichMedia | None, stack: ExitStack):
        if isinstance(content, str):
            result: dict = {"html": content}
        elif isinstance(content, list):
            result = {"blocks": list(content)}
        elif isinstance(content, dict) and any(
            key in content for key in ("html", "markdown", "blocks")
        ):
            result = dict(content)
        else:
            raise ValueError("Rich content must contain html, markdown, or blocks")
        files: dict[str, tuple[object, str]] = {}
        if media is None:
            return result, files
        source = self._source(media.media)
        attachment = source
        local_path = None
        if isinstance(source, Path):
            source = str(source)
        if isinstance(source, str) and not source.startswith(("http://", "https://")):
            try:
                candidate = Path(source)
                if candidate.is_file():
                    local_path = candidate
            except OSError:
                local_path = None
        if local_path is not None:
            handle = stack.enter_context(open(local_path, "rb"))
            attachment = "attach://rich_media_0"
            files["rich_media_0"] = (handle, local_path.name)
        elif isinstance(source, IOBase) or hasattr(source, "read"):
            attachment = "attach://rich_media_0"
            files["rich_media_0"] = (
                source,
                Path(getattr(source, "name", "media.bin")).name,
            )
        media_type = "video" if media.kind == "animation" else media.kind
        input_media = {"type": media.kind, "media": attachment}
        if "blocks" in result:
            field = media.kind
            index = 1 if media.placement == "after_first_block" else 0
            result["blocks"].insert(index, {
                "type": media.kind,
                field: input_media,
            })
        else:
            if media_type == "photo":
                media_tag = '<img src="tg://photo?id=hero"/>'
            elif media_type == "audio":
                media_tag = '<audio src="tg://audio?id=hero"></audio>'
            else:
                media_tag = '<video src="tg://video?id=hero"></video>'
            if "html" in result:
                if media.placement == "after_first_block":
                    block_end = result["html"].find("</table>")
                    if block_end >= 0:
                        block_end += len("</table>")
                        if result["html"][block_end:].startswith("<hr/>"):
                            block_end += len("<hr/>")

                        result["html"] = (
                            result["html"][:block_end] + "\n" + media_tag
                            + result["html"][block_end:]
                        )
                    else:
                        result["html"] = f'{media_tag}\n{result["html"]}'
                else:
                    result["html"] = f'{media_tag}\n{result["html"]}'
            else:
                result["markdown"] = (
                    f'![](tg://{media_type}?id=hero)\n{result["markdown"]}'
                )
            result["media"] = [{"id": "hero", "media": input_media}]
        return result, files

    async def _request(self, method: str, payload: dict, files: dict):
        session = await self._session()
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        if files:
            form = aiohttp.FormData()
            for key, value in payload.items():
                form.add_field(
                    key,
                    json.dumps(value, ensure_ascii=False)
                    if isinstance(value, (dict, list)) else str(value),
                )
            for key, (handle, filename) in files.items():
                form.add_field(
                    key,
                    handle,
                    filename=filename,
                    content_type=mimetypes.guess_type(filename)[0]
                    or "application/octet-stream",
                )
            response_context = session.post(url, data=form)
        else:
            response_context = session.post(url, json=payload)
        async with response_context as response:
            status = response.status
            data = await response.json(content_type=None)
        if not data.get("ok"):
            description = str(data.get("description", "Unknown Bot API error"))
            description_lower = description.lower()
            unavailable = (
                status == 404
                or data.get("error_code") == 404
                or any(phrase in description_lower for phrase in (
                    "method not found", "unknown method", "method is not available"
                ))
            )
            if unavailable:
                self.capable = False
                self.logger.warning("Bot API rich messages are unavailable: %s", description)
            else:
                self.logger.warning("Rich message %s failed: %s", method, description)
            return None
        return data.get("result")

    async def _bound_message(self, chat_id, result):
        message_id = result.get("message_id") if isinstance(result, dict) else None
        if not message_id:
            raise RuntimeError("Telegram accepted a rich message without a message ID")
        last_error = None
        for _ in range(3):
            try:
                return await self.client.get_messages(chat_id, message_id)
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(0.2)
        raise RuntimeError("Could not bind the sent rich message") from last_error

    async def send(
        self, chat_id, content, *, media: RichMedia | None = None,
        fallback_text: str | None = None,
        reply_markup=None, reply_parameters=None, message_thread_id=None,
        disable_notification=None, protect_content=None,
    ):
        if not self.enabled or not self.capable:
            return None
        try:
            with ExitStack() as stack:
                rich_message, files = self._rich_message(content, media, stack)
                payload = {"chat_id": chat_id, "rich_message": rich_message}
                for key, value in (
                    ("reply_markup", bot_api_dict(reply_markup)),
                    ("reply_parameters", bot_api_dict(reply_parameters)),
                    ("message_thread_id", message_thread_id),
                    ("disable_notification", disable_notification),
                    ("protect_content", protect_content),
                ):
                    if value is not None:
                        payload[key] = value
                result = await self._request("sendRichMessage", payload, files)
            return None if result is None else await self._bound_message(chat_id, result)
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, TypeError,
                ValueError, RuntimeError) as exc:
            self.logger.warning("Rich message send failed; using HTML fallback: %s", exc)
            return None

    async def edit(
        self, chat_id, message_id: int, content, *,
        media: RichMedia | None = None, reply_markup=None,
        fallback_text: str | None = None,
    ):
        if not self.enabled or not self.capable:
            return None
        try:
            with ExitStack() as stack:
                rich_message, files = self._rich_message(content, media, stack)
                payload = {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "rich_message": rich_message,
                }
                if reply_markup is not None:
                    payload["reply_markup"] = bot_api_dict(reply_markup)
                result = await self._request("editMessageText", payload, files)
            return None if result is None else await self._bound_message(chat_id, result)
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, TypeError,
                ValueError, RuntimeError) as exc:
            self.logger.warning("Rich message edit failed; using HTML fallback: %s", exc)
            return None

    async def replace_placeholder(self, placeholder, content, **kwargs):
        sent = await self.send(
            placeholder.chat.id,
            content,
            reply_parameters={
                "message_id": placeholder.reply_to_message_id
            } if placeholder.reply_to_message_id else None,
            message_thread_id=getattr(placeholder, "message_thread_id", None),
            **kwargs,
        )
        if sent is not None:
            try:
                await placeholder.delete()
            except Exception:
                self.logger.debug("Could not delete replaced placeholder", exc_info=True)
        return sent
