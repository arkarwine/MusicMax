"""Safe Markdown templates for configurable playback cards."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape, unescape
from string import Formatter
from urllib.parse import urlparse


_CODE = chr(96)
_FENCE = _CODE * 3
_LINK_RE = re.compile(
    r"\[((?:\\.|[^\]])*)\]\(((?:\\.|[^)])*)\)"
)
_REQUESTER_RE = re.compile(
    r'^\s*<a\s+href=(?:"([^"]+)"|\'([^\']+)\'|([^ >]+))>'
    r"(.*?)</a>\s*$",
    re.I | re.S,
)
_TAG_RE = re.compile(r"<[^>]+>")
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$")
_UNORDERED_RE = re.compile(r"^\s*[-*]\s+(.+)$")
_ORDERED_RE = re.compile(r"^\s*(\d+)[.)]\s+(.+)$")
_BLOCKQUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
_HORIZONTAL_RE = re.compile(r"^\s*(?:---+|___+|\*\*\*+)\s*$")
_ALLOWED_URL_SCHEMES = {"http", "https", "tg"}
_CAPTION_LIMIT = 1024
_TITLE_LIMIT = 27


@dataclass(frozen=True, slots=True)
class RenderedPlayMessage:
    rich_html: str
    fallback_html: str
    used_default: bool = False


def select_play_media(override, artwork) -> tuple[object, ...]:
    selected = []
    for source in (override, artwork):
        if source is not None and source not in selected:
            selected.append(source)
    return tuple(selected)


def _safe_url(value: object) -> str | None:
    candidate = unescape(str(value or "")).strip()
    candidate = candidate.replace(r"\)", ")").replace(r"\\", "\\")
    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in _ALLOWED_URL_SCHEMES:
        return None
    if parsed.scheme.lower() in {"http", "https"} and not parsed.netloc:
        return None
    return candidate


def _visible_text(value: object) -> str:
    return unescape(_TAG_RE.sub("", str(value or "")))


def _requester_fragment(value: object) -> str:
    raw = str(value or "")
    match = _REQUESTER_RE.fullmatch(raw)
    if match:
        href = _safe_url(next(item for item in match.groups()[:3] if item))
        label = _visible_text(match.group(4))
        if href:
            return (
                f'<a href="{escape(href, quote=True)}">'
                f"{escape(label)}</a>"
            )
    return escape(_visible_text(raw))


def _find_closing(text: str, delimiter: str, start: int) -> int:
    index = start
    while True:
        index = text.find(delimiter, index)
        if index < 0:
            return -1
        slashes = 0
        cursor = index - 1
        while cursor >= 0 and text[cursor] == "\\":
            slashes += 1
            cursor -= 1
        if slashes % 2 == 0:
            return index
        index += len(delimiter)


def _inline_html(text: str, fragments: dict[str, str]) -> str:
    rendered = []
    index = 0
    delimiters = (("**", "b"), ("__", "i"), ("~~", "s"), (_CODE, "code"))
    while index < len(text):
        if text[index] == "\x00":
            end = text.find("\x00", index + 1)
            token = text[index:end + 1] if end >= 0 else ""
            if token in fragments:
                rendered.append(fragments[token])
                index = end + 1
                continue

        if text[index] == "\\" and index + 1 < len(text):
            rendered.append(escape(text[index + 1]))
            index += 2
            continue

        link = _LINK_RE.match(text, index)
        if link:
            href = _safe_url(link.group(2))
            if href:
                rendered.append(
                    f'<a href="{escape(href, quote=True)}">'
                    f"{_inline_html(link.group(1), fragments)}</a>"
                )
                index = link.end()
                continue

        matched = False
        for delimiter, tag in delimiters:
            if not text.startswith(delimiter, index):
                continue
            end = _find_closing(
                text, delimiter, index + len(delimiter)
            )
            if end < 0:
                continue
            inner = text[index + len(delimiter):end]
            content = (
                escape(inner)
                if tag == "code"
                else _inline_html(inner, fragments)
            )
            rendered.append(f"<{tag}>{content}</{tag}>")
            index = end + len(delimiter)
            matched = True
            break
        if matched:
            continue

        rendered.append(escape(text[index]))
        index += 1
    return "".join(rendered)


def _is_block_start(line: str) -> bool:
    return bool(
        not line.strip()
        or line.startswith(_FENCE)
        or _HEADING_RE.match(line)
        or _UNORDERED_RE.match(line)
        or _ORDERED_RE.match(line)
        or _BLOCKQUOTE_RE.match(line)
        or _HORIZONTAL_RE.match(line)
    )


def _markdown_html(
    markdown: str,
    fragments: dict[str, str],
    *,
    rich: bool,
) -> str:
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue

        if line.startswith(_FENCE):
            language = line[len(_FENCE):].strip()
            index += 1
            code_lines = []
            while index < len(lines) and not lines[index].startswith(_FENCE):
                code_lines.append(lines[index])
                index += 1
            if index >= len(lines):
                raise ValueError("Unclosed fenced code block")
            index += 1
            attribute = (
                f' language="{escape(language, quote=True)}"'
                if language else ""
            )
            blocks.append(
                f"<pre{attribute}>{escape(chr(10).join(code_lines))}</pre>"
            )
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            body = _inline_html(heading.group(2), fragments)
            if rich:
                level = len(heading.group(1))
                blocks.append(f"<h{level}>{body}</h{level}>")
            else:
                blocks.append(f"<b>{body}</b>")
            index += 1
            continue

        if _HORIZONTAL_RE.match(line):
            blocks.append("<hr/>" if rich else "────────")
            index += 1
            continue

        unordered = _UNORDERED_RE.match(line)
        if unordered:
            items = []
            while index < len(lines):
                item = _UNORDERED_RE.match(lines[index])
                if not item:
                    break
                items.append(
                    f"<li>{_inline_html(item.group(1), fragments)}</li>"
                )
                index += 1
            if rich:
                blocks.append("<ul>" + "".join(items) + "</ul>")
            else:
                blocks.append(
                    "<br>".join(
                        "• " + re.sub(r"^<li>|</li>$", "", item)
                        for item in items
                    )
                )
            continue

        ordered = _ORDERED_RE.match(line)
        if ordered:
            items = []
            numbers = []
            while index < len(lines):
                item = _ORDERED_RE.match(lines[index])
                if not item:
                    break
                numbers.append(item.group(1))
                items.append(
                    f"<li>{_inline_html(item.group(2), fragments)}</li>"
                )
                index += 1
            if rich:
                blocks.append("<ol>" + "".join(items) + "</ol>")
            else:
                blocks.append(
                    "<br>".join(
                        f"{number}. "
                        + re.sub(r"^<li>|</li>$", "", item)
                        for number, item in zip(numbers, items)
                    )
                )
            continue

        quote = _BLOCKQUOTE_RE.match(line)
        if quote:
            quoted = []
            while index < len(lines):
                item = _BLOCKQUOTE_RE.match(lines[index])
                if not item:
                    break
                quoted.append(_inline_html(item.group(1), fragments))
                index += 1
            blocks.append(
                "<blockquote>" + "<br>".join(quoted) + "</blockquote>"
            )
            continue

        paragraph = []
        while index < len(lines) and (
            not paragraph or not _is_block_start(lines[index])
        ):
            paragraph.append(_inline_html(lines[index], fragments))
            index += 1
        blocks.append("<br>".join(paragraph))

    separator = "" if rich else "<br><br>"
    return separator.join(blocks)


def _template_with_fragments(
    template: str,
    *,
    title: object,
    url: object,
    duration: object,
    requester: object,
) -> tuple[str, dict[str, str]]:
    display_title = str(title or "Unknown track")
    if len(display_title) > _TITLE_LIMIT:
        display_title = (
            display_title[:_TITLE_LIMIT - 3].rstrip() + "..."
        )
    source_url = _safe_url(url)
    title_fragment = escape(display_title)
    title_link = title_fragment
    if source_url:
        title_link = (
            f'<a href="{escape(source_url, quote=True)}">'
            f"{title_fragment}</a>"
        )

    values = {
        "title": title_fragment,
        "title_link": title_link,
        "duration": escape(str(duration or "--:--")),
        "requester": _requester_fragment(requester),
        "source_url": escape(source_url or ""),
    }
    fragments: dict[str, str] = {}
    parts = []
    serial = 0
    for literal, field, _, _ in Formatter().parse(str(template)):
        parts.append(literal)
        if field is not None:
            token = f"\x00{serial}\x00"
            serial += 1
            fragments[token] = values[field]
            parts.append(token)
    return "".join(parts), fragments


def _caption_length(html: str) -> int:
    plain = unescape(
        _TAG_RE.sub("", html.replace("<br>", "\n").replace("<hr/>", "\n"))
    )
    return len(plain.encode("utf-16-le")) // 2


def _render_once(
    template: str,
    *,
    title: object,
    url: object,
    duration: object,
    requester: object,
) -> RenderedPlayMessage:
    markdown, fragments = _template_with_fragments(
        template,
        title=title,
        url=url,
        duration=duration,
        requester=requester,
    )
    rich_html = _markdown_html(markdown, fragments, rich=True)
    fallback_html = _markdown_html(markdown, fragments, rich=False)
    if not fallback_html.strip():
        raise ValueError("Play template rendered an empty caption")
    if _caption_length(fallback_html) > _CAPTION_LIMIT:
        raise ValueError("Play template exceeds Telegram's caption limit")
    return RenderedPlayMessage(rich_html, fallback_html)


def render_play_message(
    template: str,
    default_template: str,
    *,
    title: object,
    url: object,
    duration: object,
    requester: object,
) -> RenderedPlayMessage:
    try:
        return _render_once(
            template,
            title=title,
            url=url,
            duration=duration,
            requester=requester,
        )
    except (KeyError, ValueError):
        if template == default_template:
            raise
        rendered = _render_once(
            default_template,
            title=title,
            url=url,
            duration=duration,
            requester=requester,
        )
        return RenderedPlayMessage(
            rendered.rich_html,
            rendered.fallback_html,
            used_default=True,
        )

