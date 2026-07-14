"""Generic Telegram inline-keyboard construction primitives."""

from collections.abc import Callable, Sequence

from pyrogram import enums, types

from anony.core.custom_emoji import custom_emoji_button


def button(text: str, **kwargs) -> types.InlineKeyboardButton:
    """Build a button through the project's custom-emoji compatibility layer."""
    return custom_emoji_button(text=text, **kwargs)


def markup(
    rows: Sequence[Sequence[types.InlineKeyboardButton]],
) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup([list(row) for row in rows])


def grid(
    items: Sequence[types.InlineKeyboardButton],
    *,
    columns: int,
) -> list[list[types.InlineKeyboardButton]]:
    if columns < 1:
        raise ValueError("columns must be at least 1")
    return [
        list(items[index : index + columns])
        for index in range(0, len(items), columns)
    ]


def back_button(text: str, callback_data: str) -> types.InlineKeyboardButton:
    return button(text=text, callback_data=callback_data)


def back_row(text: str, callback_data: str) -> list[types.InlineKeyboardButton]:
    return [back_button(text, callback_data)]


def home_button(
    text: str,
    callback_data: str = "help home",
) -> types.InlineKeyboardButton:
    return button(text=text, callback_data=callback_data)


def home_row(
    text: str,
    callback_data: str = "help home",
) -> list[types.InlineKeyboardButton]:
    return [home_button(text, callback_data)]


def cancel_button(
    text: str,
    callback_data: str,
    *,
    danger: bool = True,
) -> types.InlineKeyboardButton:
    return button(
        text=text,
        callback_data=callback_data,
        style=enums.ButtonStyle.DANGER if danger else enums.ButtonStyle.DEFAULT,
    )


def cancel_row(
    text: str,
    callback_data: str,
    *,
    danger: bool = True,
) -> list[types.InlineKeyboardButton]:
    return [cancel_button(text, callback_data, danger=danger)]


def confirmation_keyboard(
    *,
    confirm_text: str,
    confirm_callback: str,
    cancel_text: str,
    cancel_callback: str,
    confirm_style: enums.ButtonStyle = enums.ButtonStyle.DANGER,
) -> types.InlineKeyboardMarkup:
    return markup([[
        button(
            text=confirm_text,
            callback_data=confirm_callback,
            style=confirm_style,
        ),
        button(text=cancel_text, callback_data=cancel_callback),
    ]])


def pagination_row(
    *,
    page: int,
    page_count: int,
    callback_for_page: Callable[[int], str],
    indicator_callback: str,
    previous_text: str = "‹",
    next_text: str = "›",
) -> list[types.InlineKeyboardButton]:
    pages = max(1, page_count)
    current = max(0, min(page, pages - 1))
    return [
        button(
            text=previous_text,
            callback_data=callback_for_page(max(0, current - 1)),
        ),
        button(
            text=f"{current + 1} / {pages}",
            callback_data=indicator_callback,
        ),
        button(
            text=next_text,
            callback_data=callback_for_page(min(pages - 1, current + 1)),
        ),
    ]
