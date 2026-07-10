# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


from pyrogram import enums, types

from anony import app, config, lang
from anony.core.lang import lang_codes


class Inline:
    def __init__(self):
        self.ikm = types.InlineKeyboardMarkup
        self.ikb = types.InlineKeyboardButton

    def cancel_dl(self, text) -> types.InlineKeyboardMarkup:
        return self.ikm(
            [[self.ikb(
                text=text,
                callback_data="cancel_dl",
                style=enums.ButtonStyle.DANGER,
            )]]
        )

    def controls(
        self,
        chat_id: int,
        status: str = None,
        timer: str = None,
        remove: bool = False,
        playing: bool = True,
    ) -> types.InlineKeyboardMarkup:
        keyboard = []
        if status:
            keyboard.append(
                [self.ikb(text=status, callback_data=f"controls status {chat_id}")]
            )
        elif timer:
            keyboard.append(
                [self.ikb(text=timer, callback_data=f"controls status {chat_id}")]
            )

        if not remove:
            playback = (
                self.ikb(
                    text="Ⅱ",
                    callback_data=f"controls pause {chat_id}",
                    style=enums.ButtonStyle.PRIMARY,
                )
                if playing
                else self.ikb(
                    text="▷",
                    callback_data=f"controls resume {chat_id}",
                    style=enums.ButtonStyle.SUCCESS,
                )
            )
            keyboard.append(
                [
                    playback,
                    self.ikb(
                        text="↻",
                        callback_data=f"controls replay {chat_id}",
                    ),
                    self.ikb(
                        text="»",
                        callback_data=f"controls skip {chat_id}",
                        style=enums.ButtonStyle.PRIMARY,
                    ),
                    self.ikb(
                        text="■",
                        callback_data=f"controls stop {chat_id}",
                        style=enums.ButtonStyle.DANGER,
                    ),
                ]
            )
        return self.ikm(keyboard)

    def help_markup(
        self, _lang: dict, back: bool = False, sudo: bool = False
    ) -> types.InlineKeyboardMarkup:
        if back:
            rows = [
                [
                    self.ikb(text=_lang["back"], callback_data="help back"),
                    self.ikb(
                        text=_lang["close"],
                        callback_data="help close",
                        style=enums.ButtonStyle.DANGER,
                    ),
                ]
            ]
        else:
            cbs = [
                "admins", "auth", "blist", "lang", "ping",
                "play", "queue", "stats",
            ]
            if sudo:
                cbs.append("sudo")
            buttons = [
                self.ikb(
                    text=_lang[f"help_{i}"],
                    callback_data=f"help {cb}",
                    style=(
                        enums.ButtonStyle.PRIMARY
                        if i in {0, 4, 5, 6}
                        else enums.ButtonStyle.DEFAULT
                    ),
                )
                for i, cb in enumerate(cbs)
            ]
            rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]

        return self.ikm(rows)

    def lang_markup(self, _lang: str) -> types.InlineKeyboardMarkup:
        langs = lang.get_languages()

        buttons = [
            self.ikb(
                text=f"{name} ({code}) {'✔️' if code == _lang else ''}",
                callback_data=f"lang_change {code}",
                style=(
                    enums.ButtonStyle.SUCCESS
                    if code == _lang
                    else enums.ButtonStyle.DEFAULT
                ),
            )
            for code, name in langs.items()
        ]
        rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
        return self.ikm(rows)

    def ping_markup(self, text: str) -> types.InlineKeyboardMarkup:
        return self.ikm(
            [[self.ikb(
                text=text,
                url=config.SUPPORT_CHAT,
                style=enums.ButtonStyle.PRIMARY,
            )]]
        )

    def play_queued(
        self, chat_id: int, item_id: str, _text: str
    ) -> types.InlineKeyboardMarkup:
        return self.ikm(
            [
                [
                    self.ikb(
                        text=_text,
                        callback_data=f"controls force {chat_id} {item_id}",
                        style=enums.ButtonStyle.SUCCESS,
                    )
                ]
            ]
        )

    def recovery(self, chat_id: int, text: str) -> types.InlineKeyboardMarkup:
        return self.ikm(
            [[self.ikb(
                text=text,
                callback_data=f"controls resume {chat_id}",
                style=enums.ButtonStyle.SUCCESS,
            )]]
        )

    def queue_markup(
        self, chat_id: int, _text: str, playing: bool
    ) -> types.InlineKeyboardMarkup:
        _action = "pause" if playing else "resume"
        return self.ikm(
            [
                [self.ikb(
                    text=_text,
                    callback_data=f"controls status {chat_id} q",
                )],
                [
                    self.ikb(
                        text="Ⅱ" if playing else "▷",
                        callback_data=f"controls {_action} {chat_id} q",
                        style=(
                            enums.ButtonStyle.PRIMARY
                            if playing
                            else enums.ButtonStyle.SUCCESS
                        ),
                    ),
                    self.ikb(
                        text="»",
                        callback_data=f"controls skip {chat_id} q",
                        style=enums.ButtonStyle.PRIMARY,
                    ),
                    self.ikb(
                        text="■",
                        callback_data=f"controls stop {chat_id} q",
                        style=enums.ButtonStyle.DANGER,
                    ),
                ],
            ]
        )

    def settings_markup(
        self,
        lang: dict,
        admin_only: bool,
        cmd_delete: bool,
        feedback_cleanup: bool,
        default_video: bool,
        language: str,
        chat_id: int,
    ) -> types.InlineKeyboardMarkup:
        return self.ikm(
            [
                [
                    self.ikb(
                        text="👥 " + lang["play_mode"],
                        callback_data="settings",
                    ),
                    self.ikb(
                        text=(
                            lang["setting_admins"]
                            if admin_only
                            else lang["setting_everyone"]
                        ),
                        callback_data="settings play",
                        style=enums.ButtonStyle.PRIMARY,
                    ),
                ],
                [
                    self.ikb(
                        text="🎧 " + lang["default_playback"],
                        callback_data="settings",
                    ),
                    self.ikb(
                        text=(
                            lang["setting_video"]
                            if default_video
                            else lang["setting_audio"]
                        ),
                        callback_data="settings video",
                        style=enums.ButtonStyle.PRIMARY,
                    ),
                ],
                [
                    self.ikb(text="⌨️ " + lang["cmd_delete"], callback_data="settings"),
                    self.ikb(
                        text=lang["setting_on"] if cmd_delete else lang["setting_off"],
                        callback_data="settings delete",
                        style=(
                            enums.ButtonStyle.SUCCESS
                            if cmd_delete
                            else enums.ButtonStyle.DEFAULT
                        ),
                    ),
                ],
                [
                    self.ikb(
                        text="✨ " + lang["clean_feedback"],
                        callback_data="settings",
                    ),
                    self.ikb(
                        text=(
                            lang["setting_on"]
                            if feedback_cleanup
                            else lang["setting_off"]
                        ),
                        callback_data="settings cleanup",
                        style=(
                            enums.ButtonStyle.SUCCESS
                            if feedback_cleanup
                            else enums.ButtonStyle.DEFAULT
                        ),
                    ),
                ],
                [
                    self.ikb(
                        text="🌐 " + lang["language"],
                        callback_data="settings",
                    ),
                    self.ikb(
                        text=lang_codes[language],
                        callback_data="language",
                        style=enums.ButtonStyle.PRIMARY,
                    ),
                ],
            ]
        )

    def setup_markup(self, lang: dict, ready: bool) -> types.InlineKeyboardMarkup:
        rows = [[
            self.ikb(
                text=lang["check_again"],
                callback_data="setup check",
                style=(
                    enums.ButtonStyle.SUCCESS
                    if ready
                    else enums.ButtonStyle.PRIMARY
                ),
            )
        ]]
        if ready:
            rows.append([
                self.ikb(
                    text=lang["settings"],
                    callback_data="setup settings",
                    style=enums.ButtonStyle.PRIMARY,
                ),
                self.ikb(text=lang["help"], callback_data="help"),
            ])
        return self.ikm(rows)

    def start_key(
        self, lang: dict, private: bool = False
    ) -> types.InlineKeyboardMarkup:
        rows = [
            [
                self.ikb(
                    text=lang["add_me"],
                    url=f"https://t.me/{app.username}?startgroup=true",
                    style=enums.ButtonStyle.SUCCESS,
                )
            ],
            [self.ikb(
                text=lang["help"],
                callback_data="help",
                style=enums.ButtonStyle.PRIMARY,
            )],
            [
                self.ikb(
                    text=lang["support"],
                    url=config.SUPPORT_CHAT,
                    style=enums.ButtonStyle.PRIMARY,
                ),
                self.ikb(text=lang["channel"], url=config.SUPPORT_CHANNEL),
            ],
        ]
        if private:
            rows += [
                [
                    self.ikb(
                        text=lang["source"],
                        url="https://github.com/AnonymousX1025/AnonXMusic",
                    )
                ]
            ]
        else:
            rows += [[self.ikb(
                text=lang["language"],
                callback_data="language",
                style=enums.ButtonStyle.PRIMARY,
            )]]
        return self.ikm(rows)

    def yt_key(self, link: str) -> types.InlineKeyboardMarkup:
        return self.ikm(
            [
                [
                    self.ikb(
                        text="Copy link",
                        copy_text=link,
                        style=enums.ButtonStyle.PRIMARY,
                    ),
                    self.ikb(text="YouTube", url=link),
                ],
            ]
        )
