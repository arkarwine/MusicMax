# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import pyrogram

from anony import config, logger


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
        self.owner_url = f"tg://user?id={self.owner}"
        self.logger: int | None = None
        self.bl_users = pyrogram.filters.user()
        self.sudoers = pyrogram.filters.user(self.owner)

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
