# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import re

from pyrogram import enums, types

from anony import app, db, logger


class Utilities:
    def __init__(self):
        pass

    def format_eta(self, seconds: int) -> str:
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            return f"{seconds // 60}:{seconds % 60:02d} min"
        else:
            h = seconds // 3600
            m = (seconds % 3600) // 60
            s = seconds % 60
            return f"{h}:{m:02d}:{s:02d} h"

    def format_size(self, bytes: int) -> str:
        if bytes >= 1024**3:
            return f"{bytes / 1024 ** 3:.2f} GB"
        elif bytes >= 1024**2:
            return f"{bytes / 1024 ** 2:.2f} MB"
        else:
            return f"{bytes / 1024:.2f} KB"

    def to_seconds(self, value: str | None) -> int:
        if not value:
            return 0
        try:
            parts = [int(part) for part in value.strip().split(":")]
        except (AttributeError, ValueError):
            return 0
        return sum(part * 60**i for i, part in enumerate(reversed(parts)))


    def get_url(self, message_1: types.Message) -> str | None:
        link = None
        messages = [message_1]

        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)

        for message in messages:
            entities = message.entities or message.caption_entities or []

            for entity in entities:
                if entity.type == enums.MessageEntityType.TEXT_LINK:
                    link = entity.url
                    break
                elif entity.type == enums.MessageEntityType.URL:
                    text = message.text or message.caption
                    if not text:
                        continue
                    link = text[entity.offset: entity.offset + entity.length]
                    break

        if link:
            return link.split("&si")[0].split("?si")[0]
        return None


    async def extract_user(self, msg: types.Message) -> types.User | None:
        if msg.reply_to_message:
            return msg.reply_to_message.from_user

        if msg.entities:
            for e in msg.entities:
                if e.type == enums.MessageEntityType.TEXT_MENTION:
                    return e.user

        if msg.text:
            try:
                if m := re.search(r"@(\w{5,32})", msg.text):
                    return await app.get_users(m.group(0))
                if m := re.search(r"\b\d{6,15}\b", msg.text):
                    return await app.get_users(int(m.group(0)))
            except Exception:
                pass

        return None


    async def play_log(
        self,
        m: types.Message,
        link: str,
        title: str,
        duration: str,
    ) -> None:
        if not app.logger or not await db.is_logger() or m.chat.id == app.logger:
            return
        _text = m.lang["play_log"].format(
            app.name,
            m.chat.id,
            m.chat.title,
            m.from_user.id,
            m.from_user.mention,
            link,
            title,
            duration,
        )
        try:
            await app.send_message(chat_id=app.logger, text=_text)
        except Exception:
            logger.exception("Failed to send play log to chat %s", app.logger)

    async def send_log(self, m: types.Message, chat: bool = False) -> None:
        if not app.logger or not await db.is_logger() or m.chat.id == app.logger:
            return
        if chat:
            user = m.from_user
            text = m.lang["log_chat"].format(
                m.chat.id,
                m.chat.title,
                user.id if user else 0,
                user.mention if user else "Anonymous",
            )
        else:
            username = f"@{m.from_user.username}" if m.from_user.username else "No username"
            text = m.lang["log_user"].format(
                m.from_user.id,
                username,
                m.from_user.mention,
            )
        try:
            await app.send_message(chat_id=app.logger, text=text)
        except Exception:
            logger.exception("Failed to send activity log to chat %s", app.logger)
