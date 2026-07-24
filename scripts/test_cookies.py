#!/usr/bin/env python3
"""Test YouTube cookies with the same local yt-dlp dependency as the bot.

Examples:
  python scripts/test_cookies.py
  python scripts/test_cookies.py 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
  python scripts/test_cookies.py --all --video-id dQw4w9WgXcQ
  python scripts/test_cookies.py --cookie anony/cookies/youtube.txt --format audio
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yt_dlp

# PM2 exposes Node IPC variables. They are irrelevant to Python but can confuse
# yt-dlp's JS runtimes in the same way the bot already guards against.
os.environ.pop("NODE_CHANNEL_FD", None)
os.environ.pop("NODE_UNIQUE_ID", None)

DEFAULT_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
COOKIE_DIR = Path("anony/cookies")


def cookie_files() -> list[Path]:
    if not COOKIE_DIR.exists():
        return []
    return sorted(
        path for path in COOKIE_DIR.glob("*.txt")
        if path.is_file() and path.stat().st_size > 0
    )


def target_url(args: argparse.Namespace) -> str:
    if args.video_id:
        return f"https://www.youtube.com/watch?v={args.video_id}"
    return args.url or DEFAULT_URL


def format_spec(kind: str) -> str:
    if kind == "audio":
        return "bestaudio[ext=webm][acodec=opus]/bestaudio/best"
    if kind == "video":
        return "(bestvideo[height<=?720][width<=?1280][ext=mp4]+bestaudio)/best"
    return "bestvideo*+bestaudio/best"


def run_cookie_test(
    cookie: Path | None,
    url: str,
    kind: str,
    list_formats: bool,
) -> bool:
    label = str(cookie.resolve()) if cookie else "no cookie"
    print(f"\n=== Testing {label} ===")
    opts = {
        "quiet": False,
        "verbose": True,
        "simulate": True,
        "noplaylist": True,
        "geo_bypass": True,
        "nocheckcertificate": True,
        "socket_timeout": 15,
        "retries": 2,
        "fragment_retries": 2,
        "extractor_retries": 1,
        "file_access_retries": 1,
        "format": format_spec(kind),
    }
    if list_formats:
        opts["listformats"] = True
    if cookie:
        opts["cookiefile"] = str(cookie)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        title = (info or {}).get("title") or "unknown title"
        video_id = (info or {}).get("id") or "unknown id"
        print(f"OK: {video_id} · {title}")
        return True
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Test bot YouTube cookies with yt-dlp")
    parser.add_argument("url", nargs="?", help="YouTube URL to test")
    parser.add_argument("--video-id", help="YouTube video id to test")
    parser.add_argument("--cookie", type=Path, help="Specific cookie file")
    parser.add_argument("--all", action="store_true", help="Test every anony/cookies/*.txt file")
    parser.add_argument(
        "--format",
        choices=("audio", "video", "best"),
        default="audio",
        help="Format family to test; default matches /play audio best",
    )
    parser.add_argument("-F", "--list-formats", action="store_true")
    args = parser.parse_args()

    url = target_url(args)
    files = cookie_files()
    print(f"Working directory: {Path.cwd()}")
    print(f"Cookie directory: {COOKIE_DIR.resolve()}")
    print(f"Cookie files: {len(files)}")
    for file in files:
        print(f"- {file} ({file.stat().st_size} bytes)")
    print(f"URL: {url}")
    print(f"Format: {args.format}")

    if args.cookie:
        selected = [args.cookie]
    elif args.all:
        selected = files
    else:
        selected = files[:1]

    if not selected:
        print("No cookie file found. Testing without cookies.")
        selected = [None]

    ok = 0
    for cookie in selected:
        if cookie is not None and not cookie.exists():
            print(f"\nMissing cookie file: {cookie}")
            continue
        ok += int(run_cookie_test(cookie, url, args.format, args.list_formats))

    print(f"\nResult: {ok}/{len(selected)} passed")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
