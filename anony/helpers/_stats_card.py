# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import asyncio
import math
from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


class StatsCard:
    """Render a premium, chart-only summary of the bot's reach."""

    SIZE = (1600, 1000)
    BG_TOP = (8, 12, 25)
    BG_BOTTOM = (18, 25, 46)
    PANEL = (23, 31, 53)
    PANEL_SHADOW = (7, 10, 21)
    GRID = (48, 60, 88)
    OUTLINE = (43, 57, 91)
    TEXT = (246, 248, 255)
    MUTED = (151, 163, 188)
    BLUE = (91, 142, 255)
    BLUE_FILL = (27, 48, 88)
    VIOLET = (164, 105, 255)
    GREEN = (66, 207, 145)
    GREEN_FILL = (24, 67, 66)

    def __init__(self) -> None:
        root = Path(__file__).resolve().parent
        self.bold_path = root / "Raleway-Bold.ttf"
        self.regular_path = root / "Inter-Light.ttf"

    def _font(self, size: int, bold: bool = False):
        return ImageFont.truetype(
            str(self.bold_path if bold else self.regular_path),
            size,
        )

    @staticmethod
    def _compact(value: int) -> str:
        if value >= 1_000_000:
            return f"{value / 1_000_000:.1f}M"
        if value >= 1_000:
            return f"{value / 1_000:.1f}K"
        return str(value)

    @staticmethod
    def _rounded(draw, box, radius=26, fill=None, outline=None, width=1):
        draw.rounded_rectangle(
            box,
            radius=radius,
            fill=fill,
            outline=outline,
            width=width,
        )

    @staticmethod
    def _nice_max(value: int) -> int:
        value = max(int(value), 1)
        magnitude = 10 ** max(math.floor(math.log10(value)) - 1, 0)
        return max(int(math.ceil(value / magnitude) * magnitude), 1)

    @staticmethod
    def _label_indices(length: int) -> set[int]:
        if length <= 7:
            return set(range(length))
        points = {0, length - 1}
        points.update(round(index * (length - 1) / 6) for index in range(1, 6))
        return points

    @staticmethod
    def _date_label(day: dict) -> str:
        try:
            return datetime.fromisoformat(day["day"]).strftime("%d %b")
        except (KeyError, TypeError, ValueError):
            return str(day.get("label", ""))

    def _background(self, draw) -> None:
        for y in range(self.SIZE[1]):
            ratio = y / (self.SIZE[1] - 1)
            color = tuple(
                int(start + (end - start) * ratio)
                for start, end in zip(self.BG_TOP, self.BG_BOTTOM)
            )
            draw.line((0, y, self.SIZE[0], y), fill=color)
        draw.ellipse((1260, -330, 1810, 220), fill=(31, 43, 79))
        draw.ellipse((-260, 820, 260, 1340), fill=(17, 32, 61))

    def _panel(self, draw, box) -> None:
        x1, y1, x2, y2 = box
        self._rounded(
            draw,
            (x1 + 7, y1 + 9, x2 + 7, y2 + 9),
            fill=self.PANEL_SHADOW,
        )
        self._rounded(
            draw,
            box,
            fill=self.PANEL,
            outline=self.OUTLINE,
            width=2,
        )

    def _header(
        self,
        draw,
        box,
        title: str,
        subtitle: str,
        total: str,
        accent,
        total_label: str = "30-day total",
    ) -> None:
        x1, y1, x2, _ = box
        draw.rounded_rectangle(
            (x1 + 28, y1 + 25, x1 + 35, y1 + 77),
            radius=4,
            fill=accent,
        )
        draw.text(
            (x1 + 55, y1 + 20),
            title,
            font=self._font(29, True),
            fill=self.TEXT,
        )
        draw.text(
            (x1 + 55, y1 + 60),
            subtitle,
            font=self._font(17),
            fill=self.MUTED,
        )
        draw.text(
            (x2 - 28, y1 + 24),
            total,
            font=self._font(23, True),
            fill=accent,
            anchor="ra",
        )
        draw.text(
            (x2 - 28, y1 + 58),
            total_label,
            font=self._font(15),
            fill=self.MUTED,
            anchor="ra",
        )

    def _grid(self, draw, plot, maximum: int) -> None:
        x1, y1, x2, y2 = plot
        for step in range(5):
            ratio = step / 4
            y = y2 - (y2 - y1) * ratio
            value = round(maximum * ratio)
            draw.line((x1, y, x2, y), fill=self.GRID, width=1)
            draw.text(
                (x1 - 14, y - 8),
                self._compact(value),
                font=self._font(13),
                fill=self.MUTED,
                anchor="ra",
            )

    def _x_labels(self, draw, plot, days: list[dict]) -> None:
        x1, _, x2, y2 = plot
        slot = (x2 - x1) / max(len(days), 1)
        labels = self._label_indices(len(days))
        for index, day in enumerate(days):
            if index not in labels:
                continue
            center = x1 + slot * index + slot / 2
            draw.text(
                (center, y2 + 13),
                self._date_label(day),
                font=self._font(13),
                fill=self.MUTED,
                anchor="ma",
            )

    def _growth_chart(self, draw, box, days: list[dict]) -> None:
        self._panel(draw, box)
        total_people = sum(int(day.get("users_added", 0)) for day in days)
        total_groups = sum(int(day.get("groups_added", 0)) for day in days)
        self._header(
            draw,
            box,
            "Bot growth",
            "New people and groups · last 30 days",
            f"+{self._compact(total_people + total_groups)} chats",
            self.BLUE,
        )
        x1, y1, x2, y2 = box
        draw.ellipse((x1 + 470, y1 + 31, x1 + 482, y1 + 43), fill=self.BLUE)
        draw.text(
            (x1 + 491, y1 + 25),
            "People",
            font=self._font(15),
            fill=self.MUTED,
        )
        draw.ellipse((x1 + 570, y1 + 31, x1 + 582, y1 + 43), fill=self.VIOLET)
        draw.text(
            (x1 + 591, y1 + 25),
            "Groups",
            font=self._font(15),
            fill=self.MUTED,
        )

        plot = (x1 + 72, y1 + 112, x2 - 30, y2 - 47)
        totals = [
            int(day.get("users_added", 0)) + int(day.get("groups_added", 0))
            for day in days
        ]
        maximum = self._nice_max(max([1] + totals))
        self._grid(draw, plot, maximum)
        px1, py1, px2, py2 = plot
        slot = (px2 - px1) / max(len(days), 1)
        bar_width = max(8, min(25, int(slot * 0.58)))
        height = py2 - py1
        for index, day in enumerate(days):
            people = int(day.get("users_added", 0))
            groups = int(day.get("groups_added", 0))
            center = px1 + slot * index + slot / 2
            people_height = height * people / maximum
            groups_height = height * groups / maximum
            if people:
                draw.rounded_rectangle(
                    (
                        center - bar_width / 2,
                        py2 - people_height,
                        center + bar_width / 2,
                        py2,
                    ),
                    radius=5,
                    fill=self.BLUE,
                )
            if groups:
                top = py2 - people_height - groups_height
                draw.rounded_rectangle(
                    (
                        center - bar_width / 2,
                        top,
                        center + bar_width / 2,
                        py2 - people_height + 3,
                    ),
                    radius=5,
                    fill=self.VIOLET,
                )
        self._x_labels(draw, plot, days)

    def _area_chart(
        self,
        draw,
        box,
        days: list[dict],
        *,
        field: str,
        title: str,
        subtitle: str,
        unit: str,
        accent,
        fill,
    ) -> None:
        self._panel(draw, box)
        values = [int(day.get(field, 0)) for day in days]
        is_active_chats = field == "active_chats"
        summary = values[-1] if is_active_chats and values else sum(values)
        self._header(
            draw,
            box,
            title,
            subtitle,
            f"{self._compact(summary)} {unit}",
            accent,
            "latest day" if is_active_chats else "30-day total",
        )
        x1, y1, x2, y2 = box
        plot = (x1 + 72, y1 + 112, x2 - 30, y2 - 47)
        maximum = self._nice_max(max([1] + values))
        px1, py1, px2, py2 = plot
        slot = (px2 - px1) / max(len(days), 1)
        height = py2 - py1
        points = [
            (
                px1 + slot * index + slot / 2,
                py2 - height * value / maximum,
            )
            for index, value in enumerate(values)
        ]
        if points:
            area = [(points[0][0], py2), *points, (points[-1][0], py2)]
            draw.polygon(area, fill=fill)
        self._grid(draw, plot, maximum)
        if len(points) > 1:
            draw.line(points, fill=accent, width=5, joint="curve")
        markers = self._label_indices(len(days))
        for index, (x, y) in enumerate(points):
            if index in markers:
                draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=accent)
        self._x_labels(draw, plot, days)

    def _render(self, data: dict) -> BytesIO:
        image = Image.new("RGB", self.SIZE, self.BG_TOP)
        draw = ImageDraw.Draw(image)
        self._background(draw)

        draw.text(
            (64, 38),
            data["bot_name"],
            font=self._font(25, True),
            fill=self.BLUE,
        )
        draw.text(
            (64, 73),
            "30-DAY BOT REACH",
            font=self._font(48, True),
            fill=self.TEXT,
        )
        draw.text(
            (1536, 84),
            "Growth · listening · active chats",
            font=self._font(18),
            fill=self.MUTED,
            anchor="ra",
        )

        month = data.get("month") or data["days"]
        self._growth_chart(draw, (60, 145, 1540, 500), month)
        self._area_chart(
            draw,
            (60, 530, 790, 930),
            month,
            field="plays",
            title="Songs played",
            subtitle="Daily listening · last 30 days",
            unit="plays",
            accent=self.GREEN,
            fill=self.GREEN_FILL,
        )
        self._area_chart(
            draw,
            (810, 530, 1540, 930),
            month,
            field="active_chats",
            title="Active chats",
            subtitle="Unique listening chats · last 30 days",
            unit="chats",
            accent=self.BLUE,
            fill=self.BLUE_FILL,
        )
        draw.text(
            (60, 963),
            f"Updated {data['updated']} UTC",
            font=self._font(15),
            fill=self.MUTED,
        )

        output = BytesIO()
        output.name = "bot-reach.png"
        image.save(output, "PNG", optimize=True)
        output.seek(0)
        return output

    async def generate(self, data: dict) -> BytesIO:
        return await asyncio.to_thread(self._render, data)


stats_card = StatsCard()