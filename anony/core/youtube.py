# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import os
import re
import yt_dlp
import random
import asyncio
import aiohttp
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path
from time import monotonic

from py_yt import Playlist, VideosSearch

from anony import logger
from anony.helpers import Track, utils


class YouTube:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.cookies = []
        self.checked = False
        self.cookie_dir = "anony/cookies"
        self.warned = False
        self._cookie_scan_at = 0.0
        self._search_cache = OrderedDict()
        self._search_timeout = 12
        self._search_ttl = 600
        self._search_cache_limit = 256
        self._download_tasks = {}
        self._download_lock = asyncio.Lock()
        self._download_slots = asyncio.Semaphore(4)
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
        now = monotonic()
        if not self.checked or now - self._cookie_scan_at >= 60:
            try:
                self.cookies = sorted(
                    f"{self.cookie_dir}/{file}"
                    for file in os.listdir(self.cookie_dir)
                    if file.endswith(".txt")
                )
            except OSError:
                self.cookies = []
            self.checked = True
            self._cookie_scan_at = now
        if not self.cookies:
            if not self.warned:
                self.warned = True
                logger.warning("Cookies are missing; downloads might fail.")
            return None
        return random.choice(self.cookies)

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
        logger.info(f"Cookies saved in {self.cookie_dir}.")

    def valid(self, url: str) -> bool:
        return bool(re.match(self.regex, url))

    def invalid(self, url: str) -> bool:
        return bool(re.match(self.iregex, url))

    async def search(
        self, query: str, m_id: int, video: bool = False
    ) -> Track | None:
        normalized = " ".join(str(query).split())
        if not normalized:
            return None
        key = (normalized.casefold(), bool(video))
        now = monotonic()
        cached = self._search_cache.get(key)
        if cached and cached[0] > now:
            self._search_cache.move_to_end(key)
            return replace(cached[1], message_id=m_id, video=video)
        if cached:
            self._search_cache.pop(key, None)

        started = monotonic()
        try:
            search = VideosSearch(normalized, limit=1, with_live=False)
            results = await asyncio.wait_for(
                search.next(), timeout=self._search_timeout
            )
        except asyncio.TimeoutError:
            logger.warning(
                "YouTube search timed out after %ss", self._search_timeout
            )
            return None
        except Exception as exc:
            logger.warning("YouTube search failed: %s", type(exc).__name__)
            return None
        elapsed = monotonic() - started
        if elapsed >= 3:
            logger.info("YouTube search completed in %.2fs", elapsed)
        if not results or not results.get("result"):
            return None

        data = results["result"][0]
        thumbnails = data.get("thumbnails") or [{}]
        thumbnail = thumbnails[-1].get("url") or ""
        track = Track(
            id=data.get("id"),
            channel_name=data.get("channel", {}).get("name"),
            duration=data.get("duration") or "Live",
            duration_sec=utils.to_seconds(data.get("duration")),
            title=data.get("title") or "Untitled track",
            thumbnail=thumbnail.split("?")[0],
            url=data.get("link"),
            view_count=data.get("viewCount", {}).get("short"),
            video=video,
        )
        self._search_cache[key] = (now + self._search_ttl, track)
        self._search_cache.move_to_end(key)
        while len(self._search_cache) > self._search_cache_limit:
            self._search_cache.popitem(last=False)
        return replace(track, message_id=m_id)

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
                    title=data.get("title") or "Untitled track",
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

    async def download_song(self, video_id: str) -> dict | None:
        """Download Telegram-ready MP3 audio while retaining source metadata."""
        url = self.base + video_id
        filename = Path("downloads") / f"song_{video_id}.mp3"
        cookie = self.get_cookies()
        options = {
            "format": "bestaudio/best",
            "outtmpl": "downloads/song_%(id)s.%(ext)s",
            "quiet": True,
            "noplaylist": True,
            "geo_bypass": True,
            "no_warnings": True,
            "overwrites": False,
            "nocheckcertificate": True,
            "cookiefile": cookie,
            "socket_timeout": 15,
            "retries": 2,
            "fragment_retries": 2,
            "extractor_retries": 1,
            "file_access_retries": 1,
            "concurrent_fragment_downloads": 4,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                },
                {
                    "key": "FFmpegMetadata",
                    "add_metadata": True,
                },
            ],
        }

        def _download():
            try:
                with yt_dlp.YoutubeDL(options) as ydl:
                    info = ydl.extract_info(url, download=not filename.exists())
                if not filename.exists():
                    return None
                return {
                    "file_path": str(filename),
                    "title": str(
                        info.get("track") or info.get("title") or "Song"
                    ),
                    "performer": str(
                        info.get("artist")
                        or info.get("uploader")
                        or info.get("channel")
                        or ""
                    ),
                    "duration": int(info.get("duration") or 0),
                    "url": info.get("webpage_url") or url,
                }
            except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError):
                return None
            except Exception as ex:
                logger.warning("Song download failed: %s", ex)
                return None

        return await asyncio.to_thread(_download)

    async def _download_once(
        self, video_id: str, video: bool, filename: str
    ) -> str | None:
        url = self.base + video_id
        cookie = self.get_cookies()
        base_opts = {
            "outtmpl": "downloads/%(id)s.%(ext)s",
            "quiet": True,
            "noplaylist": True,
            "geo_bypass": True,
            "no_warnings": True,
            "overwrites": False,
            "nocheckcertificate": True,
            "cookiefile": cookie,
            "socket_timeout": 15,
            "retries": 2,
            "fragment_retries": 2,
            "extractor_retries": 1,
            "file_access_retries": 1,
            "concurrent_fragment_downloads": 4,
        }
        if video:
            options = {
                **base_opts,
                "format": (
                    "(bestvideo[height<=?720][width<=?1280][ext=mp4])"
                    "+(bestaudio)"
                ),
                "merge_output_format": "mp4",
            }
        else:
            options = {
                **base_opts,
                "format": "bestaudio[ext=webm][acodec=opus]",
            }

        def run():
            with yt_dlp.YoutubeDL(options) as ydl:
                try:
                    ydl.download([url])
                except (
                    yt_dlp.utils.DownloadError,
                    yt_dlp.utils.ExtractorError,
                ):
                    return None
                except Exception as exc:
                    logger.warning("Download failed: %s", exc)
                    return None
            return filename if Path(filename).is_file() else None

        started = monotonic()
        async with self._download_slots:
            result = await asyncio.to_thread(run)
        elapsed = monotonic() - started
        if elapsed >= 5:
            logger.info(
                "YouTube %s download %s in %.2fs",
                "video" if video else "audio",
                "completed" if result else "failed",
                elapsed,
            )
        return result

    async def download(
        self, video_id: str, video: bool = False
    ) -> str | None:
        ext = "mp4" if video else "webm"
        filename = f"downloads/{video_id}.{ext}"
        if Path(filename).is_file():
            return filename

        key = (video_id, bool(video))
        async with self._download_lock:
            task = self._download_tasks.get(key)
            if task is None:
                task = asyncio.create_task(
                    self._download_once(video_id, video, filename)
                )
                self._download_tasks[key] = task
        try:
            return await asyncio.shield(task)
        finally:
            if task.done():
                async with self._download_lock:
                    if self._download_tasks.get(key) is task:
                        self._download_tasks.pop(key, None)
