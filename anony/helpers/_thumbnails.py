# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import asyncio
import hashlib
import os
import aiohttp
from PIL import (Image, ImageDraw, ImageEnhance,
                 ImageFilter, ImageFont, ImageOps)

from anony import config
from anony.helpers import Track


class Thumbnail:
    def __init__(self):
        self.rect = (914, 514)
        self.fill = (255, 255, 255)
        self.font1 = ImageFont.truetype("anony/helpers/Raleway-Bold.ttf", 30)
        self.font2 = ImageFont.truetype("anony/helpers/Inter-Light.ttf", 30)
        self.session: aiohttp.ClientSession | None = None
        self._play_image_lock = asyncio.Lock()
        self._artwork_locks: dict[str, asyncio.Lock] = {}
        self._artwork_slots = asyncio.Semaphore(2)

    async def start(self) -> None:
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10, connect=4)
        )

    async def close(self) -> None:
        if self.session is not None:
            await self.session.close()
            self.session = None

    async def save_thumb(self, output_path: str, url: str) -> str:
        if self.session is None or not url:
            raise RuntimeError("Thumbnail downloader is unavailable")
        async with self.session.get(url) as resp:
            resp.raise_for_status()
            with open(output_path, "wb") as file:
                file.write(await resp.read())
        return output_path

    async def play_image(self, url: str) -> str | None:
        """Cache a configured PLAY_IMAGE as a reusable Telegram photo.

        Rich-message URL media is fetched by Telegram. Reusing the same URL in
        later slideshow edits is not reliable, so normalize it once and upload
        the local JPEG as a fresh attachment for every play card.
        """
        if not url:
            return None

        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
        output = f"cache/play_image_{digest}.jpg"
        source = f"cache/play_image_{digest}.source"
        os.makedirs("cache", exist_ok=True)

        if os.path.exists(output) and os.path.getsize(output) > 0:
            return output

        async with self._play_image_lock:
            if os.path.exists(output) and os.path.getsize(output) > 0:
                return output
            try:
                if url.startswith(("http://", "https://")):
                    await self.save_thumb(source, url)
                else:
                    from anony import app

                    downloaded = await app.download_media(url, file_name=source)
                    if not downloaded:
                        raise RuntimeError("Telegram media could not be downloaded")
                await asyncio.to_thread(
                    self._normalize_play_image,
                    source,
                    output,
                )
                return output
            except Exception:
                try:
                    os.remove(output)
                except OSError:
                    pass
                return None
            finally:
                try:
                    os.remove(source)
                except OSError:
                    pass

    @staticmethod
    def _normalize_play_image(source: str, output: str) -> None:
        with Image.open(source) as image:
            normalized = image.convert("RGB")
            normalized.thumbnail(
                (1920, 1920), Image.Resampling.LANCZOS
            )
            normalized.save(
                output, "JPEG", quality=88, optimize=True
            )

    async def audio_cover(self, song: Track) -> str | None:
        """Create a Telegram-compatible square JPEG cover for an audio file."""
        if not song.thumbnail:
            return None
        output = f"cache/song_{song.id}.jpg"
        temp = f"cache/song_{song.id}.source"
        try:
            if os.path.exists(output) and os.path.getsize(output) <= 200_000:
                return output
            await self.save_thumb(temp, song.thumbnail)
            with Image.open(temp) as source:
                cover = ImageOps.fit(
                    source.convert("RGB"),
                    (320, 320),
                    method=Image.Resampling.LANCZOS,
                )
                for quality in (88, 76, 64, 52):
                    cover.save(output, "JPEG", quality=quality, optimize=True)
                    if os.path.getsize(output) <= 200_000:
                        return output
            return output if os.path.getsize(output) <= 200_000 else None
        except Exception:
            return None
        finally:
            try:
                os.remove(temp)
            except OSError:
                pass

    def _render_artwork(
        self,
        source_path: str,
        output_path: str,
        song: Track,
        size: tuple[int, int],
    ) -> None:
        with Image.open(source_path) as source:
            thumb = source.convert("RGBA").resize(
                size, Image.Resampling.LANCZOS,
            )
        blur = thumb.filter(ImageFilter.GaussianBlur(25))
        image = ImageEnhance.Brightness(blur).enhance(.40)

        rect = ImageOps.fit(
            thumb, self.rect,
            method=Image.Resampling.LANCZOS, centering=(0.5, 0.5),
        )
        mask = Image.new("L", self.rect, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, self.rect[0], self.rect[1]),
            radius=15,
            fill=255,
        )
        rect.putalpha(mask)
        image.paste(rect, (183, 30), rect)

        draw = ImageDraw.Draw(image)
        draw.text(
            xy=(50, 560),
            text=f"{(song.channel_name or '')[:25]} | {song.view_count or ''}",
            font=self.font2, fill=self.fill,
        )
        draw.text(
            (50, 600),
            (song.title or "")[:50],
            font=self.font1,
            fill=self.fill,
        )
        draw.text((40, 650), "0:01", font=self.font1, fill=self.fill)
        draw.line(
            [(140, 670), (1160, 670)],
            fill=self.fill,
            width=5,
            joint="curve",
        )
        draw.text(
            (1185, 650),
            song.duration or "--:--",
            font=self.font1,
            fill=self.fill,
        )
        image.convert("RGB").save(
            output_path,
            "JPEG",
            quality=84,
            optimize=True,
        )

    async def generate(self, song: Track, size=(1280, 720)) -> str:
        song_id = str(song.id or "unknown")
        os.makedirs("cache", exist_ok=True)
        output = f"cache/{song_id}.jpg"
        if os.path.exists(output) and os.path.getsize(output) > 0:
            return output
        if not song.thumbnail:
            return config.DEFAULT_THUMB

        lock = self._artwork_locks.setdefault(song_id, asyncio.Lock())
        try:
            async with lock:
                if os.path.exists(output) and os.path.getsize(output) > 0:
                    return output
                temp = f"cache/temp_{song_id}.jpg"
                try:
                    await self.save_thumb(temp, song.thumbnail)
                    async with self._artwork_slots:
                        await asyncio.to_thread(
                            self._render_artwork,
                            temp,
                            output,
                            song,
                            size,
                        )
                    return output
                finally:
                    try:
                        os.remove(temp)
                    except OSError:
                        pass
        except Exception:
            return config.DEFAULT_THUMB
        finally:
            if self._artwork_locks.get(song_id) is lock and not lock.locked():
                self._artwork_locks.pop(song_id, None)
