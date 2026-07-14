# Telegram UI Style Guide

This guide defines the user-facing conventions for AnonXMusic as a standard Telegram chat bot. It covers messages, Telegram formatting, keyboards, callbacks, media, and conversational state. New interactions should follow these rules unless Telegram API constraints require an exception.

The primary references are the English locale (`anony/locales/en.json`), shared keyboard builder (`anony/helpers/_inline.py`), feedback and navigation helpers, and existing command handlers. User-visible text belongs in locale files; English is the fallback language.

## Message formatting rules

- Use Telegram HTML parse mode. The client configures it globally in `Bot.__init__()` in `anony/core/bot.py`.
- Keep messages compact: one purpose, one next action, and no implementation details for ordinary users.
- Use this order when all three parts are needed:
  1. short state or heading;
  2. essential details;
  3. one clear next action.
- Separate logical sections with one blank line. Do not build dense paragraphs.
- Use `<b>` for headings, current track titles, and values that need immediate attention.
- Use `<i>` for short command explanations in Help.
- Use `<code>` for commands, IDs, reference codes, arguments, and literal values.
- Use `<blockquote>` for compact supporting details. Use `<blockquote expandable>` only for long technical reports or lists.
- Use `<a href="...">` for a named destination or source instead of exposing a raw URL.
- Escape dynamic user-provided values before inserting them into localized HTML. Do not transform arbitrary user content as if it were a trusted template.
- Preserve custom emoji tags only in trusted locale or template text. The centralized custom-emoji layer in `anony/core/custom_emoji.py` supplies Unicode fallbacks.
- Use ellipsis character `…`, not three periods, for an operation in progress.

Repository examples:

```html
🎵 <b>Nᴏᴡ Pʟᴀʏɪɴɢ</b>

<b><a href="{0}">{1}</a></b>
<blockquote>{2} · requested by {3}</blockquote>
```

```html
⚠️ That didn't work. Try again in a moment.
<code>{0}</code>
```

The first is `play_media`; the second is the ordinary-user form of `feedback_error_user` in `anony/locales/en.json`.

## Emoji rules

- Use emoji to identify a state or destination, not as decoration on every line.
- Use at most one leading status emoji in routine feedback:
  - `✅` success;
  - `ℹ️` neutral information or an empty state;
  - `⚠️` recoverable warning or error;
  - `⏳` active work;
  - `🔒` or `🔐` restricted access;
  - `🎵` music action or result.
- Use the same emoji for the same meaning throughout a flow.
- Every custom emoji must contain a meaningful Unicode fallback:

```html
<tg-emoji emoji-id="5467383519724446667">⏸️</tg-emoji>
```

- Keep the custom emoji tag directly in the localized string. Do not create a separate symbol-to-ID map.
- In an inline button, a leading custom emoji tag may become `icon_custom_emoji_id`. If Telegram rejects it, the visible Unicode fallback must remain.
- Symbol-only playback controls are the exception to descriptive button labels. Their current meanings are:
  - `♾️` repeat;
  - `⏹️` stop;
  - `⏸️` pause;
  - `▶️` resume;
  - `⏭️` skip;
  - `🔄` replay.
- Do not depend on custom emoji for meaning. The fallback text, surrounding message, and button position must keep the action understandable.

## Heading format

- Use one short bold heading in title case or a compact branded style already present in the locale.
- Put the heading on the first line.
- Put the explanation or content after one blank line.
- Do not add punctuation to a standalone heading.
- Avoid stacking a heading, subheading, and repeated explanatory sentence.

Examples:

```html
🎵 <b>𝗪𝗵𝗮𝘁 𝘄𝗼𝘂𝗹𝗱 𝘆𝗼𝘂 𝗹𝗶𝗸𝗲 𝘁𝗼 𝗱𝗼?</b>

Choose a section below.
```

```html
🌐 <b>𝗖𝗵𝗼𝗼𝘀𝗲 𝗮 𝗹𝗮𝗻𝗴𝘂𝗮𝗴𝗲</b>
```

Help category pages use a descriptive heading followed by command entries:

```html
<b>Commands in the 🎵 Music category:</b>

/play — <i>Plays a song or YouTube link in the group call.</i>
<code>/play &lt;song or link&gt; or reply with /play</code>
```

## Menu message format

- A menu message names the current destination and gives one short instruction.
- Put choices in the inline keyboard rather than repeating them in the message.
- A detail menu may show a compact summary before its actions, such as assistant totals or group settings.
- Public menus use friendly language. Sudo menus may include IDs, connection state, and operational detail.
- The Start menu is a launcher. Its photo/caption and original keyboard remain unchanged when a destination opens as a new message.
- Menus opened from a plain text menu should normally replace that message through `navigate()` in `anony/helpers/_navigation.py`.
- Group-specific configuration must open in private through a deep link such as:

```text
https://t.me/{bot_username}?start=settings_{chat_id}
```

Current examples are Start (`start()` in `anony/plugins/start.py`), Help (`_help()`), Settings (`open_group_settings()`), assistant sessions (`_dashboard()` in `anony/plugins/sessions.py`), and runtime configuration (`_runtime_view()` in `anony/plugins/runtime_config.py`).

## Inline keyboard patterns

- Build shared keyboards in `Inline` in `anony/helpers/_inline.py`; do not duplicate common layouts in handlers.
- Prefer one to three buttons per row for named actions.
- Use a five-button row only for the established symbol-only playback controls.
- Put a full-width primary journey action on its own row. Start currently does this for **Add me to your group**.
- Put related choices on the same row: Help/Language/Stats, Support/Channel, or confirm/cancel.
- Use URL buttons for external destinations and private deep links. Use callback buttons for actions that the bot can complete in the current conversation.
- A label-only settings column may use a no-op callback paired with a value/action button, as in `settings_markup()`.
- Preserve native button styles when rebuilding a keyboard after a custom-emoji failure.
- Use red/danger only where the current product convention explicitly calls for it. Destructive confirmations must always be red. Most navigation and neutral controls remain default/colorless.
- Do not add Close buttons. A completed view either remains useful, navigates back, or has its keyboard removed/replaced.

Established layouts:

```text
[ Add me to your group ]
[ Help ] [ Language ] [ Stats ]
[ Trending ]
[ Support ] [ Channel ]
[ Owner ]
```

```text
[ ♾️ ] [ ⏹️ ] [ ⏸️/▶️ ] [ ⏭️ ] [ 🔄 ]
```

```text
[ Setting name ] [ Current value ]
[ Setting name ] [ Current value ]
```

## Reply keyboard patterns

- Do not use persistent `ReplyKeyboardMarkup` or `KeyboardButton` menus. The bot currently has no persistent reply keyboard.
- Use `ForceReply` only when free-form input is required and an inline choice cannot supply it.
- A ForceReply prompt must be associated with:
  - the initiating user;
  - the prompt message ID;
  - the expected stage;
  - an expiry time.
- Ignore replies from other users and unrelated replies.
- Delete sensitive replies, such as session strings, login codes, passwords, and phone numbers, as soon as they are consumed.
- Replace a ForceReply prompt by sending a new ForceReply message; editing an old prompt does not reactivate Telegram's reply UI.
- Remove the old prompt when a stage advances or the flow is cancelled.

Examples are the `/song` input prompt in `anony/plugins/song.py` and the phone/session-string login flow in `anony/plugins/sessions.py`.

## Button label rules

- Use a short verb or destination noun: **Help**, **Language**, **Stats**, **Check again**, **Add assistant**, **Remove**.
- Prefer two to four words. Do not place explanations or technical state dumps in labels.
- Use sentence case unless the label is a proper name.
- Make destructive labels explicit: **Remove permanently** is clearer than **Yes**.
- The non-destructive alternative names the safe outcome: **Keep session**, not **No**.
- Use one leading emoji only when it improves scanning. Do not mix leading and trailing decorative emoji.
- A selected choice may use a trailing `✔️`, as in language selection.
- Symbol-only labels are reserved for familiar playback actions; every other action should be named.
- URL labels describe the destination, not the transport: **Owner**, **Support**, **Open settings**.
- Keep labels localized. Current hard-coded labels such as `Copy link` and `YouTube` in `yt_key()` are compatibility exceptions, not a pattern for new UI.

## Button ordering

Use a predictable reading and risk order:

1. current or most likely action;
2. alternative actions;
3. navigation;
4. destructive action, visually separated where possible.

Specific conventions:

- List choices left to right, then top to bottom.
- In Help, categories are arranged in rows of up to three by `help_markup()`.
- In language selection, choices are arranged two per row by `lang_markup()`.
- In playback, keep the fixed order: repeat, stop, pause/resume, skip, replay.
- In a destructive confirmation, put the destructive action first and the safe escape second:

```text
[ Remove permanently ] [ Keep session ]
```

- Place Back on its own final row when a submenu needs it.
- Place the Start menu’s Add-to-Group action first and external destinations last.

## Back, cancel, and home behavior

- **Back** returns exactly one level and edits the current menu message.
- **Home** returns to the root dashboard for the current private flow.
- **Cancel** ends an unfinished operation, releases temporary resources, deletes or replaces the active prompt, and gives a short acknowledgement.
- A destructive confirmation must always provide a non-destructive escape.
- Help category pages contain Back. The root Help menu does not.
- Group-language settings use Back to return to that group’s settings.
- Assistant and runtime configuration dashboards may use Home to return to the private Start destination.
- The Start launcher is not edited. Opening Help, Language, Stats, Trending, or another Start destination sends a new message where necessary; `navigate()` preserves a media launcher by doing this automatically.
- Do not create Back buttons that jump across unrelated flows.
- Do not use Close as a substitute for Back or Cancel.

## Confirmation patterns

- Require confirmation for irreversible or high-impact state changes.
- The confirmation message must name the target and state the consequence.
- Use an explicit red destructive button and a clearly named safe alternative.
- Validate permission and target state again when the callback is pressed; do not trust the earlier screen.
- Answer expired or unauthorized confirmations with a callback alert or toast and leave state unchanged.
- Remove or replace the confirmation keyboard after completion so it cannot be submitted twice.

Repository example: permanent assistant removal in `_remove_confirmation()` and `_session_callback()` in `anony/plugins/sessions.py`.

Immediate controls such as playback Stop intentionally do not require confirmation. They should update the existing playback card at once and remove obsolete controls.

## Success, error, warning, and processing patterns

### Success

- Lead with `✅` when a visible confirmation is useful.
- State the completed result, not the internal operation.
- Prefer a callback toast for a minor setting change.
- When clean feedback is enabled, minor confirmations may be removed after 8 seconds through `Feedback.keep_or_clean()`.

Examples:

```text
✅ Admin list refreshed.
```

```text
✅ Repeating this track 2 more time(s).
```

### Information and empty states

- Lead with `ℹ️` for a neutral condition.
- Say what is true now; include the next action only when one is available.

Examples:

```text
ℹ️ Nothing is playing right now.
```

```text
ℹ️ No extra users have playback access.
```

### Warning and recoverable error

- Lead with `⚠️`.
- Explain the problem in user terms and give a direct recovery action.
- Do not expose exception names, library names, tracebacks, peer IDs, or database terminology to ordinary users.
- Keep actionable errors, setup guidance, and permission guidance visible. Routine errors may be removed after 20 seconds when clean feedback is enabled.

Examples:

```text
⚠️ Start a video chat, then try again.
```

```text
⚠️ Let me invite users, then try again.
```

### Sudo error

- Start with the same concise result, then include a reference, action, exception type, and expandable details.
- Use `<code>` and `<blockquote expandable>` for technical data.
- Never send sudo detail to a non-sudo user.

The centralized user/sudo split is implemented by `Language.language()` in `anony/core/lang.py` with `feedback_error_user` and `feedback_error_sudo`.

### Processing

- Use `⏳` plus a present-participle action when waiting is meaningful: **Loading the queue…**, **Preparing the application log…**.
- Prefer editing one status message through its stages rather than sending a message per stage.
- Do not simulate progress or stream partial prose.
- Replace the processing message with the result, or delete it after sending the final media.
- If processing can be cancelled, show one red Cancel button tied to that task.

The `/song` flow edits **Searching** → **Downloading** → **Uploading**, sends the audio, then deletes the status message.

## Callback-data conventions

- Use lowercase ASCII tokens separated by one space.
- The first token is a stable feature namespace; the second is an action.
- Put identifiers after the action, from broadest scope to narrowest scope.
- Preferred shapes:

```text
<feature> <action> [chat_id] [item_id|page|context]
```

Repository examples:

```text
controls pause -1001234567890
controls force -1001234567890 7f5a...
settings -1001234567890 language
settings_lang -1001234567890 my
session remove 2
stats refresh
help play
```

- Keep callback data within Telegram's size limit; store large or sensitive state server-side.
- Never put phone numbers, passwords, session strings, URLs, or localized text in callback data.
- Parse an exact token count or a documented optional suffix. Reject malformed and stale callbacks gracefully.
- Anchor callback filters to the complete namespace where the framework permits it.
- Validate the pressing user, chat, permissions, and target state in the callback handler.
- Use a callback toast for a small result; use an alert when the user must stop and read it.
- Treat current single-token callbacks such as `cancel_dl` and `language` as established compatibility forms. New multi-action features should use the namespaced shape above.
- Callback names are compatibility contracts. Do not rename or reorder existing tokens without retaining old handlers.

## Message editing rules

- Edit the current message when the user remains in the same flow: category navigation, settings toggles, language choices, playback state, setup recheck, and status progress.
- Send a new message when:
  - preserving the Start media launcher;
  - Telegram cannot edit the existing media type into the required result;
  - a new ForceReply prompt is required;
  - the result is a distinct artifact such as audio, document, or generated statistics photo.
- Prefer editing a caption when the current view is media and the result remains a media view.
- Prefer editing text when the current view is text.
- If an edit fails because the original message is gone or incompatible, send one replacement instead of silently abandoning the flow.
- On playback skip or replay, delete the obsolete playback card before presenting its replacement.
- On Stop, keep the final status visible but replace the active keyboard with a status-only or empty keyboard.
- On menu navigation, replacing the markup removes the old actions. Do not leave stale keyboards unless the message is intentionally a permanent launcher.
- If a callback has expired, answer it consistently and prevent further state changes.

Central navigation behavior is in `navigate()` in `anony/helpers/_navigation.py`. Playback card replacement is handled in `_controls()` in `anony/plugins/callbacks.py` and `_show_play_card()` in `anony/core/calls.py`.

## Media and caption conventions

- Use media only when it adds recognition or summarizes information better than text.
- Keep the caption useful without requiring the image to be read.
- The Start screen uses configured artwork; if none is configured, it may use the generated statistics image, then the default thumbnail.
- `/stats` sends a generated chart image with a complete text summary in its caption and a Refresh button.
- `/song` sends Telegram-playable audio with source metadata and a thumbnail where available.
- Playback and queue views may use artwork, but must fall back to a text message if Telegram rejects the media.
- Insufficient group permissions may include `assets/admin_permissions.png` together with concise instructions.
- Use one media item per primary result. Do not send decorative media for routine success or error feedback.
- Keep captions within Telegram limits. Move lengthy technical detail to a document or a separate expandable text report.
- Escape dynamic caption values exactly as message values are escaped.
- When refreshing generated media, edit the existing media and retain the keyboard rather than posting duplicates.

Relevant implementations are `_start_artwork()` in `anony/plugins/start.py`, `_stats()` and `_stats_refresh()` in `anony/plugins/stats.py`, `_deliver_song()` in `anony/plugins/song.py`, and `_new_member()` in `anony/plugins/start.py`.

## Conversation flow rules

- Every flow must have a clear entry, current state, completion, cancellation path where appropriate, and expiry behavior.
- Keep ordinary command flows stateless when one command or callback is enough.
- Use stored conversational state only for multi-step input such as assistant login and `/song` ForceReply.
- Bind state to the initiating user and prompt. In group chats, never let another member advance someone else's flow.
- Validate at every transition; do not advance the stage on invalid input.
- Give immediate waiting feedback before network or download work.
- For recoverable input errors, explain the expected input and keep or replace the prompt.
- Expire temporary state and disconnect temporary clients. Tell the user to start again when an expired prompt receives a reply.
- Delete secrets immediately and never echo them in status messages, logs, buttons, or callback data.
- Complete a flow by replacing/removing its active keyboard and clearing its stored state.
- Use private chat for account sessions, runtime configuration, language selection launched from private Start, and group settings. In a group, send a private deep-link button rather than running sensitive configuration there.
- Permission checks occur before actions and again at callback time. Ordinary users receive concise guidance; sudo users may receive diagnostic detail.
- Preserve command compatibility. Aliases may remain callable even when only the primary command appears in Telegram's command menu.
- Register public commands globally and sudo commands only in the relevant user scope during startup (`boot()` and `register_sudo_commands()` in `anony/core/bot.py`).

### Standard one-step flow

```text
command → validate → processing edit (if needed) → result → cleanup
```

Example: `/queue` sends **Loading the queue…**, then replaces it with the queue view or the localized empty state.

### Standard button menu flow

```text
launcher → submenu → detail/action → toast or edited result → Back/Home
```

Example: private Start → Help → Music category → Back to Help.

### Standard sensitive input flow

```text
private entry → method choice → ForceReply prompt → validate and delete reply
→ next prompt/status → complete or Cancel/expiry → clear state
```

Example: assistant addition in `anony/plugins/sessions.py`: method → phone or session string → login code → optional two-step password → activation → refreshed dashboard.

## Shared implementation points

New UI should reuse these central layers:

- `anony/core/lang.py`: locale loading, English fallback, command wrapper, and user/sudo error separation.
- `anony/core/custom_emoji.py`: capability state, tagged-text fallback, and custom-emoji button construction.
- `anony/core/bot.py`: HTML parse mode and centralized send/edit custom-emoji retry behavior.
- `anony/helpers/_inline.py`: shared inline keyboard layouts.
- `anony/helpers/_feedback.py`: concise sends/edits, callback toasts, and cleanup timing.
- `anony/helpers/_navigation.py`: edit-in-place navigation while preserving media launchers.
- `anony/plugins/callbacks.py`: playback, Help, and Settings callback transitions.
- `anony/plugins/sessions.py`: confirmation and multi-stage sensitive-input patterns.

Do not introduce a handler-local formatting, emoji fallback, or navigation convention when one of these shared layers already owns it.
