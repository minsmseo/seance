# Design

The console is the only screen a person sees. It must read as a finished product, not a debug page. These rules apply to everything under `skeleton/seance/console/`.

## Direction

A control room at night, lit by one candle. Near-black warm ground, thin rules, monospace numbers. The single accent color is amber, and amber means "look here". Nothing is amber unless it needs attention.

## Tokens

Define these once as CSS custom properties on `:root` and use only the variables elsewhere.

| Token | Value | Use |
|---|---|---|
| `--ground` | `#0E0C0A` | page background, header, inputs |
| `--panel` | `#17130F` | tiles, ledger, tool panel |
| `--ink` | `#F4EDE1` | primary text, section rules, button fill |
| `--mute` | `#B3A592` | labels, units, secondary text |
| `--line` | `#2E2720` | tile borders, row separators |
| `--line-strong` | `#5A4E40` | input borders, header chip border |
| `--alert` | `#F08A24` | attention border, header underline |
| `--alert-ink` | `#FFB45C` | text on attention surfaces |
| `--alert-ground` | `#2B1806` | attention surface background |

Radius is 3px everywhere. No shadows, no gradients, no glow, no emoji, no icons other than one warning triangle on attention tiles.

## Type

- Wordmark: Fraunces italic 500, 30px, the word `Seance` in title case. Used once, in the header.
- Text: Inter 400, 500 and 600.
- Numbers, point names, tool names, timestamps and code: JetBrains Mono.
- Load the three families from Google Fonts with `display=swap`, and give every `font-family` a system fallback so the page works offline.

## Layout

1. Header: wordmark, app name, a `READ-ONLY, 5 TOOLS` chip, the time of the last read and a `Read again` button.
2. Summary strip: devices answering, points read, and one attention chip per problem. No attention chip when nothing is wrong.
3. Main column: one section per device. Device name in mono, description, health text, then a grid of point tiles.
4. Right column: the Ledger. Newest call first. On narrow screens it moves below the devices.
   - Beside the devices the Ledger is sticky near the top of the viewport, its height fits the viewport (`calc(100vh - offset)`) and it scrolls on its own. Below the devices it is in normal flow, with no own scroll.
   - Each row shows the source word: `agent` in `--ink`, `console` in `--mute`. Source never uses an alert color.
   - A call that names more than three points shows `<device>, <n> points`, with the full list in the row `title`. Otherwise device and point names are joined with `, `, each name on one line, so lines wrap only at the commas.
5. Below the devices: `Call a tool yourself`, with selects for tool, device and point, a `Send` button and the raw reply.

## Tiles

- Every point tile is exactly the same size: 108px tall, in a grid of `repeat(auto-fill, minmax(196px, 1fr))` with a 10px gap. Never let content change a tile's height.
- A tile shows three lines: the point name, the value with its unit, and one small line of detail.
- The unit sits in its own element next to the value, smaller than the value and in `--mute`.
- A tile needs attention when its label is not the healthy one (for example `down`) or when the read failed. An attention tile uses `--alert-ground`, a 2px `--alert` border, `--alert-ink` text and the warning triangle. State is never shown by color alone.

## Display formatting

Formatting happens in the console only. Tool results sent to agents keep their raw values.

| Kind | Raw | Shown | Detail line |
|---|---|---|---|
| seconds of uptime | `86427.5 s` | `1d 0h 0m` | `86,427.5 s` |
| bytes | `5010152941 B` | `5.01 GB` | `5,010,152,941 B` |
| boolean | `true` | `on` or `yes` | time of read |
| labeled integer | `2` | `down` | `raw 2, <time>` |
| unit `degC` | | `°C` | |
| unit `percent` | | `%` | |
| unit `state` | | no unit shown | |
| timestamp | ISO 8601 UTC | local `HH:MM:SS` | full ISO value in `title` |

Parts of a detail line are separated with `, `.

## Copy

- Plain labels. No parentheses that explain a label, no theme words on controls.
- The theme lives in two words only: `Seance` and `Ledger`.
- Sentence case for headings and buttons.

## Accessibility

- Text contrast at least 4.5:1, including the 11px detail lines.
- Real `button`, `select`, `label` and `a` elements. Every control is reachable by keyboard and at least 44px tall.
- The page must be usable at 390px wide: the header wraps, the Ledger moves below, the tile grid drops to two columns.
