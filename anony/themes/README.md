# AnonXMusic themes

Themes are versioned, data-only JSON documents. They never contain Python,
credentials, assistant sessions, database paths, or arbitrary local paths.

Use `/themes` in a private chat as a sudo user to browse, clone, activate,
import, export, rename, or delete themes. Built-in themes are read-only.

## Minimal document

```json
{
  "$schema": "./theme.schema.json",
  "schema_version": 2,
  "id": "midnight",
  "name": "Midnight",
  "description": "A compact dark presentation.",
  "author": "Example",
  "version": "1.0.0",
  "config": {},
  "ui": {},
  "locales": {}
}
```

Missing values inherit application/environment defaults. They never inherit
from the previously active theme.

`$schema` enables validation and completion in JSON-aware editors. It is a
portable reference relative to the theme document; `schema_version` remains
the runtime migration and compatibility version. New schema-2 themes should
include both fields. Legacy schema-1 themes remain importable without the
reference.


## Configuration

`config` accepts the same safe keys shown by `/config`, using JSON-native
values:

- Limits are integers. `duration_limit` is measured in minutes.
- Switches such as `auto_end` are booleans.
- Disabled optional values use `null`.
- `play_controls_layout` is an array of rows, for example
  `[["pause", "skip"], ["stop"]]`.
- Templates, links, labels, language codes, and media references are strings.
- Media may be an HTTPS URL or Telegram file ID. Runtime themes cannot use
  local filesystem paths.

## Presentation

`ui` supports:

```json
{
  "heading_font": "small_caps",
  "icons": true,
  "heading_alignment": "center",
  "separators": true,
  "media_placement": "automatic",
  "tables": {
    "bordered": null,
    "striped": null,
    "header_alignment": null,
    "value_alignment": null
  },
  "surfaces": {
    "play": {
      "heading_level": 1,
      "heading_alignment": "left",
      "icon": "🎵",
      "media_placement": "after_heading"
    }
  },
  "keyboards": {
    "start_private": [
      ["add"],
      ["help", "language", "stats"],
      ["trending"],
      ["support", "channel"],
      ["owner"]
    ]
  }
}
```

Table values set to `null` preserve the surface formatter's native choice.
Keyboard layouts can reorder registered actions but cannot invent callbacks or
remove required actions.


## Emoji registry

Schema 2 themes can reuse semantic emoji tokens across registered UI slots:

```json
{
  "ui": {
    "emojis": {
      "mode": "custom",
      "registry": {
        "music": {
          "native": "🎵",
          "custom_emoji_id": "5409194048667807708",
          "hidden": false
        }
      },
      "placements": {
        "headings": {"play": "music"},
        "buttons": {"help.play": "music"}
      }
    }
  }
}
```

`mode` is `native`, `custom`, or `none`. Every token requires one Unicode
emoji; the decimal Telegram custom-emoji ID is optional. Placements may only
use registered heading surfaces, localized status keys, keyboard action IDs,
or rank positions. Use `null` to explicitly suppress an inherited or legacy
icon at one placement.

Custom emoji rejected by Telegram are removed on retry rather than replaced
with their Unicode token. Telegram may still show the mandatory alternative
emoji on clients that cannot display a successfully delivered custom emoji.
Schema 1 themes remain importable and are normalized to schema 2 on export.
## Locale overrides

`locales` may override registered English or Burmese keys:

```json
{
  "locales": {
    "en": {
      "heading_welcome": "Hello"
    }
  }
}
```

An override must preserve exactly the placeholders used by its base locale
value. This prevents an imported theme from causing runtime formatting errors.

Exported themes contain every effective safe configuration value and can be
imported into another deployment with `/importtheme`.
