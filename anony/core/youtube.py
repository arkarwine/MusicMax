# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import re
import yt_dlp
import random
import asyncio
import aiohttp
from pathlib import Path

from py_yt import Playlist, VideosSearch

from anony import config, logger
from anony.helpers import Track, utils


class YouTube:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.cookies = []
        self.checked = False
        bundled_dir = Path(__file__).resolve().parents[1] / "cookies"
        configured_dir = Path(config.COOKIE_DIR).expanduser() if config.COOKIE_DIR else bundled_dir
        self.cookie_dir = str(configured_dir.resolve())
        self.warned = False
        self.regex = re.compile(
            r"(https?://)?(www\.|m\.|music\.)?"
            r"(youtube\.com/(watch\?v=|shorts/|playlist\?list=)|youtu\.be/)"
            r"([A-Za-z0-9_-]{11}|PL[A-Za-z0-9_-]+)([&?][^\s]*)?"
        )
        self.iregex = re.compile(
            r"https?://(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)"
            r"(?!/(watch\?v=[A-Za-z0-9_-]{11}|shorts/[A-Za-z0-9_-]{11}"
            r"|playlist\?list=PL[A-Za-z0-9_-]+|[A-Za-z0-9_-]{11}))\S*"
        )

    def get_cookies(self):
        if not self.checked:
            cookie_dir = Path(self.cookie_dir)
            cookie_dir.mkdir(parents=True, exist_ok=True)
            self.cookies = [
                str(file.resolve())
                for file in cookie_dir.glob("*.txt")
                if file.is_file()
            ]
            self.checked = True
        if not self.cookies:
            if not self.warned:
                self.warned = True
                logger.warning("Cookies are missing; downloads might fail.")
            return None
        return random.choice(self.cookies)

    def get_cookie_candidates(self) -> list[str | None]:
        self.get_cookies()
        if not self.cookies:
            return [None]
        candidates = self.cookies.copy()
        random.shuffle(candidates)
        return candidates

    async def save_cookies(self, urls: list[str]) -> None:
        logger.info("Saving cookies from urls...")
        async with aiohttp.ClientSession() as session:
            for url in urls:
                name = url.split("/")[-1]
                link = "https://batbin.me/raw/" + name
                async with session.get(link) as resp:
                    resp.raise_for_status()
                    with open(f"{self.cookie_dir}/{name}.txt", "wb") as fw:
                        fw.write(await resp.read())
        self.cookies.clear()
        self.checked = False
        self.warned = False
        logger.info(f"Cookies saved in {self.cookie_dir}.")

    def valid(self, url: str) -> bool:
        return bool(re.match(self.regex, url))

    def invalid(self, url: str) -> bool:
        return bool(re.match(self.iregex, url))

    async def search(self, query: str, m_id: int, video: bool = False) -> Track | None:
        try:
            _search = VideosSearch(query, limit=1, with_live=False)
            results = await _search.next()
        except Exception:
            return None
        if results and results["result"]:
            data = results["result"][0]
            thumbnails = data.get("thumbnails") or [{}]
            thumbnail = thumbnails[-1].get("url") or ""
            return Track(
                id=data.get("id"),
                channel_name=data.get("channel", {}).get("name"),
                duration=data.get("duration") or "Live",
                duration_sec=utils.to_seconds(data.get("duration")),
                message_id=m_id,
                title=(data.get("title") or "Untitled track")[:25],
                thumbnail=thumbnail.split("?")[0],
                url=data.get("link"),
                view_count=data.get("viewCount", {}).get("short"),
                video=video,
            )
        return None

    async def playlist(self, limit: int, user: str, url: str, video: bool) -> list[Track | None]:
        tracks = []
        try:
            plist = await Playlist.get(url)
            for data in (plist.get("videos") or [])[:limit]:
                thumbnails = data.get("thumbnails") or [{}]
                thumbnail = thumbnails[-1].get("url") or ""
                link = data.get("link") or self.base + str(data.get("id") or "")
                track = Track(
                    id=data.get("id"),
                    channel_name=data.get("channel", {}).get("name", ""),
                    duration=data.get("duration") or "Live",
                    duration_sec=utils.to_seconds(data.get("duration")),
                    title=(data.get("title") or "Untitled track")[:25],
                    thumbnail=thumbnail.split("?")[0],
                    url=link.split("&list=")[0],
                    user=user,
                    view_count="",
                    video=video,
                )
                tracks.append(track)
        except Exception:
            pass
        return tracks

    async def download(self, video_id: str, video: bool = False) -> str | None:
        url = self.base + video_id
        download_dir = Path("downloads")
        download_dir.mkdir(parents=True, exist_ok=True)

        def existing_file() -> str | None:
            extensions = (".mp4", ".mkv") if video else (
                ".webm", ".m4a", ".opus", ".ogg", ".mp3", ".aac",
                ".mp4", ".mkv"
            )
            for extension in extensions:
                candidate = download_dir / f"{video_id}{extension}"
                if candidate.is_file() and candidate.stat().st_size:
                    return str(candidate)
            return None

        if cached := existing_file():
            return cached

        base_opts = {
            "outtmpl": "downloads/%(id)s.%(ext)s",
            "quiet": True,
            "noplaylist": True,
            "geo_bypass": True,
            "no_warnings": True,
            "overwrites": False,
            "nocheckcertificate": True,
        }

        def _download():
            for cookie in self.get_cookie_candidates():
                ydl_opts = {**base_opts, "cookiefile": cookie}
                if video:
                    ydl_opts["merge_output_format"] = "mp4"
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.extract_info(url, download=True)
                except (
                    yt_dlp.utils.DownloadError,
                    yt_dlp.utils.ExtractorError,
                ) as ex:
                    logger.warning(
                        "yt-dlp native selection rejected %s using cookie %s: %s",
                        video_id,
                        cookie or "none",
                        ex,
                    )
                    continue
                except Exception as ex:
                    logger.warning("Download failed: %s", ex)
                    continue
                if downloaded := existing_file():
                    return downloaded
                logger.warning(
                    "yt-dlp completed %s but no playable output file was found",
                    video_id,
                )
            return None

        return await asyncio.to_thread(_download)
