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
_IMAGE_MARKER = "\ue000play-image\ue001"


@dataclass(frozen=True, slots=True)
class RenderedPlayMessage:
    rich_html: str
    rich_blocks: list[dict]
    fallback_html: str
    used_default: bool = False
    media_index: int | None = None


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
            target = link.group(2)
            for token, fragment in fragments.items():
                if token in target:
                    target = target.replace(
                        token, _visible_text(fragment)
                    )
            href = _safe_url(target)
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


def _plain_rich_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_plain_rich_text(item) for item in value)
    if isinstance(value, dict):
        return _plain_rich_text(value.get("text", ""))
    return str(value or "")


def _compact_rich_text(items: list[object]) -> object:
    compacted: list[object] = []
    for item in items:
        if item == "":
            continue
        if isinstance(item, str) and compacted and isinstance(compacted[-1], str):
            compacted[-1] += item
        else:
            compacted.append(item)
    if not compacted:
        return ""
    if len(compacted) == 1:
        return compacted[0]
    return compacted


def _inline_rich(text: str, fragments: dict[str, object]) -> object:
    rendered: list[object] = []
    index = 0
    delimiters = (
        ("**", "bold"), ("__", "italic"),
        ("~~", "strikethrough"), (_CODE, "code"),
    )
    while index < len(text):
        if text[index] == "\x00":
            end = text.find("\x00", index + 1)
            token = text[index:end + 1] if end >= 0 else ""
            if token in fragments:
                rendered.append(fragments[token])
                index = end + 1
                continue

        if text[index] == "\\" and index + 1 < len(text):
            rendered.append(text[index + 1])
            index += 2
            continue

        link = _LINK_RE.match(text, index)
        if link:
            target = link.group(2)
            for token, fragment in fragments.items():
                if token in target:
                    target = target.replace(
                        token, _plain_rich_text(fragment)
                    )
            href = _safe_url(target)
            if href:
                rendered.append({
                    "type": "url",
                    "text": _inline_rich(link.group(1), fragments),
                    "url": href,
                })
                index = link.end()
                continue

        matched = False
        for delimiter, kind in delimiters:
            if not text.startswith(delimiter, index):
                continue
            end = _find_closing(text, delimiter, index + len(delimiter))
            if end < 0:
                continue
            inner = text[index + len(delimiter):end]
            rendered.append({
                "type": kind,
                "text": inner if kind == "code" else _inline_rich(
                    inner, fragments
                ),
            })
            index = end + len(delimiter)
            matched = True
            break
        if matched:
            continue

        rendered.append(text[index])
        index += 1
    return _compact_rich_text(rendered)


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
        if rich:
            blocks.extend(
                f"<p>{line}</p>" for line in paragraph
            )
        else:
            blocks.append("<br>".join(paragraph))

    if rich:
        return "".join(blocks)
    return "<br><br>".join(blocks)


def _markdown_blocks(
    markdown: str,
    fragments: dict[str, object],
) -> list[dict]:
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[dict] = []
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
            block = {
                "type": "pre",
                "text": "\n".join(code_lines),
            }
            if language:
                block["language"] = language
            blocks.append(block)
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            blocks.append({
                "type": "heading",
                "text": _inline_rich(heading.group(2), fragments),
                "size": len(heading.group(1)),
            })
            index += 1
            continue

        if _HORIZONTAL_RE.match(line):
            blocks.append({"type": "divider"})
            index += 1
            continue

        unordered = _UNORDERED_RE.match(line)
        if unordered:
            items = []
            while index < len(lines):
                item = _UNORDERED_RE.match(lines[index])
                if not item:
                    break
                items.append({
                    "blocks": [{
                        "type": "paragraph",
                        "text": _inline_rich(item.group(1), fragments),
                    }],
                })
                index += 1
            blocks.append({"type": "list", "items": items})
            continue

        ordered = _ORDERED_RE.match(line)
        if ordered:
            items = []
            while index < len(lines):
                item = _ORDERED_RE.match(lines[index])
                if not item:
                    break
                items.append({
                    "blocks": [{
                        "type": "paragraph",
                        "text": _inline_rich(item.group(2), fragments),
                    }],
                    "value": int(item.group(1)),
                    "type": "1",
                })
                index += 1
            blocks.append({"type": "list", "items": items})
            continue

        quote = _BLOCKQUOTE_RE.match(line)
        if quote:
            quote_blocks = []
            while index < len(lines):
                item = _BLOCKQUOTE_RE.match(lines[index])
                if not item:
                    break
                quote_blocks.append({
                    "type": "paragraph",
                    "text": _inline_rich(item.group(1), fragments),
                })
                index += 1
            blocks.append({
                "type": "blockquote",
                "blocks": quote_blocks,
            })
            continue

        paragraph = []
        while index < len(lines) and (
            not paragraph or not _is_block_start(lines[index])
        ):
            paragraph.append(lines[index])
            index += 1
        blocks.extend(
            {
                "type": "paragraph",
                "text": _inline_rich(item, fragments),
            }
            for item in paragraph
        )
    return blocks


def _requester_rich_fragment(value: object) -> object:
    raw = str(value or "")
    match = _REQUESTER_RE.fullmatch(raw)
    if match:
        href = _safe_url(next(item for item in match.groups()[:3] if item))
        label = _visible_text(match.group(4))
        if href:
            return {
                "type": "url",
                "text": label,
                "url": href,
            }
    return _visible_text(raw)


def _template_with_fragments(
    template: str,
    *,
    title: object,
    url: object,
    duration: object,
    requester: object,
) -> tuple[str, dict[str, str], dict[str, object]]:
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

    html_values = {
        "image": _IMAGE_MARKER,
        "title": title_fragment,
        "title_link": title_link,
        "duration": escape(str(duration or "--:--")),
        "requester": _requester_fragment(requester),
        "source_url": escape(source_url or ""),
    }
    rich_title_link: object = display_title
    if source_url:
        rich_title_link = {
            "type": "url",
            "text": display_title,
            "url": source_url,
        }
    rich_values: dict[str, object] = {
        "image": _IMAGE_MARKER,
        "title": display_title,
        "title_link": rich_title_link,
        "duration": str(duration or "--:--"),
        "requester": _requester_rich_fragment(requester),
        "source_url": source_url or "",
    }
    html_fragments: dict[str, str] = {}
    rich_fragments: dict[str, object] = {}
    parts = []
    serial = 0
    for literal, field, _, _ in Formatter().parse(str(template)):
        parts.append(literal)
        if field is not None:
            token = f"\x00{serial}\x00"
            serial += 1
            html_fragments[token] = html_values[field]
            rich_fragments[token] = rich_values[field]
            parts.append(token)
    return "".join(parts), html_fragments, rich_fragments
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
    markdown, html_fragments, rich_fragments = _template_with_fragments(
        template,
        title=title,
        url=url,
        duration=duration,
        requester=requester,
    )
    clean_markdown = markdown
    for token, fragment in html_fragments.items():
        if fragment == _IMAGE_MARKER:
            clean_markdown = clean_markdown.replace(token, "")
    rich_html = _markdown_html(clean_markdown, html_fragments, rich=True)
    rich_blocks = _markdown_blocks(markdown, rich_fragments)
    media_index = next((
        index for index, block in enumerate(rich_blocks)
        if block.get("type") == "paragraph"
        and block.get("text") == _IMAGE_MARKER
    ), None)
    if media_index is not None:
        rich_blocks.pop(media_index)
    fallback_html = _markdown_html(
        clean_markdown, html_fragments, rich=False
    )
    if not fallback_html.strip():
        raise ValueError("Play template rendered an empty caption")
    if _caption_length(fallback_html) > _CAPTION_LIMIT:
        raise ValueError("Play template exceeds Telegram's caption limit")
    return RenderedPlayMessage(
        rich_html, rich_blocks, fallback_html,
        media_index=media_index,
    )


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
            rendered.rich_blocks,
            rendered.fallback_html,
            used_default=True,
            media_index=rendered.media_index,
        )
