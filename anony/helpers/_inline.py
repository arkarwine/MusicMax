# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


from pyrogram import enums, types

from anony import app, config, lang
from anony.core.lang import lang_codes
from anony.ui import callbacks
from anony.ui.keyboards import back_row, button, cancel_row, grid, markup


class Inline:
    def __init__(self):
        self.ikm = markup
        self.ikb = button

    @staticmethod
    def _control(name: str) -> str:
        return lang.languages["en"][f"control_{name}"]

    def cancel_dl(self, text) -> types.InlineKeyboardMarkup:
        return self.ikm([cancel_row(text, callbacks.CANCEL_DOWNLOAD)])

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
                [
                    self.ikb(
                        text=status,
                        callback_data=callbacks.controls("status", chat_id),
                    )
                ]
            )
        elif timer:
            keyboard.append(
                [
                    self.ikb(
                        text=timer,
                        callback_data=callbacks.controls("status", chat_id),
                    )
                ]
            )

        if not remove:
            playback = (
                self.ikb(
                    text=self._control("pause"),
                    callback_data=callbacks.controls("pause", chat_id),
                    style=enums.ButtonStyle.SUCCESS,
                )
                if playing
                else self.ikb(
                    text=self._control("resume"),
                    callback_data=callbacks.controls("resume", chat_id),
                    style=enums.ButtonStyle.DANGER,
                )
            )
            keyboard.append(
                [
                    self.ikb(
                        text=self._control("loop"),
                        callback_data=callbacks.controls("loop", chat_id),
                    ),
                    self.ikb(
                        text=self._control("stop"),
                        callback_data=callbacks.controls("stop", chat_id),
                        style=enums.ButtonStyle.DEFAULT,
                    ),
                    playback,
                    self.ikb(
                        text=self._control("skip"),
                        callback_data=callbacks.controls("skip", chat_id),
                        style=enums.ButtonStyle.DEFAULT,
                    ),
                    self.ikb(
                        text=self._control("replay"),
                        callback_data=callbacks.controls("replay", chat_id),
                    ),
                ]
            )
        return self.ikm(keyboard)

    def help_markup(
        self, _lang: dict, back: bool = False, sudo: bool = False
    ) -> types.InlineKeyboardMarkup | None:
        if back:
            return self.ikm([back_row(_lang["back"], callbacks.help("back"))])

        cbs = [
            "admins", "auth", "blist", "lang", "ping",
            "play", "queue", "stats",
        ]
        if sudo:
            cbs.append("sudo")
        help_buttons = [
            self.ikb(
                text=_lang[f"help_{i}"],
                callback_data=callbacks.help(cb),
                style=enums.ButtonStyle.DEFAULT,
            )
            for i, cb in enumerate(cbs)
        ]
        return self.ikm(grid(help_buttons, columns=3))

    def lang_markup(
        self, _lang: str, home: bool = True
    ) -> types.InlineKeyboardMarkup:
        langs = lang.get_languages()

        language_buttons = [
            self.ikb(
                text=f"{name} ({code}) {'✔️' if code == _lang else ''}",
                callback_data=callbacks.language_change(code),
                style=enums.ButtonStyle.DEFAULT,
            )
            for code, name in langs.items()
        ]
        return self.ikm(grid(language_buttons, columns=2))

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
                        callback_data=callbacks.controls("force", chat_id, item_id),
                        style=enums.ButtonStyle.DEFAULT,
                    )
                ]
            ]
        )

    def recovery(self, chat_id: int, text: str) -> types.InlineKeyboardMarkup:
        return self.ikm(
            [[self.ikb(
                text=text,
                callback_data=callbacks.controls("resume", chat_id),
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
                    callback_data=callbacks.controls("status", chat_id, "q"),
                )],
                [
                    self.ikb(
                        text=(
                            self._control("pause")
                            if playing
                            else self._control("resume")
                        ),
                        callback_data=callbacks.controls(_action, chat_id, "q"),
                        style=(
                            enums.ButtonStyle.SUCCESS
                            if playing
                            else enums.ButtonStyle.DANGER
                        ),
                    ),
                    self.ikb(
                        text=self._control("skip"),
                        callback_data=callbacks.controls("skip", chat_id, "q"),
                        style=enums.ButtonStyle.DEFAULT,
                    ),
                    self.ikb(
                        text=self._control("stop"),
                        callback_data=callbacks.controls("stop", chat_id, "q"),
                        style=enums.ButtonStyle.DEFAULT,
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
                        callback_data=callbacks.settings(chat_id),
                    ),
                    self.ikb(
                        text=(
                            lang["setting_admins"]
                            if admin_only
                            else lang["setting_everyone"]
                        ),
                        callback_data=callbacks.settings(chat_id, "play"),
                        style=enums.ButtonStyle.DEFAULT,
                    ),
                ],
                [
                    self.ikb(
                        text="🎧 " + lang["default_playback"],
                        callback_data=callbacks.settings(chat_id),
                    ),
                    self.ikb(
                        text=(
                            lang["setting_video"]
                            if default_video
                            else lang["setting_audio"]
                        ),
                        callback_data=callbacks.settings(chat_id, "video"),
                        style=enums.ButtonStyle.DEFAULT,
                    ),
                ],
                [
                    self.ikb(
                        text="⌨️ " + lang["cmd_delete"],
                        callback_data=callbacks.settings(chat_id),
                    ),
                    self.ikb(
                        text=lang["setting_on"] if cmd_delete else lang["setting_off"],
                        callback_data=callbacks.settings(chat_id, "delete"),
                        style=enums.ButtonStyle.DEFAULT,
                    ),
                ],
                [
                    self.ikb(
                        text="✨ " + lang["clean_feedback"],
                        callback_data=callbacks.settings(chat_id),
                    ),
                    self.ikb(
                        text=(
                            lang["setting_on"]
                            if feedback_cleanup
                            else lang["setting_off"]
                        ),
                        callback_data=callbacks.settings(chat_id, "cleanup"),
                        style=enums.ButtonStyle.DEFAULT,
                    ),
                ],
                [
                    self.ikb(
                        text="🌐 " + lang["language"],
                        callback_data=callbacks.settings(chat_id),
                    ),
                    self.ikb(
                        text=lang_codes[language],
                        callback_data=callbacks.settings(chat_id, "language"),
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
                callback_data=callbacks.setup(),
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
                self.ikb(text=lang["help"], callback_data=callbacks.help()),
            ])
        return self.ikm(rows)

    def group_lang_markup(
        self, _lang: str, chat_id: int, labels: dict
    ) -> types.InlineKeyboardMarkup:
        langs = lang.get_languages()
        choices = [
            self.ikb(
                text=f"{name} ({code}) {'✔️' if code == _lang else ''}",
                callback_data=callbacks.settings_language(chat_id, code),
                style=enums.ButtonStyle.DEFAULT,
            )
            for code, name in langs.items()
        ]
        rows = grid(choices, columns=2)
        rows.append(back_row(labels["back"], callbacks.settings(chat_id, "back")))
        return self.ikm(rows)

    def start_key(
        self,
        lang: dict,
        private: bool = False,
        chat_id: int | None = None,
    ) -> types.InlineKeyboardMarkup:
        rows = []
        if private:
            rows.append([self.ikb(
                text=lang["start_add_button"].format(lang["add_me"]),
                url=f"https://t.me/{app.username}?startgroup=true",
                style=enums.ButtonStyle.DANGER,
            )])
            rows += [[
                self.ikb(text=lang["help"], callback_data=callbacks.help()),
                self.ikb(
                    text=lang["language"],
                    callback_data=callbacks.LANGUAGE_ROOT,
                ),
                self.ikb(
                    text=lang["stats"],
                    callback_data=callbacks.stats("view"),
                ),
            ]]
            rows.append([
                self.ikb(
                    text=lang["trending"],
                    callback_data=callbacks.trending(),
                )
            ])
            rows += [
                [
                    self.ikb(
                        text=lang["start_support_button"].format(lang["support"]),
                        url=config.SUPPORT_CHAT,
                    ),
                    self.ikb(
                        text=lang["start_channel_button"].format(lang["channel"]),
                        url=config.SUPPORT_CHANNEL,
                    ),
                ],
                [
                    self.ikb(
                        text=lang["start_owner_button"].format(lang["owner"]),
                        url=app.owner_url,
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
                    text="⚙️ " + lang["settings"],
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
