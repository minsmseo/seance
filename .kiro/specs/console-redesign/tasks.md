# Implementation Plan: console-redesign

## Overview

The plan adds the optional `healthy` point field first, because the console needs it, then rebuilds the console in layers: static shell and stylesheet, tiles and formatting, summary strip, Ledger, tool panel. Tests for the design rules come last. Each layer leaves the console working, with no orphaned code.

Constraints that apply to every task:

- Never run the full pytest suite locally. GitHub Actions is the source of truth. Locally run `uv run ruff check .`, `uv run ruff format .`, and at most one targeted pytest file, once. Never retry after WinError 10014.
- Run each command directly, one per call. No `;` chaining and no output redirected to a file.
- Do not change `skeleton/seance/guard.py`, `skeleton/seance/audit.py`, `skeleton/seance/adapter.py` or any `apps/*/adapter.py`. The audit format and the `/audit` response fields stay as they are, except the additive `source` field in task 12.4.
- Source files and documents are UTF-8 and ASCII only. The degree sign reaches the page only through the Formatter, written in `console.js` as the escape `"\u00b0"`, or as the HTML entity `&deg;` (Requirement 6.11).
- `console.js`, `console.css` and the HTML shell contain no point name and no device name, including in comments. Describe behavior by unit and value type instead (Requirements 6.13, 10.8).
- Tests use `Fake_Adapter` and the shared `session_portal` fixture. No test creates an event loop of its own and no test makes a network call.
- Edit only the files allowed by Requirement 10.5.

## Tasks

- [x] 1. Add the optional `healthy` field to the configuration
  - [x] 1.1 Add `healthy` to `PointConfig` in `skeleton/seance/points.py`
    - Append `healthy: str | None = None` as the last field, so existing positional construction keeps working.
    - _Requirements: 1.1, 10.5_
  - [x] 1.2 Parse and validate `healthy` in `_load_point` in `skeleton/seance/config.py`
    - Run the check after `labels` is resolved. Accept the key only when it is non-empty text, `labels` is set, and the text is one of the label values.
    - Raise `ConfigError` naming the file, the device and `points[<name>].healthy`. The "not one of the labels" error lists the allowed label texts.
    - A point with no `healthy` key loads exactly as before.
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 1.8_
  - [x] 1.3 Emit `healthy` in `dump_config`
    - Write the key after `labels`, only when the value is not `None`.
    - _Requirements: 1.7, 1.8_
  - [x] 1.4 Add `healthy: up` and `healthy: normal` to `apps/snmp/devices.yaml`
    - Add `healthy: up` to `port1_status`, `port2_status`, `port3_status`, `port4_status` and `wan_link_status`.
    - Add `healthy: normal` to `on_battery`.
    - Change no other line and touch no other file under `apps/`. Do not edit `apps/modbus/devices.yaml`.
    - _Requirements: 2.1, 2.2, 2.4_
  - [x] 1.5 Write example tests in `skeleton/tests/test_config.py`
    - One test per `ConfigError` case: `healthy` not non-empty text (empty string, number), `healthy` without `labels`, `healthy` not among the label values. Assert the message names the file, the device and `points[<name>].healthy`, and for the last case lists the allowed texts.
    - A test that a point with `healthy` loads with the value stored, and that a point without it loads with `None`.
    - A readable `dump_config` then `load_config` round-trip example with a `healthy` field.
    - A test that `load_config` reads `apps/snmp/devices.yaml` without error and that the six named points carry the expected `healthy` text.
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.9, 2.1, 2.2, 2.3_
  - [x] 1.6 Write the Hypothesis round-trip test in `skeleton/tests/test_config_properties.py`
    - **Property 4: Healthy-field round trip**
    - Extend the `_points()` strategy: when `labels` is drawn, draw `healthy` as `None` or one of the drawn label texts. When `labels` is `None`, `healthy` is `None`.
    - Add `test_config_round_trip_with_healthy`, tagged `Feature: console-redesign, Property 4`, with at least 100 examples. Reuse the structure of the existing round-trip test. Create no event loop.
    - **Validates: Requirements 1.7, 1.8**
  - [x] 1.7 Run ruff and one targeted test file
    - Run `uv run ruff check .`, then `uv run ruff format .`, then `uv run pytest skeleton/tests/test_config.py` once.
    - _Requirements: 12.10_

- [x] 2. Checkpoint - Ensure the healthy field is correct
  - Ensure ruff is clean and the one targeted test file passed. Ask the user if questions arise.

- [x] 3. Build the static HTML shell, the CSS tokens and the `/config` route
  - [x] 3.1 Add `GET /config` and simplify `_index_html` in `skeleton/seance/console/app.py`
    - `GET /config` returns `{"devices": [{"name", "description", "points": [{"name", "unit", "healthy"}]}], "tools": [...]}` built from `server.config`, with `tools` taken from `READ_TOOLS`. Expose no `address`, `data_type`, `scale`, `decimals` or `labels`.
    - The route does not call the adapter and does not call `ToolServer.call`.
    - `_index_html` reads `templates/index.html` and returns it unchanged. It no longer walks the configuration or calls `read_points`.
    - Leave `GET /points/{device}/{point}`, `POST /tools/{tool_name}` and `GET /audit` untouched.
    - _Requirements: 3.12, 9.13, 10.1, 10.2, 10.8_
  - [x] 3.2 Rewrite `skeleton/seance/console/templates/index.html` as the static shell
    - Document order: header (wordmark `Seance` once, app name, chip `READ-ONLY, 5 TOOLS`, last-read time, `Read again` button), Summary_Strip, `<main>` with an empty `<div id="devices">` and the Tool_Panel markup, then the Ledger `<aside>`.
    - Tool_Panel: heading `Call a tool yourself`, three labelled `select` elements (tool, device, point), a `Send` button and an output area for the raw reply. No textarea.
    - Load Fraunces, Inter and JetBrains Mono from Google Fonts with `display=swap`, then `console.css`, then `console.js` at the end of `<body>`.
    - Headings and buttons use sentence case and no parentheses. The only theme words are `Seance` and `Ledger`. No emoji, no device or point names, no `data-device` attributes.
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.10, 3.11, 4.5, 4.7, 4.9, 9.3, 9.10, 10.8_
  - [x] 3.3 Rewrite `skeleton/seance/console/static/console.css` against the steering tokens
    - Define the nine tokens once on `:root` with the exact hex values from `.kiro/steering/design.md`. Use colors elsewhere only as `var(--token)`.
    - Radius 3px on every element that has one. No `box-shadow`, `text-shadow` or gradient.
    - Wordmark in Fraunces italic 500 at 30px, text in Inter 400/500/600, numbers, names, timestamps and code in JetBrains Mono. Every `font-family` ends with a system fallback.
    - Layout for header, Summary_Strip, main and Ledger columns, controls at least 44px tall, and the narrow rules at 390px (header wraps, Ledger below, tile grid two columns).
    - Define the tile rules now: grid `repeat(auto-fill, minmax(196px, 1fr))` with a 10px gap, one shared `.tile` rule with `height: 108px`, ellipsis clipping on tile lines, and the attention style (`--alert-ground` background, 2px `--alert` border, `--alert-ink` text). Nothing else sets a height on a tile or its content.
    - Check the text and surface pairs, including the 11px detail line, for 4.5:1 contrast.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.6, 4.8, 4.9, 4.10, 5.3, 5.4, 5.5, 5.9_
  - [x] 3.4 Create a minimal `skeleton/seance/console/static/console.js` entry point
    - Fetch `/config` and create one `<section>` per device inside `#devices` with an `h2` (device name), the description and an empty tile grid. Write all text with `textContent`.
    - Write `No devices are configured.` when the list is empty and `No points configured.` for a device with no points.
    - Contain no point names or device names, including in comments.
    - _Requirements: 3.5, 3.6, 3.7, 3.8, 3.9, 10.8_
  - [x] 3.5 Update the old tests in `skeleton/tests/test_console.py` that assert the removed server-rendered markup
    - `GET /` no longer embeds device sections or point values, so these four tests change. Keep each test's intent and move the assertion to the new data source.
    - `test_index_lists_devices_and_points_with_live_values` asserted that `GET /` contained device names, descriptions, point names and the value `10.0`. Change it to assert `GET /config` lists both devices and the points `temperature` and `running`, and that `POST /tools/read_points` for `press` returns the value `10.0` (100 * 0.1 from the fake bytes).
    - `test_index_keeps_device_names_readable_after_escaping` asserted `&lt;main&gt;` in the HTML. Change it to assert that `GET /` contains neither `ODD_NAME` nor its escaped form (the shell is name-free), and that `GET /config` returns `ODD_NAME` and `Odd & <unusual> name` as exact JSON strings.
    - `test_index_shows_adapter_error_sentence_unchanged` asserted the error sentence in the HTML. Change it to call `POST /tools/read_points` with the error adapter and assert the same sentence appears in the JSON reply, and that neither `boom` nor `Traceback` appears.
    - `test_index_writes_one_audit_entry_per_device_with_points` asserted that `GET /` wrote one audit entry per device with points. Change it to assert that `GET /` and `GET /config` write no audit entry, since neither calls `ToolServer.call`.
    - Leave unchanged: `test_point_route_returns_live_value`, `test_point_route_unknown_point_returns_sentence_unchanged`, `test_point_route_handles_device_name_with_special_characters`, `test_tool_invocation_returns_raw_result`, `test_tool_invocation_errors_are_plain_sentences`, `test_console_does_not_forward_write_requests_to_the_adapter`, `test_audit_is_empty_at_start`, `test_each_console_call_writes_one_audit_entry`, `test_audit_view_is_capped_at_50_newest_first`.
    - Add tests for the `GET /config` shape: `healthy` is `null` for a point without one and the configured text otherwise (add a point with `labels` and `healthy` to the test `CONFIG`, or build a second configuration), and `tools` lists the five read tools.
    - Record in the completion note exactly which tests changed and why.
    - _Requirements: 3.8, 10.1, 10.2, 10.8, 12.8, 12.9_
  - [x] 3.6 Run ruff and one targeted test file
    - Run `uv run ruff check .`, then `uv run ruff format .`, then `uv run pytest skeleton/tests/test_console.py` once.
    - _Requirements: 12.10_

- [x] 4. Add the app title, plain device descriptions and the device header row
  - [x] 4.1 Add the optional `title` field to the config, with validation and dump
    - Add `title: str | None = None` as the last field of `Configuration` in `skeleton/seance/points.py`.
    - In `load_config` in `skeleton/seance/config.py`, read the top-level `title`. Absent or null gives `None`. Otherwise it must be non-empty text of at most 40 characters. Raise `ConfigError(file, "", "title", reason)` for empty text, a value that is not text (including numbers and booleans), and text longer than 40 characters.
    - In `dump_config`, write `title` only when it is not `None`.
    - Keep the skeleton generic: no protocol word in the field, the messages or the comments.
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 10.5_
  - [x] 4.2 Write the title tests in `skeleton/tests/test_config.py` and `skeleton/tests/test_config_properties.py`
    - Example tests in `test_config.py`: a valid title is stored, an absent title loads as `None`, an empty title, a non-text title and a 41-character title each raise `ConfigError` that names the file and the field `title`, a 40-character title loads, and a `dump_config` then `load_config` round trip with a title keeps it.
    - Extend the Hypothesis configuration strategy in `test_config_properties.py` so `title` is `None` or non-empty text of 1 to 40 characters, and keep the round-trip test at 100 examples or more. Create no event loop.
    - _Requirements: 13.6, 13.15_
  - [x] 4.3 Return `title` from `GET /config` and show it in the header
    - In `skeleton/seance/console/app.py`, add `"title": server.config.title` to the `GET /config` response.
    - In `skeleton/seance/console/templates/index.html`, keep the header app-name element with the placeholder text `Read-only console`.
    - In `skeleton/seance/console/static/console.js`, after `/config` loads, set that element with `textContent` to the title when it is non-empty text. Leave the placeholder when the title is null.
    - Add tests in `skeleton/tests/test_console.py`: `GET /config` returns the title for a configuration with a title and `null` for one without, and the served `console.js` sets the app name from `title` while the shell still contains `Read-only console`.
    - _Requirements: 13.7, 13.8, 13.9, 13.15, 10.8_
  - [x] 4.4 Set the titles and plain descriptions in both `devices.yaml` files
    - Add `title: "SNMP network gear"` to `apps/snmp/devices.yaml` and `title: "Modbus factory line"` to `apps/modbus/devices.yaml`.
    - Remove the parenthetical part from every device description in both files, for example `Core switch with four ports and an uplink`.
    - Search `apps/*/tests/`, `apps/*/README.md`, `README.md` and `skeleton/tests/` for the old description text and update every quote to the new text. Change no other line.
    - Do not edit `apps/modbus/adapter.py`, `apps/modbus/simulator.py` or any Modbus test that does not quote an old description.
    - Add a test in `skeleton/tests/test_config.py` that `load_config` reads both files and that each loaded title equals the text above and no description contains `(`.
    - _Requirements: 13.10, 13.11, 10.5, 2.4_
  - [x] 4.5 Build the device header row in `console.css` and `console.js`
    - In `console.js`, create for each device section one `div.device-head` that holds the `h2` with the device name, a `p` with the description and a `p` with the health text, all written with `textContent`. Create the health text element empty in this row. Task 5.2 fills it.
    - In `console.css`, make `.device-head` a wrapping flex row with the name and description on the left and the health text at the right end (`margin-left: auto`), and put the section rule on the bottom edge of the row. At 390px the items wrap with no clipping and no horizontal scroll. Use only Steering_Tokens and keep the controls rules from task 3.3.
    - Add no device name or point name to `console.js`, `console.css` or the shell, including in comments. Add a test in `skeleton/tests/test_console.py` that the served `console.js` creates the `device-head` row and that `console.css` defines it with wrapping.
    - _Requirements: 13.12, 13.13, 13.14, 3.5, 4.2, 4.10, 10.8_
  - [x] 4.6 Run ruff only
    - Run `uv run ruff check .`, then `uv run ruff format .`. Do not run pytest; GitHub Actions verifies the tests.
    - _Requirements: 12.10_

- [x] 5. Render tiles and the Formatter in `console.js`
  - [x] 5.1 Add the pure Formatter functions
    - `formatSeconds`, `formatBytes`, `formatBoolean`, `formatLabeled`, `formatUnit`, `formatTimestamp`. Each takes plain values and returns plain strings or small objects, with no DOM access.
    - Seconds: a value of 60 or more is a duration with each part rounded down: `<d>d <h>h <m>m` from one day, `<h>h <m>m` from one hour (for example `5400` shows `1h 30m`), `<m>m <s>s` below one hour (`270` shows `4m 30s`). The detail line is the raw value with a thousands separator and `s` (`86427.5` shows `1d 0h 0m` with `86,427.5 s`). A value below 60 shows as plain seconds (`42.5 s`) with the time of the read as detail.
    - Bytes: decimal kB, MB, GB, TB with two decimals, raw byte count with a thousands separator as detail (`5010152941` shows `5.01 GB`).
    - Booleans: `on` or `off`, with the time of the read as detail. Labeled integers: the label as value, detail `raw <integer>` and the time of the read.
    - Units: `degC` to `"\u00b0C"`, `percent` to `%`, `state` to no unit, any other unit as received.
    - Timestamps: local `HH:MM:SS` with the full ISO text kept for the `title`. An unparseable timestamp is shown unchanged.
    - Choose every format from the unit and the value type only. No function takes or inspects a point name, device name or description. Never change the sign of a number.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.10, 6.11, 6.12, 6.13_
  - [x] 5.2 Add `renderTile` and tile filling in `console.js`
    - `renderTile` builds one three-line tile (name, value with unit, detail) with `textContent`. Lines clip with an ellipsis through the CSS from task 3.3.
    - A failed read gives an Attention_Tile: warning triangle, short error sentence in the detail line, full sentence in `title`. A point with a healthy text whose returned label differs gives an Attention_Tile showing the label. A point with no healthy text and a successful read is a normal tile.
    - Fetch `/config`, then issue one `/tools/read_points` call per device so each call writes one audit entry. Fill each device section's grid with one tile per configured point in configuration order, and fill the device health text.
    - Expose a single `refreshAll()` that the first page load and `Read again` will both use, and keep the tiles on screen during a re-read.
    - _Requirements: 3.5, 3.8, 3.9, 5.1, 5.2, 5.6, 5.7, 5.8, 5.9, 5.10, 10.1_
  - [x] 5.3 Run ruff and one targeted test file
    - Run `uv run ruff check .`, then `uv run ruff format .`, then `uv run pytest skeleton/tests/test_console.py` once.
    - _Requirements: 12.10_
  - [x] 5.4 Update the app integration tests that assert the old server-rendered markup
    - GitHub Actions fails `test_console_shows_three_devices_with_live_values_within_five_seconds` in `apps/modbus/tests/test_server_integration.py` and `apps/snmp/tests/test_server_integration.py`. Both assert device names in the HTML of `GET /`, which is now a static shell.
    - Keep the check that `GET /` returns 200 within five seconds. Move the device-name check to `GET /config` and the live-value check to the route that returns point values (`GET /points/{device}/{point}` or `POST /tools/read_points`).
    - Change only these two tests. Do not change any source file under `apps/`.
    - Run `uv run ruff check .`, then `uv run ruff format .`. Do not run pytest.
    - _Requirements: 10.1, 10.5, 12.8_

- [x] 6. Add the summary strip
  - [x] 6.1 Add `renderSummaryStrip` to `console.js` and wire it into `refreshAll()`
    - Show devices answering out of configured devices, and points read out of configured points. A device answers when at least one point read succeeded, or when it has no points and raised no error. A device whose every point fails does not answer.
    - Add one Attention_Chip per Attention_Tile, in tile order. Each chip names the device and the point and states the returned label or the failed read. No chip when nothing is wrong. Chips use the attention style from task 3.3.
    - Build the chip list from the same list that marks tiles, so the chip count always equals the attention tile count.
    - Activating a chip (a real `button`) moves focus to the matching tile, which is made focusable.
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8_
  - [x] 6.2 Run ruff and one targeted test file
    - Run `uv run ruff check .`, then `uv run ruff format .`, then `uv run pytest skeleton/tests/test_console.py` once.
    - _Requirements: 12.10_

- [x] 7. Add the Ledger with a 2 second refresh
  - [x] 7.1 Add the reason sentences and `renderLedgerRows` to `console.js`
    - `reasonSentence(outcome)` is a lookup table with one plain sentence each for `rejected`, `unknown_tool`, `unknown_target`, `invalid_argument`, `timeout` and `adapter_error`, and a generic sentence for any other outcome. Each says what failed and what to try next.
    - `renderLedgerRows(entries)` replaces the row container with one row per entry, in the order received, with no merge and no reordering. Each row shows the tool name, the target (device, then point when present), the outcome and the local `HH:MM:SS` time with the full ISO value in `title`. A row whose outcome is not `ok` uses the attention style, the warning triangle and the reason sentence.
    - Show `No calls yet.` when the list is empty.
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.10_
  - [x] 7.2 Add `pollAudit()` and the timer
    - Fetch `/audit` every 2000 ms with `setInterval`, started once. Skip a tick while the previous request is pending, using an in-flight flag cleared in `finally`.
    - On failure keep the rows already shown and add the line `The ledger could not be loaded. It will try again in 2 seconds.`. Clear that line after the next success.
    - Expose a function that refreshes the Ledger once, at once, sharing the same in-flight guard, for use by the tool panel.
    - _Requirements: 8.7, 8.8, 8.9, 8.11, 9.12_
  - [x] 7.3 Run ruff and one targeted test file
    - Run `uv run ruff check .`, then `uv run ruff format .`, then `uv run pytest skeleton/tests/test_console.py` once.
    - _Requirements: 12.10_

- [x] 8. Add the tool panel and `Read again`
  - [x] 8.1 Wire `Read again` in `console.js`
    - Clicking the button calls `refreshAll()`, disables the button while the re-read runs, keeps the tiles on screen, then updates every tile, the summary strip and the last-read time in the header without reloading the page. Re-enable the button in `finally`.
    - Call `refreshAll()` once on page load.
    - _Requirements: 9.1, 9.2_
  - [x] 8.2 Build the tool panel selects in `console.js`
    - Fill the tool select from the `tools` array of `GET /config`. Fill the device select from the devices and refill the point select from the selected device whenever the device changes.
    - `updateSelectState`: `list_devices` disables the device and point selects; `list_points`, `read_points` and `device_health` enable the device select and disable the point select; `read_point` enables both.
    - _Requirements: 9.3, 9.4, 9.5, 9.6, 9.8, 9.10, 9.13_
  - [x] 8.3 Implement `sendTool` in `console.js`
    - Build the arguments from the selects. `read_points` sends the names of all points of the selected device as `points`. Post to `/tools/<tool>` and show the raw JSON reply, indented, with no display formatting.
    - When the request fails, show a sentence saying the console server did not answer and to check that it is running and try again.
    - After every send, refresh the Ledger at once with the function from task 7.2.
    - _Requirements: 9.7, 9.9, 9.11, 9.12_
  - [x] 8.4 Run ruff and one targeted test file
    - Run `uv run ruff check .`, then `uv run ruff format .`, then `uv run pytest skeleton/tests/test_console.py` once.
    - _Requirements: 12.10_

- [x] 9. Checkpoint - Ensure the console works end to end
  - Ensure ruff is clean and the one targeted test file passed. Check that `console.js` contains no point or device names, including comments. Ask the user if questions arise.

- [x] 10. Write the tests for the design rules in `skeleton/tests/test_console_design.py`
  - [x] 10.1 Page structure, `/config` and the section-per-device code path
    - Assert the shell served by `GET /` contains the header, Summary_Strip, `#devices` container, Ledger and Tool_Panel in document order, and that the served `console.js` fetches `/config` and creates one section per device.
    - Assert `GET /config` returns one entry per device for several configurations.
    - Use `Fake_Adapter` and the shared `session_portal` fixture, with no new event loop.
    - _Requirements: 3.1, 3.2, 3.3, 12.1, 12.9_
  - [x] 10.2 CSS rule tests
    - `:root` holds exactly the nine tokens with the steering hex values. No hex, `rgb`, `hsl` or named color outside `:root`; every color is `var(--token)` of a steering token.
    - No `box-shadow`, `text-shadow` or gradient function. Every `border-radius` is `3px`.
    - Every `font-family` list ends with a generic family. Exactly one rule block targeting `.tile` sets `height` (108px) and no other selector for a tile or its children sets `height`, `min-height` or `max-height`. The grid declaration and 10px gap are present.
    - _Requirements: 4.1, 4.2, 4.3, 4.6, 5.3, 5.4, 12.2, 12.3, 12.5, 12.6_
  - [x] 10.3 Shell text tests: parentheses, fonts, theme words, ASCII
    - No heading and no button text in the shell contains a parenthesis, and no heading or button text constant in `console.js` does.
    - The three Google Fonts links are present with `display=swap`. `Seance` appears once as the wordmark.
    - `index.html`, `console.css` and `console.js` are ASCII only, and `console.js` produces the degree sign only through the `\u00b0` escape.
    - _Requirements: 3.4, 3.10, 3.11, 4.5, 6.11, 10.6, 12.4, 12.7_
  - [x] 10.4 Name-free test over both apps
    - Load `apps/modbus/devices.yaml` and `apps/snmp/devices.yaml` with `load_config`. Build one `ToolServer` per file with `Fake_Adapter` on the shared session loop and request `GET /` for each. Request the served `console.js` once.
    - Collect every device and point name. Search each served HTML page and the `console.js` text for each name as a whole identifier, ignoring case, with the pattern `(?<![A-Za-z0-9_])<escaped name>(?![A-Za-z0-9_])`. Fail with the file, the name and where it was found. If a short common word is found, reword the comment in `console.js` instead of loosening the test.
    - _Requirements: 6.13, 10.8, 12.11_
  - [x] 10.5 Properties 1 to 3 as example tests, and Formatter source checks
    - **Property 1: One tile per configured point.** Representative configurations: no devices, a device with no points, a device with many points, points out of alphabetical order, names containing `&` and `<`. Assert against `GET /config` and the served `console.js` source as allowed by Requirement 11.4.
    - **Property 2: Attention chip count equals attention tile count.** Representative outcome sets: no failures, all failures, a healthy-label mismatch, a device whose every point fails. Assert that `console.js` builds tiles and chips from one shared list, and drive the read outcomes through `POST /tools/read_points`.
    - **Property 3 (console half): the Ledger keeps the order received.** Assert that `renderLedgerRows` in `console.js` replaces rows in one pass with no sort, no merge and no cap beyond what `/audit` returns, and that each outcome in Requirement 8.5 maps to a distinct non-empty sentence plus the generic one.
    - Formatter source checks: `formatSeconds` branches on the value being under 60 and contains the day, hour and minute forms (`1h 30m` shape); kB, MB, GB and TB cutoffs are present; no Formatter function takes a point name argument.
    - **Validates: Requirements 5.1, 7.3, 8.1, 8.2, 8.5, 11.1, 11.2, 11.3, 11.4**
    - _Requirements: 5.1, 6.1, 6.2, 6.12, 6.13, 7.3, 8.1, 8.2, 8.5, 11.4_
  - [x] 10.6 Hypothesis audit property in `skeleton/tests/test_audit_properties.py`
    - **Property 3 (audit half): the audit view is never longer than the log and is newest first.** Add `test_recent_never_exceeds_n_or_total_and_is_newest_first` over generated entry lists and `n`, tagged `Feature: console-redesign, Property 3`, with at least 100 examples. Skip adding it only if an equivalent test already exists in the file, and say so in the completion note.
    - Also add a Hypothesis check that the audit log contains exactly one entry per tool call, including failed calls, driven through `ToolServer.call` with `Fake_Adapter`. Reuse the session loop. Do not create an event loop per example.
    - **Validates: Requirements 8.1, 8.2, 11.3, 11.6**
  - [x] 10.7 Run ruff and one targeted test file
    - Run `uv run ruff check .`, then `uv run ruff format .`, then `uv run pytest skeleton/tests/test_console_design.py` once.
    - _Requirements: 12.10_

- [~] 11. Final checkpoint - Ensure all tests pass
  - Ensure ruff is clean. Confirm that GitHub Actions is the place where the full suite is checked, and that the completion note lists every changed test from task 3.5. Ask the user if questions arise.

- [x] 12. Refine the Ledger, tiles, call source and one SNMP point name
  - [x] 12.1 Format the Ledger target in `console.js` and `console.css`
    - When an audit entry names more than three points, show `<device>, <n> points` and put the full comma-separated list of point names in the `title` of the row.
    - Otherwise join the device name and the point names with `, `. Put each name in its own `span` with `white-space: nowrap` so that lines wrap only at the commas, never inside a name.
    - _Requirements: 14.1, 14.2_
  - [x] 12.2 Render the tile unit in its own element
    - In `renderTile` in `console.js`, write the unit into a separate element. In `console.css`, make it smaller than the value and colored `var(--mute)`.
    - Keep the Tile height at 108px, set in the one shared `.tile` rule and nowhere else.
    - _Requirements: 14.3, 5.4_
  - [x] 12.3 Separate detail-line parts with `, `
    - In the Formatter and `renderTile` in `console.js`, join the detail parts with `", "`, for example `raw 1, 21:56:19`.
    - _Requirements: 14.4_
  - [x] 12.4 Add the additive `source` field to the audit log
    - In `skeleton/seance/audit.py`, add `source: str = "agent"` as the last field of `AuditEntry` and record it. In `skeleton/seance/server.py`, add a keyword `source: str = "agent"` to `ToolServer.call` and pass it to the audit log. Change nothing else in these files, so existing callers keep working and each call still writes exactly one entry.
    - In `skeleton/seance/console/app.py`, pass `source="console"` from `POST /tools/{tool_name}`, `GET /points/{device}/{point}` and the `read_points` refresh calls, and return `source` in each `GET /audit` entry.
    - Update the audit tests and the one-entry-per-call property (`skeleton/tests/test_audit.py`, `skeleton/tests/test_audit_properties.py`) to cover `source`. Add tests that calls through the MCP path record `agent` and that console `POST /tools` calls, and the console's own `read_points` refresh calls, record `console`.
    - _Requirements: 14.5, 14.6, 14.7, 14.8, 10.3, 10.5_
  - [x] 12.5 Show the call source in each Ledger row
    - In `renderLedgerRows` in `console.js`, show the source word on each row. In `console.css`, color `agent` with `var(--ink)` and `console` with `var(--mute)`. Never use `--alert` or `--alert-ink` for the source.
    - _Requirements: 14.9_
  - [x] 12.6 Make the Ledger sticky beside the devices
    - In `console.css`, at the widths where the Ledger sits beside the devices, set `position: sticky` near the top, `overflow-y: auto` and a `max-height` such as `calc(100vh - <top offset>)`. Below that breakpoint the Ledger stays in normal flow under the devices.
    - _Requirements: 14.10, 14.11_
  - [x] 12.7 Rename the SNMP point `on_battery` to `power_source`
    - Change `apps/snmp/devices.yaml`, `apps/snmp/simulator.py` only if it carries the point name, the README table or tables (`apps/snmp/README.md` and `README.md`), and every test in `skeleton/tests/` and `apps/snmp/tests/` that names it. Keep the labels and `healthy: normal`.
    - Change neither `apps/snmp/adapter.py` nor any Modbus file.
    - _Requirements: 14.12, 2.2_
  - [x] 12.8 Update `.kiro/steering/design.md`
    - Record the rules that change: unit styling in tiles, the detail-line separator, the Ledger source colors, the Ledger target formatting and the sticky Ledger. ASCII only.
    - _Requirements: 14.13_
  - [x] 12.9 Write the tests in `skeleton/tests/test_console_design.py`
    - Add source and CSS checks for 12.1 to 12.3, 12.5 and 12.6. Extend the existing CSS rule tests where they would now reject the new rules legitimately, for example a `max-height` on the Ledger is not a tile rule.
    - In the completion note, record every changed test by name.
    - _Requirements: 14.14, 12.3_
  - [x] 12.10 Run ruff only
    - Run `uv run ruff check .`, then `uv run ruff format .`. Do not run pytest.
    - _Requirements: 12.10_

## Notes

- No task is optional. Every test sub-task is required by Requirement 12.
- Properties 1 to 3 are example tests because the logic runs in browser JavaScript (Requirement 11.4). Property 4 and the audit half of Property 3 use Hypothesis.
- Real-browser behavior (DOM order, locale time formatting, fetch timing) is not covered by the Python tests and needs a manual look at the checkpoints.
- Locally run only ruff and one targeted pytest file, once. Never run the full suite.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3", "1.4"] },
    { "id": 3, "tasks": ["1.5"] },
    { "id": 4, "tasks": ["1.6"] },
    { "id": 5, "tasks": ["1.7"] },
    { "id": 6, "tasks": ["2"] },
    { "id": 7, "tasks": ["3.1", "3.2", "3.3"] },
    { "id": 8, "tasks": ["3.4"] },
    { "id": 9, "tasks": ["3.5"] },
    { "id": 10, "tasks": ["3.6"] },
    { "id": 11, "tasks": ["4.1"] },
    { "id": 12, "tasks": ["4.2", "4.3"] },
    { "id": 13, "tasks": ["4.4"] },
    { "id": 14, "tasks": ["4.5"] },
    { "id": 15, "tasks": ["4.6"] },
    { "id": 16, "tasks": ["5.1"] },
    { "id": 17, "tasks": ["5.2"] },
    { "id": 18, "tasks": ["5.3"] },
    { "id": 19, "tasks": ["5.4"] },
    { "id": 20, "tasks": ["6.1"] },
    { "id": 21, "tasks": ["6.2"] },
    { "id": 22, "tasks": ["7.1"] },
    { "id": 23, "tasks": ["7.2"] },
    { "id": 24, "tasks": ["7.3"] },
    { "id": 25, "tasks": ["8.1"] },
    { "id": 26, "tasks": ["8.2"] },
    { "id": 27, "tasks": ["8.3"] },
    { "id": 28, "tasks": ["8.4"] },
    { "id": 29, "tasks": ["9"] },
    { "id": 30, "tasks": ["10.1"] },
    { "id": 31, "tasks": ["10.2", "10.3", "10.6"] },
    { "id": 32, "tasks": ["10.4"] },
    { "id": 33, "tasks": ["10.5"] },
    { "id": 34, "tasks": ["10.7"] },
    { "id": 35, "tasks": ["11"] },
    { "id": 36, "tasks": ["12.1", "12.4"] },
    { "id": 37, "tasks": ["12.2", "12.7"] },
    { "id": 38, "tasks": ["12.3"] },
    { "id": 39, "tasks": ["12.5"] },
    { "id": 40, "tasks": ["12.6"] },
    { "id": 41, "tasks": ["12.8", "12.9"] },
    { "id": 42, "tasks": ["12.10"] }
  ]
}
```
