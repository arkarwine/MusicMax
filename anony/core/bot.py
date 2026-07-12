# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import asyncio

import pyrogram

from anony import config, logger
from anony.core.custom_emoji import (
    custom_emoji_capability_detected,
    custom_emoji_supported,
    is_localized_text,
    keyboard_has_custom_icons,
    keyboard_without_custom_icons,
    render_custom_emoji_text,
    set_custom_emoji_button_icons_supported,
    set_custom_emoji_supported,
    strip_custom_emoji_tags,
)


_CUSTOM_EMOJI_TEST_ID = "5465443221003836735"
_CUSTOM_EMOJI_TEST = (
    f'<tg-emoji emoji-id="{_CUSTOM_EMOJI_TEST_ID}">▶️</tg-emoji>'
)


class Bot(pyrogram.Client):
    def __init__(self):
        super().__init__(
            name="anony",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            bot_token=config.BOT_TOKEN,
            in_memory=True,
            parse_mode=pyrogram.enums.ParseMode.HTML,
            max_concurrent_transmissions=7,
            link_preview_options=pyrogram.types.LinkPreviewOptions(is_disabled=True),
        )
        self.owner = config.OWNER_ID
        self.owner_username: str | None = None
        self.owner_is_premium = False
        self.owner_url = f"tg://user?id={self.owner}"
        self.logger: int | None = None
        self.bl_users = pyrogram.filters.user()
        self.sudoers = pyrogram.filters.user(self.owner)

    @staticmethod
    def _render_call(args, kwargs, text_index: int, text_key: str):
        args = list(args)
        kwargs = dict(kwargs)
        if len(args) > text_index and is_localized_text(args[text_index]):
            args[text_index] = render_custom_emoji_text(args[text_index])
        elif is_localized_text(kwargs.get(text_key)):
            kwargs[text_key] = render_custom_emoji_text(kwargs[text_key])
        return args, kwargs

    async def _custom_emoji_call(
        self, method, args, kwargs, text_index: int, text_key: str
    ):
        original_args = list(args)
        original_kwargs = dict(kwargs)
        args, kwargs = self._render_call(args, kwargs, text_index, text_key)
        markup = kwargs.get("reply_markup")
        try:
            result = await method(*args, **kwargs)
            if keyboard_has_custom_icons(markup):
                set_custom_emoji_button_icons_supported(True)
            return result
        except pyrogram.errors.BadRequest as first_error:
            original_text = (
                original_args[text_index]
                if len(original_args) > text_index
                else original_kwargs.get(text_key)
            )
            has_tagged_text = (
                isinstance(original_text, str)
                and "tg-emoji" in original_text.lower()
            )
            has_icons = keyboard_has_custom_icons(markup)
            if not has_tagged_text and not has_icons:
                raise

            if has_icons:
                first_rejection = set_custom_emoji_button_icons_supported(False)
                kwargs["reply_markup"] = keyboard_without_custom_icons(markup)
                if first_rejection:
                    logger.warning(
                        "Telegram rejected custom emoji button icons (%s); "
                        "button fallbacks enabled for this process.",
                        first_error,
                    )
                try:
                    # Keep valid custom emoji entities in the message while
                    # testing whether only the keyboard icon was rejected.
                    return await method(*args, **kwargs)
                except pyrogram.errors.BadRequest:
                    if not has_tagged_text:
                        raise

            logger.warning(
                "Telegram rejected tagged custom emoji text (%s); retrying "
                "this message with its Unicode fallback.",
                first_error,
            )
            if len(args) > text_index and isinstance(args[text_index], str):
                args[text_index] = strip_custom_emoji_tags(args[text_index])
            elif isinstance(kwargs.get(text_key), str):
                kwargs[text_key] = strip_custom_emoji_tags(kwargs[text_key])
            return await method(*args, **kwargs)

    async def send_message(self, *args, **kwargs):
        return await self._custom_emoji_call(
            super().send_message, args, kwargs, 1, "text"
        )

    async def edit_message_text(self, *args, **kwargs):
        return await self._custom_emoji_call(
            super().edit_message_text, args, kwargs, 2, "text"
        )

    async def edit_message_caption(self, *args, **kwargs):
        return await self._custom_emoji_call(
            super().edit_message_caption, args, kwargs, 2, "caption"
        )

    async def answer_callback_query(self, *args, **kwargs):
        args = list(args)
        kwargs = dict(kwargs)
        # Callback toasts do not support HTML entities, so they always use the
        # localized Unicode fallback even when message rendering is supported.
        if len(args) > 1 and is_localized_text(args[1]):
            args[1] = strip_custom_emoji_tags(args[1])
        elif is_localized_text(kwargs.get("text")):
            kwargs["text"] = strip_custom_emoji_tags(kwargs["text"])
        return await super().answer_callback_query(*args, **kwargs)

    async def _send_media_with_caption(self, method, args, kwargs):
        return await self._custom_emoji_call(
            method, args, kwargs, 2, "caption"
        )

    async def send_photo(self, *args, **kwargs):
        return await self._send_media_with_caption(
            super().send_photo, args, kwargs
        )

    async def send_video(self, *args, **kwargs):
        return await self._send_media_with_caption(
            super().send_video, args, kwargs
        )

    async def send_animation(self, *args, **kwargs):
        return await self._send_media_with_caption(
            super().send_animation, args, kwargs
        )

    async def send_audio(self, *args, **kwargs):
        return await self._send_media_with_caption(
            super().send_audio, args, kwargs
        )

    async def send_document(self, *args, **kwargs):
        return await self._send_media_with_caption(
            super().send_document, args, kwargs
        )

    async def answer_inline_query(self, *args, **kwargs):
        args = list(args)
        kwargs = dict(kwargs)
        results = args[1] if len(args) > 1 else kwargs.get("results", [])
        for result in results or []:
            content = getattr(result, "input_message_content", None)
            if content and is_localized_text(
                getattr(content, "message_text", None)
            ):
                content.message_text = render_custom_emoji_text(
                    content.message_text
                )
            if is_localized_text(getattr(result, "caption", None)):
                result.caption = render_custom_emoji_text(result.caption)
        try:
            return await super().answer_inline_query(*args, **kwargs)
        except pyrogram.errors.RPCError:
            has_custom_content = False
            for result in results or []:
                content = getattr(result, "input_message_content", None)
                if content and isinstance(
                    getattr(content, "message_text", None), str
                ):
                    current = content.message_text
                    has_custom_content |= "tg-emoji" in current.lower()
                    content.message_text = strip_custom_emoji_tags(current)
                if isinstance(getattr(result, "caption", None), str):
                    current = result.caption
                    has_custom_content |= "tg-emoji" in current.lower()
                    result.caption = strip_custom_emoji_tags(current)
                markup = getattr(result, "reply_markup", None)
                if keyboard_has_custom_icons(markup):
                    has_custom_content = True
                    result.reply_markup = keyboard_without_custom_icons(markup)
            if not has_custom_content:
                raise
            logger.warning(
                "Telegram rejected inline custom emoji content; retrying with fallbacks."
            )
            return await super().answer_inline_query(*args, **kwargs)

    async def detect_custom_emoji_support(self) -> bool:
        if custom_emoji_capability_detected():
            return custom_emoji_supported()
        if not self.owner_is_premium:
            set_custom_emoji_supported(False)
            logger.info(
                "Telegram custom emoji rendering: unsupported; "
                "the owner is not Premium, using fallbacks."
            )
            return False
        sent = None
        supported = False
        try:
            sent = await asyncio.wait_for(
                super().send_message(self.owner, _CUSTOM_EMOJI_TEST),
                timeout=10,
            )
            entities = getattr(sent, "entities", None) or []
            supported = any(
                getattr(entity, "type", None)
                == pyrogram.enums.MessageEntityType.CUSTOM_EMOJI
                and str(getattr(entity, "custom_emoji_id", ""))
                == _CUSTOM_EMOJI_TEST_ID
                for entity in entities
            )
        except Exception:
            logger.debug(
                "Custom emoji capability probe failed.", exc_info=True
            )
        finally:
            set_custom_emoji_supported(supported)
            if sent is not None:
                try:
                    await asyncio.wait_for(sent.delete(), timeout=5)
                except Exception:
                    logger.debug(
                        "Could not delete custom emoji capability probe.",
                        exc_info=True,
                    )
        logger.info(
            "Telegram custom emoji rendering: %s.",
            "supported" if supported else "unsupported; using fallbacks",
        )
        return supported

    async def boot(self):
        """
        Starts the bot and performs initial setup.
        """
        await super().start()
        self.id = self.me.id
        self.name = self.me.first_name
        self.username = self.me.username
        self.mention = self.me.mention
        try:
            owner = await self.get_users(self.owner)
            self.owner_username = owner.username
            self.owner_is_premium = bool(getattr(owner, "is_premium", False))
            if owner.username:
                self.owner_url = f"https://t.me/{owner.username}"
            logger.info(
                "Resolved owner %s as %s",
                self.owner,
                f"@{owner.username}" if owner.username else owner.first_name,
            )
        except Exception:
            logger.warning(
                "Could not resolve owner username; using the numeric Telegram link."
            )

        await self.detect_custom_emoji_support()

        self.commands = [
            ("play", "Play a song or link"),
            ("vplay", "Play a video"),
            ("pause", "Pause playback"),
            ("resume", "Resume playback or a saved queue"),
            ("skip", "Skip the current track"),
            ("stop", "Stop playback and clear the queue"),
            ("queue", "Show the current queue"),
            ("loop", "Repeat the current track"),
            ("seek", "Move forward in the current track"),
            ("setup", "Check what this group still needs"),
            ("settings", "Open group playback settings"),
            ("language", "Change the group language"),
            ("ping", "Check whether the bot is responsive"),
            ("stats", "Show bot reach and activity"),
            ("trending", "Show the most-played tracks"),
            ("help", "Show commands and help"),
        ]
        try:
            await self.set_bot_commands(
                [
                    pyrogram.types.BotCommand(command, description)
                    for command, description in self.commands
                ]
            )
            logger.info("Registered %s Telegram bot commands.", len(self.commands))
        except Exception:
            logger.warning("Could not register Telegram bot commands.", exc_info=True)

        logger.info(f"Bot started as @{self.username}")

    async def register_sudo_commands(self, user_ids) -> None:
        sudo_commands = [
            ("sessions", "🤖 Open assistant manager"),
            ("session", "🔎 Open an assistant"),
            ("addsession", "➕ Add an assistant securely"),
            ("enablesession", "▶️ Enable an assistant"),
            ("disablesession", "⏸ Disable an assistant"),
            ("restartsession", "🔄 Reconnect an assistant"),
            ("removesession", "🗑 Remove an assistant"),
            ("status", "📊 Show advanced status"),
            ("logs", "📄 Get the application log"),
            ("config", "⚙️ Open runtime configuration"),
            ("setconfig", "✏️ Change a safe runtime setting"),
            ("resetconfig", "↩️ Restore a runtime setting"),
        ]
        commands = [
            pyrogram.types.BotCommand(command, description)
            for command, description in self.commands + sudo_commands
        ]
        registered = 0
        for user_id in user_ids:
            try:
                await self.set_bot_commands(
                    commands,
                    scope=pyrogram.types.BotCommandScopeChat(chat_id=user_id),
                )
                registered += 1
            except Exception:
                logger.debug(
                    "Could not register sudo commands for user %s",
                    user_id,
                    exc_info=True,
                )
        logger.info("Registered sudo command menus for %s user(s).", registered)

    async def exit(self):
        """
        Asynchronously stops the bot.
        """
        await super().stop()
        logger.info("Bot stopped.")
