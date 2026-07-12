# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import asyncio
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


class StatsCard:
    """Render the compact public reach and seven-day analytics dashboard."""

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
    def _rounded(draw, box, radius=24, fill=None, outline=None, width=1):
        draw.rounded_rectangle(
            box, radius=radius, fill=fill, outline=outline, width=width
        )

    def _metric(self, draw, box, label: str, value: str, accent) -> None:
        self._rounded(draw, box, fill=self.PANEL, outline=(43, 55, 86))
        x1, y1, x2, _ = box
        draw.rounded_rectangle(
            (x1 + 24, y1 + 25, x1 + 32, y1 + 99),
            radius=4,
            fill=accent,
        )
        draw.text(
            (x1 + 55, y1 + 26), label.upper(),
            font=self._font(21, True), fill=self.MUTED,
        )
        value_font = self._font(42 if len(value) < 13 else 32, True)
        draw.text((x1 + 55, y1 + 62), value, font=value_font, fill=self.TEXT)

    def _chart_frame(self, draw, box, title: str, subtitle: str) -> tuple:
        self._rounded(draw, box, fill=self.PANEL, outline=(43, 55, 86))
        x1, y1, x2, y2 = box
        draw.text((x1 + 28, y1 + 22), title, font=self._font(27, True), fill=self.TEXT)
        draw.text((x1 + 28, y1 + 59), subtitle, font=self._font(18), fill=self.MUTED)
        return x1 + 42, y1 + 105, x2 - 30, y2 - 48

    def _growth_chart(self, draw, box, days: list[dict]) -> None:
        x1, y1, x2, y2 = self._chart_frame(
            draw, box, "Audience growth", "New users and groups · last 7 days"
        )
        max_value = max(
            [1] + [max(day["users_added"], day["groups_added"]) for day in days]
        )
        width = x2 - x1
        slot = width / max(len(days), 1)
        baseline = y2
        height = y2 - y1
        for index, day in enumerate(days):
            center = x1 + slot * index + slot / 2
            user_h = max(3, height * day["users_added"] / max_value)
            group_h = max(3, height * day["groups_added"] / max_value)
            draw.rounded_rectangle(
                (center - 22, baseline - user_h, center - 4, baseline),
                radius=7, fill=self.BLUE,
            )
            draw.rounded_rectangle(
                (center + 4, baseline - group_h, center + 22, baseline),
                radius=7, fill=self.VIOLET,
            )
            draw.text(
                (center, baseline + 10), day["label"],
                font=self._font(15), fill=self.MUTED, anchor="ma",
            )
        draw.ellipse((x2 - 210, box[1] + 29, x2 - 196, box[1] + 43), fill=self.BLUE)
        draw.text((x2 - 187, box[1] + 25), "Users", font=self._font(16), fill=self.MUTED)
        draw.ellipse((x2 - 112, box[1] + 29, x2 - 98, box[1] + 43), fill=self.VIOLET)
        draw.text((x2 - 89, box[1] + 25), "Groups", font=self._font(16), fill=self.MUTED)

    def _activity_chart(self, draw, box, days: list[dict]) -> None:
        x1, y1, x2, y2 = self._chart_frame(
            draw, box, "Playback activity", "Daily plays and peak streams"
        )
        max_value = max(
            [1] + [max(day["plays"], day["peak_streams"]) for day in days]
        )
        width = x2 - x1
        slot = width / max(len(days), 1)
        baseline = y2
        height = y2 - y1
        points = []
        for index, day in enumerate(days):
            center = x1 + slot * index + slot / 2
            play_h = max(3, height * day["plays"] / max_value)
            draw.rounded_rectangle(
                (center - 18, baseline - play_h, center + 18, baseline),
                radius=8, fill=self.GREEN,
            )
            peak_y = baseline - height * day["peak_streams"] / max_value
            points.append((center, peak_y))
            draw.text(
                (center, baseline + 10), day["label"],
                font=self._font(15), fill=self.MUTED, anchor="ma",
            )
        if len(points) > 1:
            draw.line(points, fill=self.AMBER, width=5, joint="curve")
        for x, y in points:
            draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=self.AMBER)
        draw.rectangle((x2 - 205, box[1] + 30, x2 - 191, box[1] + 44), fill=self.GREEN)
        draw.text((x2 - 181, box[1] + 25), "Plays", font=self._font(16), fill=self.MUTED)
        draw.ellipse((x2 - 108, box[1] + 29, x2 - 94, box[1] + 43), fill=self.AMBER)
        draw.text((x2 - 84, box[1] + 25), "Peak", font=self._font(16), fill=self.MUTED)

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
        draw.text((70, 52), data["bot_name"], font=self._font(25, True), fill=self.BLUE)
        draw.text((70, 91), "ANALYTICS", font=self._font(54, True), fill=self.TEXT)
        draw.text(
            (70, 154), "LIVE REACH  /  7-DAY PERFORMANCE",
            font=self._font(18, True), fill=self.MUTED,
        )
        status_color = self.GREEN if data["status"] == "Operational" else self.AMBER
        self._rounded(draw, (1280, 72, 1530, 130), radius=29, fill=(30, 45, 59))
        draw.ellipse((1303, 91, 1321, 109), fill=status_color)
        draw.text((1338, 85), data["status"], font=self._font(21, True), fill=self.TEXT)

        metrics = [
            ("Total users", self._compact(data["users"]), self.BLUE),
            ("Total groups", self._compact(data["groups"]), self.VIOLET),
            ("Active streams", str(data["active_streams"]), self.GREEN),
            ("Available assistants", str(data["assistants"]), self.AMBER),
            ("Uptime", data["uptime"], self.BLUE),
            ("Service status", data["status"], status_color),
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
            (1530, 961), "Melody analytics",
            font=self._font(16, True), fill=self.MUTED, anchor="ra",
        )

        output = BytesIO()
        output.name = "analytics.png"
        image.save(output, "PNG", optimize=True)
        output.seek(0)
        return output

    async def generate(self, data: dict) -> BytesIO:
        return await asyncio.to_thread(self._render, data)


stats_card = StatsCard()