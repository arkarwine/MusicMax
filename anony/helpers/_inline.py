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
                    style=enums.ButtonStyle.DEFAULT,
                )
                if playing
                else self.ikb(
                    text="▷",
                    callback_data=f"controls resume {chat_id}",
                    style=enums.ButtonStyle.DEFAULT,
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
                        style=enums.ButtonStyle.DEFAULT,
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
            rows = [[self.ikb(text=_lang["back"], callback_data="help back")]]
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
                    style=enums.ButtonStyle.DEFAULT,
                )
                for i, cb in enumerate(cbs)
            ]
            rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
            rows.append([
                self.ikb(text=_lang["home"], callback_data="help home")
            ])

        return self.ikm(rows)

    def lang_markup(
        self, _lang: str, home: bool = True
    ) -> types.InlineKeyboardMarkup:
        langs = lang.get_languages()

        buttons = [
            self.ikb(
                text=f"{name} ({code}) {'✔️' if code == _lang else ''}",
                callback_data=f"lang_change {code}",
                style=enums.ButtonStyle.DEFAULT,
            )
            for code, name in langs.items()
        ]
        rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
        if home:
            rows.append([
                self.ikb(
                    text=lang.languages.get(_lang, lang.languages["en"])["home"],
                    callback_data="help home",
                )
            ])
        return self.ikm(rows)

    def ping_markup(self, text: str) -> types.InlineKeyboardMarkup:
        return self.ikm(
            [[self.ikb(
                text=text,
                url=config.SUPPORT_CHAT,
                style=enums.ButtonStyle.DEFAULT,
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
                        style=enums.ButtonStyle.DEFAULT,
                    )
                ]
            ]
        )

    def recovery(self, chat_id: int, text: str) -> types.InlineKeyboardMarkup:
        return self.ikm(
            [[self.ikb(
                text=text,
                callback_data=f"controls resume {chat_id}",
                style=enums.ButtonStyle.DEFAULT,
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
                        style=enums.ButtonStyle.DEFAULT,
                    ),
                    self.ikb(
                        text="»",
                        callback_data=f"controls skip {chat_id} q",
                        style=enums.ButtonStyle.DEFAULT,
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
                        callback_data=f"settings {chat_id}",
                    ),
                    self.ikb(
                        text=(
                            lang["setting_admins"]
                            if admin_only
                            else lang["setting_everyone"]
                        ),
                        callback_data=f"settings {chat_id} play",
                        style=enums.ButtonStyle.DEFAULT,
                    ),
                ],
                [
                    self.ikb(
                        text="🎧 " + lang["default_playback"],
                        callback_data=f"settings {chat_id}",
                    ),
                    self.ikb(
                        text=(
                            lang["setting_video"]
                            if default_video
                            else lang["setting_audio"]
                        ),
                        callback_data=f"settings {chat_id} video",
                        style=enums.ButtonStyle.DEFAULT,
                    ),
                ],
                [
                    self.ikb(
                        text="⌨️ " + lang["cmd_delete"],
                        callback_data=f"settings {chat_id}",
                    ),
                    self.ikb(
                        text=lang["setting_on"] if cmd_delete else lang["setting_off"],
                        callback_data=f"settings {chat_id} delete",
                        style=enums.ButtonStyle.DEFAULT,
                    ),
                ],
                [
                    self.ikb(
                        text="✨ " + lang["clean_feedback"],
                        callback_data=f"settings {chat_id}",
                    ),
                    self.ikb(
                        text=(
                            lang["setting_on"]
                            if feedback_cleanup
                            else lang["setting_off"]
                        ),
                        callback_data=f"settings {chat_id} cleanup",
                        style=enums.ButtonStyle.DEFAULT,
                    ),
                ],
                [
                    self.ikb(
                        text="🌐 " + lang["language"],
                        callback_data=f"settings {chat_id}",
                    ),
                    self.ikb(
                        text=lang_codes[language],
                        callback_data=f"settings {chat_id} language",
                        style=enums.ButtonStyle.DEFAULT,
                    ),
                ],
            ]
        )

    def settings_link(self, lang: dict, chat_id: int) -> types.InlineKeyboardMarkup:
        return self.ikm([[
            self.ikb(
                text=lang["open_settings"],
                url=f"https://t.me/{app.username}?start=settings_{chat_id}",
                style=enums.ButtonStyle.DEFAULT,
            )
        ]])

    def setup_markup(
        self, lang: dict, ready: bool, chat_id: int
    ) -> types.InlineKeyboardMarkup:
        rows = [[
            self.ikb(
                text=lang["check_again"],
                callback_data="setup check",
                style=enums.ButtonStyle.DEFAULT,
            )
        ]]
        if ready:
            rows.append([
                self.ikb(
                    text=lang["settings"],
                    url=f"https://t.me/{app.username}?start=settings_{chat_id}",
                    style=enums.ButtonStyle.DEFAULT,
                ),
                self.ikb(text=lang["help"], callback_data="help"),
            ])
        return self.ikm(rows)

    def group_lang_markup(
        self, _lang: str, chat_id: int, labels: dict
    ) -> types.InlineKeyboardMarkup:
        langs = lang.get_languages()
        choices = [
            self.ikb(
                text=f"{name} ({code}) {'✔️' if code == _lang else ''}",
                callback_data=f"settings_lang {chat_id} {code}",
                style=enums.ButtonStyle.DEFAULT,
            )
            for code, name in langs.items()
        ]
        rows = [choices[i : i + 2] for i in range(0, len(choices), 2)]
        rows.append([
            self.ikb(
                text=labels["back"],
                callback_data=f"settings {chat_id} back",
            )
        ])
        return self.ikm(rows)

    def start_key(
        self,
        lang: dict,
        private: bool = False,
        sudo: bool = False,
        chat_id: int | None = None,
    ) -> types.InlineKeyboardMarkup:
        rows = []
        if private:
            rows.append([self.ikb(
                text=lang["add_me"],
                url=f"https://t.me/{app.username}?startgroup=true",
                style=enums.ButtonStyle.SUCCESS,
            )])
            rows += [[
                self.ikb(text=lang["help"], callback_data="help"),
                self.ikb(text=lang["language"], callback_data="language"),
            ]]
            if sudo:
                rows.append([
                    self.ikb(
                        text=lang["session_manager"],
                        callback_data="session page 0",
                    )
                ])
            rows += [
                [
                    self.ikb(text=lang["support"], url=config.SUPPORT_CHAT),
                    self.ikb(text=lang["channel"], url=config.SUPPORT_CHANNEL),
                ],
                [
                    self.ikb(
                        text=lang["source"],
                        url="https://github.com/AnonymousX1025/AnonXMusic",
                    )
                ]
            ]
        elif chat_id is not None:
            rows.append([
                self.ikb(
                    text=lang["help"],
                    url=f"https://t.me/{app.username}?start=help",
                ),
                self.ikb(
                    text=lang["settings"],
                    url=f"https://t.me/{app.username}?start=settings_{chat_id}",
                ),
            ])
        return self.ikm(rows)

    def yt_key(self, link: str) -> types.InlineKeyboardMarkup:
        return self.ikm(
            [
                [
                    self.ikb(
                        text="Copy link",
                        copy_text=link,
                        style=enums.ButtonStyle.DEFAULT,
                    ),
                    self.ikb(text="YouTube", url=link),
                ],
            ]
        )
