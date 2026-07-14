# Telegram UI Refactor Plan

## Purpose

This document proposes a behavior-preserving refactor of repeated Telegram-native UI code in AnonXMusic. It covers keyboards, localized message presentation, callback-data construction, navigation, and transient feedback.

It does **not** change command behavior, handler routing, permissions, database logic, playback logic, API calls, localization copy, callback compatibility, or Telegram-visible flow. The conventions in `docs/TELEGRAM_UI_STYLE.md` remain the source of truth for visible behavior.

## Current UI ownership

The project already has useful shared layers:

- `anony/helpers/_inline.py` owns most public menu and playback keyboards through `Inline`.
- `anony/core/custom_emoji.py` owns custom-emoji button construction and fallback rebuilding.
- `anony/helpers/_feedback.py` owns optional cleanup for short messages and callback toasts.
- `anony/helpers/_navigation.py` chooses between editing a text view and sending a new message from a media launcher.
- `anony/core/bot.py` applies HTML/custom-emoji rendering to central send and edit methods.
- `anony/core/lang.py` loads localized text and separates ordinary-user errors from sudo diagnostics.

The remaining repetition is concentrated in `anony/plugins/sessions.py`, `anony/plugins/runtime_config.py`, `anony/plugins/callbacks.py`, and command handlers that manually implement status-message lifecycles.

## Repeated pattern inventory

### Menu keyboards

Repeated forms:

- A grid of destination buttons, such as Help categories in `Inline.help_markup()`.
- A two-column selection grid, such as `Inline.lang_markup()` and `Inline.group_lang_markup()`.
- Label/value setting rows in `Inline.settings_markup()`.
- A list of one entity per row followed by navigation, such as `_dashboard_markup()` in `anony/plugins/sessions.py`.
- A root Home row appended manually in both `anony/plugins/sessions.py` and `anony/plugins/runtime_config.py`.
- A final Back row appended manually by Help, group language, and assistant-session views.

Repeated mechanics:

- Construct `InlineKeyboardMarkup` from rows.
- Construct buttons through `buttons.ikb`/`custom_emoji_button`.
- Split a flat choice list into rows of two or three.
- Append a navigation row after the feature-specific actions.
- Repeat `ButtonStyle.DEFAULT` even though it is the neutral default.

Refactor opportunity: shared row/grid/navigation primitives, while feature modules continue to decide labels, order, callbacks, styles, and visibility.

### Confirmation keyboards

The clearest confirmation flow is permanent assistant removal in `_remove_confirmation()` in `anony/plugins/sessions.py`:

```text
[ Remove permanently ] [ Keep session ]
```

It repeats a general structure that future destructive flows will also need:

- localized confirmation text;
- one danger action;
- one safe return action;
- callback context repeated on both buttons;
- a keyboard that is replaced after completion.

Refactor opportunity: a generic `confirmation_keyboard()` that accepts already-localized labels and already-built callback data. It must not decide whether confirmation is required or execute either action.

### Back buttons

Back-like buttons currently appear as:

- localized `‹ Back` with `help back` in `Inline.help_markup()`;
- localized Back with `settings {chat_id} back` in `Inline.group_lang_markup()`;
- hard-coded `⬅️ Assistants` with `session page {page}` in multiple session views;
- hard-coded `⬅️ Keep session` with `session view {slot} {page}` in removal confirmation.

The visual role is repeated even though the destination and label vary.

Refactor opportunity: `back_button(label, callback_data)` and `back_row(...)`. Keep labels and callback destinations supplied by the feature so existing wording and behavior do not change.

### Cancel buttons

There are two cancellation patterns:

- `Inline.cancel_dl()` builds a single red `cancel_dl` button for cancellable downloads.
- Assistant sign-in is cancelled with `/cancel`; its prompts repeat that instruction in localized message text and `_cancel_session_add()` performs cleanup.

The button construction can be generalized, but the session command flow should remain unchanged. A shared helper must not add a Cancel button where none exists today.

Refactor opportunity: `cancel_button(label, callback_data, danger=True)` and `cancel_row(...)`, initially used only by the existing download keyboard.

### Home buttons

The same destination appears in:

- session dashboard: hard-coded `⬅️ Home`, callback `help home`;
- runtime configuration: hard-coded `⬅️ Home`, callback `help home`;
- Help callback handling: `help home` returns to the Start view.

Refactor opportunity: a shared `home_row(label, callback_data="help home")`. The helper centralizes construction, not routing.

### Pagination keyboards

`_dashboard_markup()` in `anony/plugins/sessions.py` manually implements:

- page clamping;
- previous-page callback;
- inert `current / total` indicator;
- next-page callback;
- entity rows above the paginator;
- Add and Home rows below it.

Current shape:

```text
[ ‹ ] [ 2 / 4 ] [ › ]
```

Refactor opportunity: a reusable `pagination_row()` that receives `page`, `page_count`, and callback factory. Page calculation over session records may remain in the session feature to avoid mixing data logic into UI primitives.

### Success messages

Localized success messages repeatedly use a leading `✅` and a concise result:

- `auth_added`, `auth_removed` in `anony/plugins/auth.py`;
- `admin_cache_reloaded` in `anony/plugins/auth.py`;
- `loop_set`, `loop_off` in `anony/plugins/loop.py`;
- `play_paused`, `play_resumed`, `play_skipped`, `play_stopped` in playback commands;
- `backup_done` in `anony/plugins/setup.py`;
- `restarted`, `logger_on`, `setlog_success` in `anony/plugins/restart.py`.

Delivery is split between `feedback.send()`, `feedback.edit()`, and direct `reply_text()`/`edit_text()` calls. This makes cleanup behavior depend on the handler rather than the message role.

Refactor opportunity: semantic presentation methods such as `feedback.success()` and `feedback.success_edit()`. They must accept final localized HTML unchanged; they should not prepend emoji or rewrite copy.

### Error messages

Repeated error delivery includes:

- `feedback.send(..., error=True)` for playback and queue failures;
- `feedback.edit(..., error=True)` after a loading message in `/play` and `/queue`;
- direct replies in auth, blacklist, sessions, runtime config, song, stats, and trending;
- repeated expired-control responses across callbacks, language, sessions, and runtime configuration;
- user/sudo exception templates centralized in `Language.language()`.

The same semantic error may therefore be transient, permanent, a toast, or an alert depending on which method a handler calls.

Refactor opportunity:

- Add explicit `feedback.error()`, `feedback.error_edit()`, and `feedback.expired()` methods.
- Keep `error=True` as a compatibility path during migration.
- Let the caller still choose message versus callback, toast versus alert, and cleanup override.
- Do not catch new exceptions or alter the existing global error wrapper.

### Warning messages

Warnings are stored as normal locale strings and typically start with `⚠️`:

- `error_no_call` and other playback recovery guidance;
- `admin_required`, `play_unban_required`, and assistant join guidance;
- `stats_failed`, `trending_failed`, and `song_failed`;
- invalid two-step password and session action failures.

There is no semantic warning method, so handlers use direct edit/reply or the error cleanup path.

Refactor opportunity: `feedback.warning()` and `feedback.warning_edit()` with an explicit persistence option. Actionable setup or permission warnings remain persistent; routine warnings retain their current cleanup behavior.

### Empty-state messages

Repeated empty results include:

- `not_playing` in pause, resume, skip, stop, loop, queue, callbacks, and seek;
- `auth_empty` in `anony/plugins/auth.py`;
- `vc_empty` in `anony/plugins/active.py`;
- `log_not_found` in `anony/plugins/restart.py`;
- `trending_empty` in `anony/plugins/trending.py`;
- `session_not_found` for missing assistant lookups.

These are semantically similar but have different delivery requirements. For example, `not_playing` can be a command reply, callback toast, or callback alert.

Refactor opportunity: an `empty()` presentation method for messages and an `empty_toast()` alias for callbacks. The caller provides the localized text and current visibility/alert choice.

### Message templates

Repeated message structures include:

1. **Loading then result**

   Used by active-call listing, admin-cache refresh, broadcast, log retrieval, restart, play, queue, song download, stats, and sudo-list retrieval.

   ```text
   reply loading → perform work → edit same message with result/error
   ```

2. **Heading, blank line, detail block**

   Used by playback cards, queue cards, Help pages, session detail, setup, stats caption, and sudo status.

3. **Technical failure block**

   Used by `feedback_error_sudo`, `session_action_failed`, `session_phone_failed`, and `setlog_failed` with error type/details wrapped in `<code>` or expandable quotes.

4. **Entity summary**

   Used by session dashboard/detail, auth list, active calls, stats, and status.

Refactor opportunity:

- A `StatusMessage` wrapper for the existing loading-message lifecycle.
- Small trusted HTML composition helpers for headings, sections, code values, and blockquotes only where templates are currently assembled in Python.
- Keep complete localized messages in locale files. Do not decompose natural-language locale strings into fragments merely to reuse HTML tags.

### Callback-data construction

Callback strings are assembled with f-strings throughout the project:

- `controls {action} {chat_id} [q|item_id]` in `anony/helpers/_inline.py`;
- `help {destination}` in Help;
- `settings {chat_id} {action}` and `settings_lang {chat_id} {code}`;
- `session {action} {slot|page} [page]` throughout `anony/plugins/sessions.py`;
- `runtime_config toggle {key}`;
- fixed forms such as `stats view`, `stats refresh`, `trending view`, `setup check`, `cancel_dl`, and `language`.

Problems caused by repetition:

- namespace and argument order are implicit;
- optional arguments are assembled differently per call site;
- handler parsing and keyboard construction can drift apart;
- callback length is not checked centrally;
- some callback filters are anchored and others match a prefix loosely;
- compatibility strings are hard to inventory before a rename.

Refactor opportunity: one callback builder per namespace backed by a small safe joiner. Existing strings must remain byte-for-byte identical.

## Proposed module structure

```text
anony/
└── ui/
    ├── __init__.py
    ├── callbacks.py       # callback-data constants and builders
    ├── keyboards.py       # generic rows, navigation, confirmation, pagination
    ├── messages.py        # semantic feedback facade and status-message lifecycle
    └── html.py            # trusted HTML composition helpers, if justified

anony/helpers/
├── _inline.py             # feature-level public/playback/settings keyboards
├── _feedback.py           # cleanup scheduler and low-level delivery
└── _navigation.py         # Telegram edit-versus-send behavior
```

This is an additive structure. Existing helper modules stay in place until all call sites have migrated and compatibility imports can be provided.

### Responsibility boundary

`anony/ui/keyboards.py` may know:

- how to create buttons and rows;
- the visual structure of Back, Home, Cancel, confirmation, and pagination controls;
- how to chunk buttons into a grid;
- how to preserve button styles and custom emoji through `custom_emoji_button`.

It must not know:

- whether a user is allowed to press a button;
- which database record exists;
- whether an operation needs confirmation;
- what callback handler performs the action;
- how playback, sessions, settings, or downloads work.

`anony/ui/callbacks.py` may know:

- stable namespace names;
- argument order;
- how to join scalar callback fields;
- Telegram callback-data length validation in development/tests.

It must not perform callback actions, permission checks, database reads, API calls, or handler registration.

`anony/ui/messages.py` may know:

- whether a UI result is success, information, warning, error, empty, or processing;
- how to delegate sends/edits/toasts to the existing `Feedback` cleanup behavior;
- how to retain and edit one processing message.

It must not create user-facing prose, translate text, catch business exceptions, or decide success/failure.

## Proposed helper APIs

The signatures below are illustrative and deliberately accept localized labels/text from callers.

### Keyboard primitives

```python
def button(
    text: str,
    *,
    callback_data: str | None = None,
    url: str | None = None,
    style: ButtonStyle = ButtonStyle.DEFAULT,
    **telegram_options,
) -> InlineKeyboardButton: ...

def grid(
    buttons: Sequence[InlineKeyboardButton],
    *,
    columns: int,
) -> list[list[InlineKeyboardButton]]: ...

def back_button(text: str, callback_data: str) -> InlineKeyboardButton: ...
def back_row(text: str, callback_data: str) -> list[InlineKeyboardButton]: ...

def home_button(
    text: str,
    callback_data: str = "help home",
) -> InlineKeyboardButton: ...

def home_row(
    text: str,
    callback_data: str = "help home",
) -> list[InlineKeyboardButton]: ...

def cancel_button(
    text: str,
    callback_data: str,
    *,
    danger: bool = True,
) -> InlineKeyboardButton: ...
```

All button creation must continue through `custom_emoji_button()` so custom emoji, Unicode fallback, and native styles behave exactly as they do now.

### Confirmation keyboard

```python
def confirmation_keyboard(
    *,
    confirm_text: str,
    confirm_callback: str,
    cancel_text: str,
    cancel_callback: str,
    confirm_style: ButtonStyle = ButtonStyle.DANGER,
) -> InlineKeyboardMarkup: ...
```

Initial mapping:

```python
confirmation_keyboard(
    confirm_text="🗑 Remove permanently",
    confirm_callback=callbacks.session("confirm_remove", slot, page),
    cancel_text="⬅️ Keep session",
    cancel_callback=callbacks.session("view", slot, page),
)
```

The strings shown above reflect current UI and should come from localization during implementation.

### Pagination

```python
def pagination_row(
    *,
    page: int,
    page_count: int,
    callback_for_page: Callable[[int], str],
    previous_text: str = "‹",
    next_text: str = "›",
    indicator_callback: str,
) -> list[InlineKeyboardButton]: ...
```

Requirements:

- preserve the current zero-based callback page values;
- preserve the displayed one-based `current / total` value;
- clamp previous/next destinations exactly as the session dashboard does today;
- keep the indicator inert through the existing `session noop` callback;
- do not fetch, slice, count, or sort entities.

### Callback builders

```python
MAX_CALLBACK_BYTES = 64

def build(namespace: str, *parts: object) -> str: ...

def controls(action: str, chat_id: int, context: str | None = None) -> str: ...
def help(destination: str | None = None) -> str: ...
def settings(chat_id: int, action: str | None = None) -> str: ...
def settings_language(chat_id: int, code: str) -> str: ...
def session(action: str, *parts: int | str) -> str: ...
def runtime_config(action: str, key: str) -> str: ...
def stats(action: str) -> str: ...
def trending(action: str = "view") -> str: ...
def setup(action: str = "check") -> str: ...
```

Examples must remain identical:

```python
controls("pause", -100123)          # "controls pause -100123"
controls("status", -100123, "q")   # "controls status -100123 q"
settings(-100123, "language")       # "settings -100123 language"
session("view", 2, 0)               # "session view 2 0"
stats("refresh")                     # "stats refresh"
```

`build()` should reject whitespace inside individual tokens and raise in tests/development if UTF-8 encoded callback data exceeds Telegram's limit. It must not silently truncate data.

Fixed compatibility callbacks may be constants:

```python
CANCEL_DOWNLOAD = "cancel_dl"
LANGUAGE_ROOT = "language"
HELP_HOME = "help home"
```

### Semantic feedback facade

```python
class TelegramUI:
    async def success(self, update, text, *, reply_markup=None, keep=None): ...
    async def info(self, update, text, *, reply_markup=None, keep=None): ...
    async def warning(self, update, text, *, reply_markup=None, keep=None): ...
    async def error(self, update, text, *, reply_markup=None, keep=None): ...
    async def empty(self, update, text, *, reply_markup=None, keep=None): ...
    async def toast(self, query, text="", *, alert=False): ...
    async def expired(self, query, text, *, alert=False): ...
```

These methods should initially be thin adapters over the existing `Feedback` class. To preserve behavior, each migrated call must explicitly retain its current timeout, persistence, reply/edit mode, notification mode, and alert setting.

The facade must not infer category from emoji or prepend `✅`, `⚠️`, or `ℹ️`. Locale strings remain the only source of visible copy.

### Processing message lifecycle

```python
class StatusMessage:
    @classmethod
    async def begin(
        cls,
        source: Message,
        text: str,
        *,
        reply_markup=None,
        disable_notification: bool = False,
    ) -> "StatusMessage": ...

    async def update(self, text: str, *, reply_markup=None) -> Message: ...
    async def succeed(self, text: str, *, reply_markup=None, keep=None) -> Message: ...
    async def fail(self, text: str, *, reply_markup=None, keep=None) -> Message: ...
    async def remove(self) -> None: ...
```

Good initial candidates are `/song`, `/queue`, `/play`, log retrieval, admin-cache refresh, and restart. The wrapper should retain the original message object and delegate to existing reply/edit methods. It must not run work, manage exceptions, decide copy, or alter when handlers delete the status.

### Trusted HTML helpers

Only introduce `anony/ui/html.py` if Python-built templates still repeat after keyboards and feedback are centralized.

Possible narrow helpers:

```python
def heading(text: str) -> str: ...
def code(value: object) -> str: ...
def quote(text: str, *, expandable: bool = False) -> str: ...
def sections(*blocks: str) -> str: ...
```

Rules:

- escape values by default;
- accept an explicit trusted-HTML type for localized templates;
- never regex-transform user content;
- never rebuild full natural-language messages from untranslated fragments;
- preserve existing HTML output byte-for-byte during migration.

## Recommended feature-level builders

Generic primitives should not turn `anony/helpers/_inline.py` into one universal keyboard function. Keep feature intent visible through dedicated builders:

- `playback_controls(...)`
- `queue_controls(...)`
- `help_menu(...)` and `help_back(...)`
- `language_choices(...)`
- `settings_menu(...)`
- `setup_actions(...)`
- `start_menu(...)`
- `session_dashboard(...)`
- `session_detail(...)`
- `session_remove_confirmation(...)`
- `runtime_config_menu(...)`
- `stats_actions(...)`

`Inline` may remain the compatibility facade while its methods delegate to `anony.ui.keyboards` and callback builders. Session/runtime/stats builders can move into feature-focused modules later; handlers should receive final text/markup without knowing row construction details.

## Candidate-to-helper mapping

| Current location | Repeated pattern | Proposed target |
|---|---|---|
| `Inline.help_markup()` | three-column grid, Back row | `grid()`, `back_row()`, `callbacks.help()` |
| `Inline.lang_markup()` | two-column choice grid | `grid()`, language callback builder |
| `Inline.group_lang_markup()` | choice grid plus Back | `grid()`, `back_row()`, settings callback builders |
| `Inline.cancel_dl()` | one-button danger cancel row | `cancel_button()`, `CANCEL_DOWNLOAD` |
| `Inline.controls()` / `queue_markup()` | repeated controls callback f-strings | `callbacks.controls()` |
| `Inline.settings_markup()` | repeated settings callback f-strings | `callbacks.settings()` |
| `_dashboard_markup()` in sessions | entity rows, pagination, Add, Home | `pagination_row()`, `home_row()`, session builders |
| `_detail()` / `_add_method_view()` in sessions | repeated Assistants Back row | `back_row()`, `callbacks.session()` |
| `_remove_confirmation()` in sessions | danger/safe confirmation | `confirmation_keyboard()` |
| `_runtime_view()` | repeated rows plus Home | `home_row()`, runtime-config builder |
| `_stats_markup()` | single feature action | `callbacks.stats()`; retain feature builder |
| callbacks/language/sessions/runtime config | repeated expired answers | `ui.expired()` |
| play/queue/song/restart/auth/active | loading then edit | `StatusMessage` |
| playback commands and auth | short semantic results | `ui.success/info/error/empty()` |

## Migration sequence

### Phase 1: Lock current behavior with characterization tests

Before moving code, snapshot:

- button text, style, row order, URLs, callback data, and custom emoji IDs;
- Help category visibility for ordinary and sudo users;
- language selected markers;
- playback keyboard in playing, paused, timer, and removed states;
- settings keyboard values and callbacks;
- session pages, detail actions, confirmation, Add flow, and Home/Back destinations;
- callback toast versus alert choices;
- message cleanup timing and persistent exceptions;
- edit-versus-send behavior from text and media launchers.

No production logic changes belong in this phase.

### Phase 2: Add callback builders and constants

- Implement builders with byte-for-byte expected outputs.
- Replace f-strings in keyboard construction only.
- Keep handler parsing and filters unchanged.
- Add tests comparing every old literal/f-string output with the new builder.

This is the lowest-risk first extraction because callback strings are pure values.

### Phase 3: Add keyboard primitives

- Introduce `grid`, navigation rows, cancel, confirmation, and pagination.
- Make `Inline` delegate to them without changing its public method signatures.
- Migrate session and runtime-config keyboard construction after public shared keyboards.
- Compare serialized button fields before and after each migration.

### Phase 4: Add semantic feedback adapters

- Add thin adapters over `Feedback`.
- Migrate exact equivalents first: existing `feedback.send(..., error=True)` and `feedback.edit(..., error=True)`.
- Migrate direct replies only when tests prove timeout, persistence, notification, markup, and reply target remain identical.
- Retain `Feedback.send/edit/toast` as compatibility APIs until all plugins are stable.

### Phase 5: Extract the status-message lifecycle

- Start with `/song`, whose Searching → Downloading → Uploading lifecycle is self-contained.
- Continue with queue and simple administrative loading messages.
- Migrate `/play` only after the wrapper supports every existing media/card transition and error exit.
- Do not wrap business calls or exception handling inside the status helper.

### Phase 6: Optional trusted HTML primitives

- Recount Python-built HTML after the earlier phases.
- Add only helpers that remove genuine structural duplication.
- Do not rewrite locale-file templates merely for stylistic uniformity.

### Phase 7: Remove compatibility duplication

- Remove old private construction helpers only after all call sites and tests use the new layer.
- Keep public imports or aliases where plugins may depend on `buttons`, `feedback`, or `navigate`.
- Update `docs/TELEGRAM_UI_STYLE.md` only if module ownership changes; visible conventions remain unchanged.

## Verification plan

### Keyboard equivalence

For every migrated keyboard, assert:

- identical row count and button order;
- identical visible fallback text;
- identical `icon_custom_emoji_id` when supported;
- identical callback data and URLs;
- identical `ButtonStyle` values;
- identical copy-text and other Telegram-native button fields;
- identical custom-emoji fallback keyboard after rejection.

### Callback compatibility

- Table-test all callback builder outputs.
- Assert UTF-8 byte length is at most 64.
- Run existing callback handlers against the generated values without changing their parsers.
- Verify expired, unauthorized, no-op, and malformed callback behavior is unchanged.

### Message equivalence

- Assert exact HTML strings passed to send/edit APIs.
- Assert parse mode and escaping remain centralized.
- Assert the same message is edited or a new one is sent in each flow.
- Assert media captions remain captions and text fallbacks remain available.
- Assert minor success and routine error cleanup delays remain 8 and 20 seconds where currently enabled.
- Assert actionable errors, setup, queues, playback cards, sudo reports, and private messages retain their current persistence.

### Conversation equivalence

- Verify ForceReply prompt IDs, initiating-user checks, expiry, secret deletion, and stage changes are untouched.
- Verify no new Cancel, Back, Home, or confirmation step appears.
- Verify session pagination returns to the same page after detail and confirmation views.
- Verify the Start launcher remains unedited while text submenus continue editing in place.

### Regression scope

Run the existing test suite plus focused tests for:

- custom emoji supported and unsupported paths;
- Help, language, settings, setup, Start, sessions, stats, queue, and playback keyboards;
- ordinary versus sudo errors;
- public versus private flows;
- custom button fields missing from older framework objects;
- expired callbacks and deleted source messages.

## Explicit non-goals

This refactor must not:

- rename commands or callbacks;
- change handler filters or registration;
- change button labels, emoji, colors, order, or visibility;
- add or remove confirmation steps;
- add Back, Cancel, Home, pagination, or reply keyboards to existing flows;
- change whether a message is sent, edited, deleted, or automatically cleaned;
- move group settings out of private chat or expose sudo controls;
- change locale wording or fallback behavior;
- change session state, ForceReply stages, timeouts, or secret handling;
- change database schema, reads, writes, or caching;
- change playback, download, Telegram API, or assistant-session logic;
- change exception handling or logging behavior.

## Recommended end state

Handlers remain responsible for validation and actions. Feature-level builders remain responsible for which controls a view contains. The reusable UI layer becomes responsible only for consistent construction and presentation:

```text
handler
  ├─ gets localized text
  ├─ performs existing validation/action
  └─ requests a feature view
       ├─ feature keyboard builder
       │    ├─ generic keyboard primitives
       │    └─ callback-data builders
       └─ semantic feedback/status presentation
            ├─ existing cleanup policy
            ├─ existing navigation policy
            └─ existing custom-emoji fallback
```

This removes repeated Telegram UI plumbing while keeping every user-visible interaction and every non-UI responsibility in its current place.
