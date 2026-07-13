# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import asyncio
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


class StatsCard:
    """Render a friendly, public summary of the bot's reach."""

    SIZE = (1600, 1000)
    BG_TOP = (10, 14, 28)
    BG_BOTTOM = (20, 27, 48)
    PANEL = (25, 33, 56)
    PANEL_ALT = (31, 41, 68)
    TEXT = (246, 248, 255)
    MUTED = (155, 166, 190)
    BLUE = (99, 145, 255)
    VIOLET = (166, 112, 255)
    GREEN = (69, 208, 148)
    AMBER = (255, 190, 92)

    def __init__(self) -> None:
        root = Path(__file__).resolve().parent
        self.bold_path = root / "Raleway-Bold.ttf"
        self.regular_path = root / "Inter-Light.ttf"

    def _font(self, size: int, bold: bool = False):
        return ImageFont.truetype(
            str(self.bold_path if bold else self.regular_path), size
        )

    @staticmethod
    def _compact(value: int) -> str:
        if value >= 1_000_000:
            return f"{value / 1_000_000:.1f}M"
        if value >= 1_000:
            return f"{value / 1_000:.1f}K"
        return str(value)

    @staticmethod
    def _percentage_change(days: list[dict], fields: tuple[str, ...]) -> int:
        if len(days) < 2:
            return 0
        previous = sum(int(days[-2].get(field, 0)) for field in fields)
        current = sum(int(days[-1].get(field, 0)) for field in fields)
        if previous == 0:
            change = 100 if current > 0 else 0
        else:
            change = round((current - previous) * 100 / previous)
        return max(-100, min(change, 999))

    @staticmethod
    def _rounded(draw, box, radius=24, fill=None, outline=None, width=1):
        draw.rounded_rectangle(
            box, radius=radius, fill=fill, outline=outline, width=width
        )

    def _person_icon(self, draw, cx: int, cy: int, color, scale=1.0) -> None:
        radius = int(9 * scale)
        draw.ellipse(
            (cx - radius, cy - 23 * scale, cx + radius, cy - 5 * scale),
            fill=color,
        )
        draw.rounded_rectangle(
            (cx - 15 * scale, cy + 1 * scale, cx + 15 * scale, cy + 25 * scale),
            radius=int(11 * scale),
            fill=color,
        )

    def _icon(self, draw, center: tuple[int, int], kind: str, accent) -> None:
        cx, cy = center
        draw.ellipse(
            (cx - 43, cy - 43, cx + 43, cy + 43),
            fill=self.PANEL_ALT,
            outline=accent,
            width=2,
        )
        icon_color = (233, 239, 255)
        if kind == "person":
            self._person_icon(draw, cx, cy, icon_color, 1.25)
        elif kind in {"reach", "groups"}:
            self._person_icon(draw, cx, cy + 3, icon_color, 0.9)
            self._person_icon(draw, cx - 23, cy + 8, icon_color, 0.66)
            self._person_icon(draw, cx + 23, cy + 8, icon_color, 0.66)
        elif kind == "play":
            draw.polygon(
                [(cx - 14, cy - 23), (cx - 14, cy + 23), (cx + 24, cy)],
                fill=icon_color,
            )
        else:
            draw.rounded_rectangle(
                (cx - 25, cy - 20, cx + 25, cy + 18),
                radius=9,
                fill=icon_color,
            )
            draw.polygon(
                [(cx - 14, cy + 16), (cx - 23, cy + 29), (cx - 5, cy + 19)],
                fill=icon_color,
            )
            if kind == "new":
                draw.line((cx - 9, cy - 1, cx + 9, cy - 1), fill=accent, width=5)
                draw.line((cx, cy - 10, cx, cy + 8), fill=accent, width=5)
            else:
                draw.line((cx - 13, cy - 7, cx + 13, cy - 7), fill=accent, width=4)
                draw.line((cx - 13, cy + 3, cx + 5, cy + 3), fill=accent, width=4)

    def _music_mark(self, draw) -> None:
        self._rounded(
            draw,
            (44, 40, 174, 170),
            radius=24,
            fill=(20, 30, 74),
            outline=self.VIOLET,
            width=2,
        )
        draw.line((118, 73, 118, 132), fill=self.TEXT, width=10)
        draw.line((118, 73, 145, 66), fill=self.TEXT, width=10)
        draw.ellipse((91, 119, 124, 148), fill=self.TEXT)
        draw.ellipse((130, 105, 158, 132), fill=self.TEXT)
        draw.line((145, 69, 145, 119), fill=self.TEXT, width=10)

    def _chart_grid(self, draw, box, maximum: int) -> None:
        x1, y1, x2, y2 = box
        for step in range(5):
            ratio = step / 4
            y = y2 - (y2 - y1) * ratio
            value = round(maximum * ratio)
            draw.line((x1, y, x2, y), fill=(48, 60, 88), width=1)
            draw.text(
                (x1 - 12, y - 8),
                str(value),
                font=self._font(13),
                fill=self.MUTED,
                anchor="ra",
            )

    def _metric(
        self, draw, box, label: str, value: str, accent, icon: str
    ) -> None:
        self._rounded(draw, box, fill=self.PANEL, outline=(43, 61, 102))
        x1, y1, _, y2 = box
        self._icon(draw, (x1 + 70, (y1 + y2) // 2), icon, accent)
        draw.text(
            (x1 + 130, y1 + 26),
            label.upper(),
            font=self._font(20, True),
            fill=self.MUTED,
        )
        draw.text(
            (x1 + 130, y1 + 58),
            value,
            font=self._font(48, True),
            fill=self.TEXT,
        )

    def _chart_frame(
        self, draw, box, title: str, subtitle: str, change: int
    ) -> tuple:
        self._rounded(draw, box, fill=self.PANEL, outline=(43, 55, 86))
        x1, y1, x2, y2 = box
        draw.text((x1 + 28, y1 + 22), title, font=self._font(27, True), fill=self.TEXT)
        draw.text((x1 + 28, y1 + 59), subtitle, font=self._font(18), fill=self.MUTED)
        change_color = (
            self.GREEN
            if change > 0
            else self.AMBER if change < 0 else self.MUTED
        )
        change_text = f"{change:+d}% today" if change else "0% today"
        self._rounded(
            draw,
            (x2 - 163, y1 + 57, x2 - 28, y1 + 91),
            radius=17,
            fill=self.PANEL_ALT,
            outline=change_color,
        )
        draw.text(
            (x2 - 95, y1 + 63),
            change_text,
            font=self._font(15, True),
            fill=change_color,
            anchor="ma",
        )
        return x1 + 42, y1 + 105, x2 - 30, y2 - 48

    def _growth_chart(self, draw, box, days: list[dict]) -> None:
        x1, y1, x2, y2 = self._chart_frame(
            draw,
            box,
            "Growing community",
            "New chats · last 7 days",
            self._percentage_change(days, ("users_added", "groups_added")),
        )
        chat_counts = [
            day["users_added"] + day["groups_added"] for day in days
        ]
        max_value = max([1] + chat_counts)
        self._chart_grid(draw, (x1, y1, x2, y2), max_value)
        width = x2 - x1
        slot = width / max(len(days), 1)
        baseline = y2
        height = y2 - y1
        for index, (day, chats) in enumerate(zip(days, chat_counts)):
            center = x1 + slot * index + slot / 2
            bar_height = max(3, height * chats / max_value)
            draw.rounded_rectangle(
                (center - 18, baseline - bar_height, center + 18, baseline),
                radius=8,
                fill=self.BLUE,
            )
            draw.text(
                (center, baseline + 10),
                day["label"],
                font=self._font(15),
                fill=self.MUTED,
                anchor="ma",
            )


    def _activity_chart(self, draw, box, days: list[dict]) -> None:
        x1, y1, x2, y2 = self._chart_frame(
            draw,
            box,
            "Songs enjoyed",
            "Plays · last 7 days",
            self._percentage_change(days, ("plays",)),
        )
        max_value = max([1] + [day["plays"] for day in days])
        self._chart_grid(draw, (x1, y1, x2, y2), max_value)
        width = x2 - x1
        slot = width / max(len(days), 1)
        baseline = y2
        height = y2 - y1
        for index, day in enumerate(days):
            center = x1 + slot * index + slot / 2
            play_h = max(3, height * day["plays"] / max_value)
            draw.rounded_rectangle(
                (center - 18, baseline - play_h, center + 18, baseline),
                radius=8, fill=self.GREEN,
            )
            draw.text(
                (center, baseline + 10), day["label"],
                font=self._font(15), fill=self.MUTED, anchor="ma",
            )


    def _render(self, data: dict) -> BytesIO:
        image = Image.new("RGB", self.SIZE, self.BG_TOP)
        draw = ImageDraw.Draw(image)
        for y in range(self.SIZE[1]):
            ratio = y / (self.SIZE[1] - 1)
            color = tuple(
                int(a + (b - a) * ratio)
                for a, b in zip(self.BG_TOP, self.BG_BOTTOM)
            )
            draw.line((0, y, self.SIZE[0], y), fill=color)

        draw.ellipse((1250, -260, 1750, 240), fill=(35, 48, 88))
        self._music_mark(draw)
        draw.text((200, 40), data["bot_name"], font=self._font(35, True), fill=self.TEXT)
        draw.text((200, 84), "OUR MUSIC REACH", font=self._font(54, True), fill=self.TEXT)
        draw.text(
            (200, 154), "A SIMPLE LOOK AT OUR GROWING COMMUNITY",
            font=self._font(18, True), fill=self.MUTED,
        )
        status_color = self.GREEN if data["status"] == "Ready" else self.AMBER
        self._rounded(draw, (1280, 72, 1530, 130), radius=29, fill=(30, 45, 59))
        draw.ellipse((1303, 91, 1321, 109), fill=status_color)
        draw.text(
            (1338, 85),
            data["status"],
            font=self._font(21 if len(data["status"]) < 15 else 16, True),
            fill=self.TEXT,
        )

        today = data["days"][-1] if data["days"] else {}
        new_chats_today = int(today.get("users_added", 0)) + int(
            today.get("groups_added", 0)
        )
        metrics = [
            ("Total reach", self._compact(data["chats"]), self.BLUE, "reach"),
            ("People", self._compact(data["users"]), self.VIOLET, "person"),
            ("Groups", self._compact(data["groups"]), self.BLUE, "groups"),
            ("Plays today", self._compact(data["streams_24h"]), self.VIOLET, "play"),
            (
                "Active chats today",
                self._compact(data["active_chats_24h"]),
                self.BLUE,
                "chat",
            ),
            ("New chats today", self._compact(new_chats_today), self.VIOLET, "new"),
        ]
        card_w, card_h = 466, 126
        for index, metric in enumerate(metrics):
            row, column = divmod(index, 3)
            x = 70 + column * (card_w + 31)
            y = 205 + row * (card_h + 22)
            self._metric(draw, (x, y, x + card_w, y + card_h), *metric)

        self._growth_chart(draw, (70, 520, 820, 935), data["days"])
        self._activity_chart(draw, (850, 520, 1530, 935), data["days"])
        draw.text(
            (70, 961), f"Updated {data['updated']} UTC",
            font=self._font(16), fill=self.MUTED,
        )
        draw.text(
            (1530, 961),
            f"{data['assistants']} assistants · Up {data['uptime']}",
            font=self._font(16, True),
            fill=self.MUTED,
            anchor="ra",
        )

        output = BytesIO()
        output.name = "bot-reach.png"
        image.save(output, "PNG", optimize=True)
        output.seek(0)
        return output

    async def generate(self, data: dict) -> BytesIO:
        return await asyncio.to_thread(self._render, data)


stats_card = StatsCard()