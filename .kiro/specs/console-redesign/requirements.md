# Requirements Document

## Introduction

This feature rebuilds the web console in `skeleton/seance/console/` so that it follows `.kiro/steering/design.md`: a control room at night, lit by one amber candle. The console is part of the skeleton, so both apps (`apps/modbus`, `apps/snmp`) receive the new look with no app code changes.

The current console is a table-per-device page with a raw JSON textarea, a plain `/audit` table and a "Summon again" button that reloads the page. The rebuild replaces it with a header, a summary strip, device sections made of fixed-size point tiles, a Ledger column that refreshes on its own, and a "Call a tool yourself" panel built from selects.

To mark a tile as needing attention without protocol knowledge, the skeleton configuration gains one optional per-point field, `healthy`. It names the label text that means normal (for example `up`). A second optional field, a top-level `title`, gives the header an app name without protocol knowledge in the skeleton. Outside `skeleton/seance/console/` and its tests, the changes are the two config fields, the two `devices.yaml` files, and the tests and README text that quote a device description (Requirement 13).

Constraints carried from the steering documents and the request:

- Tool behavior, the read-only guard, the audit format and the adapters do not change.
- Tool results and the audit log keep raw values. Display formatting happens only in the browser.
- The console is plain HTML, CSS and JavaScript, with no framework and no build step.
- The full test suite is verified on GitHub Actions, not locally.

Current code facts that these requirements rely on:

- `PointConfig` (in `skeleton/seance/points.py`) has `name`, `address`, `data_type`, `unit`, `scale`, `decimals` and `labels`. `labels` is a tuple of (integer, text) pairs.
- `load_config` and `dump_config` (in `skeleton/seance/config.py`) validate and render the YAML. `dump_config` output must load back unchanged.
- A labeled integer read returns the label text as `value` and the integer as `raw`.
- `AuditEntry` has `timestamp`, `tool`, `device`, `point`, `outcome` and `duration_ms`. It has no reason text.
- The console routes are `/`, `/points/{device}/{point}`, `/tools/{tool_name}` and `/audit` (50 most recent, newest first). `/` currently reads every device with one `read_points` call.
- Existing outcome values include `ok`, `rejected`, `unknown_tool`, `unknown_target`, `invalid_argument`, `timeout` and `adapter_error`.

## Glossary

- **Console**: The web console served from `skeleton/seance/console/` (the FastAPI routes, `templates/index.html`, `static/console.css` and `static/console.js`).
- **Page**: The HTML document that the Console returns for `GET /`.
- **Config_Loader**: The code in `skeleton/seance/config.py` that loads, validates and dumps the YAML configuration.
- **Point_Config**: The `PointConfig` dataclass in `skeleton/seance/points.py`.
- **Healthy_Label**: The optional `healthy` text on a Point_Config that names the label meaning normal, for example `up`.
- **Tile**: The Console element that shows one point. It has three lines: the point name, the value with its unit, and one small detail line.
- **Attention_Tile**: A Tile whose read failed, or whose point has a Healthy_Label and whose returned label differs from it.
- **Attention_Chip**: One entry in the Summary_Strip that names one problem. There is one Attention_Chip per Attention_Tile.
- **Summary_Strip**: The Console row below the header that shows devices answering, points read and the Attention_Chips.
- **Device_Answering**: A device for which the most recent read returned at least one successful point reading, or a device with no points that raised no error.
- **Point_Read**: One point whose most recent read returned a value.
- **Ledger**: The Console column that lists recent Audit_Entries, newest first.
- **Audit_Entry**: One recorded tool call, as defined by `AuditEntry` in `skeleton/seance/audit.py`.
- **Ledger_Row**: One Audit_Entry as shown in the Ledger.
- **Tool_Panel**: The section titled "Call a tool yourself", with selects for tool, device and point, a Send button and the raw reply.
- **Steering_Tokens**: The nine CSS colors defined in the Tokens table of `.kiro/steering/design.md`: `--ground`, `--panel`, `--ink`, `--mute`, `--line`, `--line-strong`, `--alert`, `--alert-ink` and `--alert-ground`.
- **Formatter**: The browser-side JavaScript functions that turn a raw value, unit and timestamp into display text.
- **Test_Suite**: `skeleton/tests/test_console.py` and the test files added for the Healthy_Label.
- **App_Title**: The optional top-level `title` text of the YAML configuration, stored on the Configuration, shown in the header as the app name.
- **Device_Header_Row**: The single row at the top of a device section that holds the device name, the description and the health text, above the section rule.

## Requirements

### Requirement 1: Optional healthy label in the configuration

**User Story:** As an app author, I want to name the label that means normal for a point, so that the Console can flag abnormal states without knowing the protocol.

#### Acceptance Criteria

1. THE Point_Config SHALL carry an optional Healthy_Label that defaults to no value.
2. WHEN a point in the YAML file has a `healthy` field with non-empty text and a `labels` mapping that contains that text as a value, THE Config_Loader SHALL store the text as the Healthy_Label of the point.
3. WHEN a point has no `healthy` field, THE Config_Loader SHALL load the point with no Healthy_Label.
4. IF a point has a `healthy` field that is not non-empty text, THEN THE Config_Loader SHALL raise a ConfigError that names the file, the device and the field `points[<name>].healthy`.
5. IF a point has a `healthy` field and no `labels` mapping, THEN THE Config_Loader SHALL raise a ConfigError that names the field `points[<name>].healthy` and states that `labels` is required.
6. IF the `healthy` text is not one of the values in the `labels` mapping of the point, THEN THE Config_Loader SHALL raise a ConfigError that names the field `points[<name>].healthy` and lists the allowed label texts.
7. WHEN `dump_config` renders a Configuration that contains Healthy_Labels, THE Config_Loader SHALL include each Healthy_Label in the output so that `load_config` reads back an equal Configuration.
8. THE Config_Loader SHALL produce the same Point_Config values for every existing YAML file that has no `healthy` field.
9. THE Test_Suite SHALL cover the Healthy_Label with example tests for each ConfigError case and a round-trip test through `dump_config` and `load_config`, in `skeleton/tests/test_config.py` and a `test_config_properties.py` file when a property test is added.

### Requirement 2: Healthy labels in the SNMP app configuration

**User Story:** As a network engineer, I want the status points of the SNMP simulator marked with their normal label, so that a down port or a battery run shows as a problem.

#### Acceptance Criteria

1. THE `apps/snmp/devices.yaml` file SHALL set `healthy: up` on `port1_status`, `port2_status`, `port3_status`, `port4_status` and `wan_link_status`.
2. THE `apps/snmp/devices.yaml` file SHALL set `healthy: normal` on `on_battery`.
3. WHEN `load_config` reads `apps/snmp/devices.yaml`, THE Config_Loader SHALL load the file without error.
4. THE change set of this feature SHALL touch no file under `apps/` other than `apps/snmp/devices.yaml`, `apps/modbus/devices.yaml` (only for the changes named in Requirement 13) and the tests and README files that quote a device description (Requirement 13.11).

### Requirement 3: Page structure

**User Story:** As a plant engineer, I want one clear screen with the header, summary, devices, Ledger and tool panel, so that I can see the state of the equipment at a glance.

#### Acceptance Criteria

1. THE Page SHALL contain, in document order, a header, a Summary_Strip, a main column with one section per device, and a Ledger column.
2. THE Page SHALL contain the Tool_Panel below the device sections in the main column.
3. THE header SHALL contain the wordmark `Seance`, the app name, a chip with the text `READ-ONLY, 5 TOOLS`, the time of the last read, and a `Read again` button.
4. THE Console SHALL render the wordmark `Seance` once on the Page, in the header.
5. THE Page SHALL contain one `h2` heading per device section. The `h2` text SHALL be the device name, followed by the description and the health text of the device.
6. WHEN a device has no points, THE Console SHALL render its section with the text `No points configured.` and no Tiles.
7. WHEN no devices are configured, THE Console SHALL render the text `No devices are configured.` in the main column.
8. THE Console SHALL escape every device name, description, point name, value and error text before it is written into HTML, so that the original text is readable in the browser.
9. THE Console SHALL write dynamic text from JavaScript with `textContent` or an equivalent method that does not parse HTML.
10. THE Page SHALL use the theme words `Seance` and `Ledger` only, and no other theme words in headings, labels or buttons.
11. THE Page SHALL use sentence case for headings and buttons, and no parentheses in heading text or button text.
12. THE Console SHALL serve the Page from `GET /` with no framework and no build step.

### Requirement 4: Design tokens, type and layout rules

**User Story:** As a designer, I want the stylesheet to use only the steering tokens, so that the console matches the design document exactly.

#### Acceptance Criteria

1. THE `console.css` file SHALL define the nine Steering_Tokens once, as CSS custom properties on `:root`, with the exact hex values from `.kiro/steering/design.md`.
2. THE `console.css` file SHALL use each color only through `var(--token)` of a Steering_Token, with no hex, `rgb`, `hsl` or named color literal outside the `:root` block.
3. THE `console.css` file SHALL set the border radius to 3px on every element that has a radius, and SHALL contain no `box-shadow`, no gradient function and no `text-shadow`.
4. THE `console.css` file SHALL set the wordmark in Fraunces italic weight 500 at 30px, the text in Inter at weights 400, 500 and 600, and numbers, point names, tool names, timestamps and code in JetBrains Mono.
5. THE Page SHALL load the three font families from Google Fonts with `display=swap`.
6. THE `console.css` file SHALL give every `font-family` declaration a system fallback list, so that the Page renders without network access.
7. THE Page SHALL contain no emoji and no icon other than one warning triangle on each Attention_Tile.
8. THE `console.css` file SHALL give light text on dark surfaces a contrast ratio of at least 4.5:1 for every text and surface pair that the stylesheet uses, including the 11px detail lines.
9. THE Console SHALL use real `button`, `select`, `label` and `a` elements for controls, and SHALL give each control a minimum height of 44px.
10. WHEN the viewport is 390px wide, THE Console SHALL wrap the header, move the Ledger below the device sections, and show the Tile grid with two columns.

### Requirement 5: Point tiles

**User Story:** As an operator, I want every point shown as a tile of the same size, so that I can scan many values without the layout moving.

#### Acceptance Criteria

1. FOR ALL configurations, THE Page SHALL contain exactly one Tile for each point in the configuration, in configuration order within each device section.
2. THE Console SHALL show on each Tile three lines: the point name, the value with its unit, and one detail line.
3. THE `console.css` file SHALL lay out the Tiles in a grid with `grid-template-columns: repeat(auto-fill, minmax(196px, 1fr))` and a 10px gap.
4. THE `console.css` file SHALL set the height of every Tile to 108px in one shared rule, and no other rule SHALL set a height, min-height or max-height on a Tile or on content inside a Tile that changes the Tile height.
5. WHEN the content of a Tile line is longer than the Tile width, THE Console SHALL clip the line with an ellipsis and keep the Tile height at 108px.
6. WHEN a point read fails, THE Console SHALL show the Tile as an Attention_Tile with the short error sentence in the detail line, and the full sentence in the `title` attribute.
7. WHERE a point has a Healthy_Label, WHEN the returned label differs from the Healthy_Label, THE Console SHALL show the Tile as an Attention_Tile.
8. WHERE a point has no Healthy_Label, WHEN the read succeeds, THE Console SHALL show the Tile as a normal tile.
9. THE Console SHALL show an Attention_Tile with the `--alert-ground` background, a 2px `--alert` border, `--alert-ink` text and one warning triangle.
10. THE Console SHALL show the attention state with the warning triangle and the word of the label or the error text, so that state is not shown by color alone.

### Requirement 6: Display formatting in the browser

**User Story:** As an operator, I want durations, sizes, states and times in readable form, so that I do not have to convert raw numbers.

#### Acceptance Criteria

1. WHEN a value has unit `s` and the value is 60 or more, THE Formatter SHALL show it as a duration, with each part rounded down to a whole number: `<d>d <h>h <m>m` from one day up, `<h>h <m>m` from one hour up to one day, and `<m>m <s>s` below one hour. THE Formatter SHALL show the raw value with a thousands separator and the unit `s` on the detail line. For example, `86427.5 s` SHALL show as `1d 0h 0m` with `86,427.5 s` on the detail line, and `270 s` SHALL show as `4m 30s` with `270 s` on the detail line.
2. WHEN a value has unit `B`, THE Formatter SHALL show the value in decimal units (kB, MB, GB, TB) with two decimals, and SHALL show the raw byte count with a thousands separator on the detail line. For example, `5010152941 B` SHALL show as `5.01 GB` with `5,010,152,941 B` on the detail line.
3. WHEN a value is a boolean, THE Formatter SHALL show `on` for true and `off` for false, and the detail line SHALL show the time of the read.
4. WHEN a result carries a `raw` integer next to a label value, THE Formatter SHALL show the label as the value, and the detail line SHALL show `raw <integer>` and the time of the read.
5. WHEN a unit is `degC`, THE Formatter SHALL show `°C`. WHEN a unit is `percent`, THE Formatter SHALL show `%`. WHEN a unit is `state`, THE Formatter SHALL show no unit.
6. WHEN a unit is not listed in this requirement, THE Formatter SHALL show the unit text as received.
7. WHEN a timestamp is an ISO 8601 UTC string, THE Formatter SHALL show the local time as `HH:MM:SS` and SHALL set the full ISO value as the `title` attribute of the element.
8. IF a timestamp cannot be parsed, THEN THE Formatter SHALL show the received text unchanged.
9. THE Formatter SHALL leave every tool result, every `/points` response and every `/audit` response unchanged, so that agents and the Ledger source keep raw values.
10. THE Formatter SHALL never change the sign of a numeric value that it displays.
11. THE Page SHALL contain the character `°` only through the Formatter or an HTML entity, so that Python and CSS source files stay ASCII.
12. WHEN a value has unit `s` and the value is less than 60, THE Formatter SHALL show the value as plain seconds, which is the number followed by the unit `s`, and the detail line SHALL show the time of the read. For example, `42.5 s` SHALL show as `42.5 s`.
13. THE Formatter SHALL choose every format from the unit and the type of the value only, and SHALL never consult a point name, a device name or a description.

### Requirement 7: Summary strip

**User Story:** As an operator, I want a one-line summary with a chip for each problem, so that I see what needs attention before I read any tile.

#### Acceptance Criteria

1. THE Summary_Strip SHALL show the number of devices answering out of the number of configured devices, and the number of points read out of the number of configured points.
2. THE Summary_Strip SHALL show one Attention_Chip for each Attention_Tile, in the same order as the Tiles.
3. FOR ALL read results, THE number of Attention_Chips SHALL equal the number of Attention_Tiles.
4. THE Attention_Chip SHALL name the device and the point, and SHALL state the problem as the returned label or the failed read.
5. WHEN no Attention_Tile exists, THE Summary_Strip SHALL contain no Attention_Chip.
6. WHEN the user activates an Attention_Chip, THE Console SHALL move the focus to the matching Attention_Tile.
7. WHEN a device read fails for every point, THE Summary_Strip SHALL count that device as not answering and SHALL show one Attention_Chip for each of its points.
8. THE Summary_Strip SHALL show an Attention_Chip in the attention style of Requirement 5, criterion 9.

### Requirement 8: Ledger

**User Story:** As a safety officer, I want to see every recent call, including calls that agents make, so that I can check what was asked of the equipment.

#### Acceptance Criteria

1. THE Ledger SHALL show the Audit_Entries from `GET /audit`, newest first, in the order that the endpoint returns them.
2. THE Ledger SHALL never show more Ledger_Rows than the number of Audit_Entries in the audit log, and never more than `AUDIT_LIMIT`.
3. THE Ledger SHALL show on each Ledger_Row the tool name, the target (the device, followed by the point when one exists), the outcome and the local time as `HH:MM:SS`, with the full ISO timestamp in the `title` attribute.
4. WHEN the outcome of an Audit_Entry is not `ok`, THE Ledger SHALL show the Ledger_Row in the attention style with the warning triangle and a reason sentence.
5. THE Console SHALL derive the reason sentence from the outcome value in the browser, with one plain sentence for each of `rejected`, `unknown_tool`, `unknown_target`, `invalid_argument`, `timeout` and `adapter_error`, and a generic sentence for any other outcome. Each sentence SHALL say what failed and what to try next.
6. WHEN the audit log is empty, THE Ledger SHALL show the text `No calls yet.`
7. WHILE the Page is open, THE Console SHALL request `/audit` every 2 seconds and replace the Ledger_Rows without reloading the Page.
8. WHEN an agent makes a tool call while the Page is open, THE Ledger SHALL show the new Audit_Entry at the top within 2 seconds plus the request time.
9. IF a request to `/audit` fails, THEN THE Ledger SHALL keep the rows already shown and SHALL show the sentence `The ledger could not be loaded. It will try again in 2 seconds.`
10. THE Console SHALL leave the `GET /audit` response fields and the audit format unchanged.
11. THE Ledger SHALL not start a new request while the previous `/audit` request is still pending.

### Requirement 9: Read again and the tool panel

**User Story:** As an engineer, I want to re-read all points and to call any tool from selects, so that I can check a device without writing JSON.

#### Acceptance Criteria

1. WHEN the user activates `Read again`, THE Console SHALL re-read all points of all devices and update every Tile, the Summary_Strip and the time of the last read, without reloading the Page.
2. WHILE a re-read is in progress, THE Console SHALL disable the `Read again` button and keep the Tiles on screen.
3. THE Tool_Panel SHALL contain a `select` for the tool with the five tool names `list_devices`, `list_points`, `read_point`, `read_points` and `device_health`, a `select` for the device, a `select` for the point, and a `Send` button.
4. WHEN the selected tool needs no device, THE Tool_Panel SHALL disable the device select and the point select.
5. WHEN the selected tool needs a device and no point, THE Tool_Panel SHALL enable the device select and disable the point select.
6. WHEN the selected tool is `read_point`, THE Tool_Panel SHALL enable both selects, and the point select SHALL list only the points of the selected device.
7. WHEN the selected tool is `read_points`, THE Tool_Panel SHALL send the names of all points of the selected device as the `points` argument.
8. WHEN the user changes the selected device, THE Tool_Panel SHALL refill the point select with the points of that device.
9. WHEN the user activates `Send`, THE Tool_Panel SHALL post the arguments to `/tools/<tool>` and show the raw JSON reply, indented, without display formatting.
10. THE Tool_Panel SHALL contain no textarea and no raw JSON input.
11. IF the request to `/tools/<tool>` fails, THEN THE Tool_Panel SHALL show a sentence that says the console server did not answer and what to try next.
12. WHEN the user sends a call from the Tool_Panel, THE Console SHALL refresh the Ledger at once.
13. THE Tool_Panel SHALL populate the tool options from the server-side tool list, so that the Console sends no tool outside the read tools.

### Requirement 10: Unchanged behavior and boundaries

**User Story:** As a maintainer, I want the redesign limited to the console, so that the guard, the audit log and the adapters keep working as before.

#### Acceptance Criteria

1. THE Console SHALL read every value through `ToolServer.call`, so that each Console call writes exactly one Audit_Entry.
2. THE Console SHALL keep the routes `GET /points/{device}/{point}`, `POST /tools/{tool_name}` and `GET /audit` with their current status codes and response bodies.
3. THE change set SHALL leave `skeleton/seance/guard.py`, `skeleton/seance/audit.py`, `skeleton/seance/adapter.py` and every file under `apps/*/adapter.py` unchanged.
4. THE skeleton SHALL import nothing from `apps/`, and SHALL import neither `pymodbus` nor `pysnmp`.
5. THE change set SHALL edit files only in `skeleton/seance/console/`, `skeleton/tests/`, `skeleton/seance/config.py`, `skeleton/seance/points.py`, `apps/snmp/devices.yaml`, `apps/modbus/devices.yaml` and this spec folder, plus the `healthy` and `title` documentation lines in `README.md` and `docs/add-a-protocol.md` when those files describe point fields or top-level fields, plus every test file under `apps/*/tests/` and every `README.md` (root and `apps/*/README.md`) that quotes an old device description text, plus the `apps/*/tests/test_server_integration.py` tests that assert the old server-rendered markup. THE change set SHALL change no other Modbus source file, so `apps/modbus/adapter.py`, `apps/modbus/simulator.py` and every Modbus test that does not quote an old device description or assert the old markup stay as they are.
6. THE source files and the documents of the change set SHALL be UTF-8 and use ASCII characters only.
7. THE Console SHALL create no event loop per request, and the tests SHALL reuse the session event loop.
8. THE served HTML shell, `console.css` and `console.js` SHALL contain no point name and no device name. Names SHALL reach the Page only as data from `GET /config` and from tool results, and the server SHALL not write a device name into the HTML shell.

### Requirement 11: Correctness properties

**User Story:** As a maintainer, I want the key invariants of the console checked automatically, so that a later change cannot silently break them.

#### Acceptance Criteria

1. FOR ALL configurations that Hypothesis generates, THE Page SHALL contain exactly one Tile for each point in the configuration (Property 1).
2. FOR ALL configurations and read outcomes that Hypothesis generates, THE number of Attention_Chips SHALL equal the number of Attention_Tiles (Property 2).
3. FOR ALL audit logs that Hypothesis generates, THE Ledger SHALL show no more Ledger_Rows than the number of Audit_Entries, and SHALL keep newest-first order (Property 3).
4. WHERE the Formatter, the chip count or the Ledger ordering is implemented in JavaScript, THE Test_Suite SHALL check Properties 1 to 3 as example tests on the rendered HTML and on the served `console.js` source instead of Hypothesis tests.
5. WHERE the tile markup, the chip markup or the Ledger rows are produced by pure Python helpers in `skeleton/seance/console/`, THE Test_Suite SHALL check Properties 1 to 3 with Hypothesis in `skeleton/tests/test_console_properties.py`.
6. THE property tests SHALL reuse the session event loop and make no network calls.

### Requirement 12: Tests for the design rules

**User Story:** As a maintainer, I want tests that enforce the steering rules, so that the console stays on design.

#### Acceptance Criteria

1. THE Test_Suite SHALL check that the HTML shell contains the header, the Summary_Strip, the devices container, the Ledger and the Tool_Panel, and that the served `console.js` creates one section per device from the `GET /config` data.
2. THE Test_Suite SHALL check that every color value in `console.css`, outside the `:root` block, is `var(--token)` of a Steering_Token, and that the `:root` block holds exactly the nine Steering_Tokens with the steering values.
3. THE Test_Suite SHALL check that no rule that targets a Tile sets its own height other than the one shared 108px rule.
4. THE Test_Suite SHALL check that no heading and no button in the Page contains a parenthesis.
5. THE Test_Suite SHALL check that `console.css` contains no `box-shadow`, `text-shadow` or gradient function, and that every `border-radius` is 3px.
6. THE Test_Suite SHALL check that every `font-family` declaration ends with a generic system family.
7. THE Test_Suite SHALL check that the Page loads the three Google Fonts families with `display=swap`.
8. THE Test_Suite SHALL keep each existing test in `skeleton/tests/test_console.py` passing, and SHALL update a test only when it asserts the old markup, and the final report SHALL list each test that changed and why.
9. THE Test_Suite SHALL make no network call and SHALL run the console tests with the Fake_Adapter.
10. THE Test_Suite SHALL be verified on GitHub Actions. THE developer SHALL run only `ruff` and at most one targeted pytest file, once, on the local machine.
11. THE Test_Suite SHALL load `apps/modbus/devices.yaml` and `apps/snmp/devices.yaml`, and SHALL check that no device name and no point name from either file appears in the served HTML (`GET /`, built over each of the two configurations) or in the served `console.js`. THE check SHALL match each name as a whole word, ignoring case, and SHALL fail with the file and the name that was found.

### Requirement 13: App title, plain device descriptions and the device header row

**User Story:** As an operator, I want the header to name the app, the device descriptions to be short, and each device name, description and health text on one row, so that the console reads at a glance.

#### Acceptance Criteria

1. THE Configuration SHALL carry an optional App_Title that defaults to no value, and THE skeleton SHALL treat the App_Title as generic text with no protocol knowledge.
2. WHEN the YAML file has a top-level `title` field with non-empty text of at most 40 characters, THE Config_Loader SHALL store the text as the App_Title.
3. WHEN the YAML file has no top-level `title` field, THE Config_Loader SHALL load the Configuration with no App_Title.
4. IF the top-level `title` field is empty, is not text, or is longer than 40 characters, THEN THE Config_Loader SHALL raise a ConfigError that names the file and the field `title`.
5. WHEN `dump_config` renders a Configuration, THE Config_Loader SHALL write the `title` field only when the App_Title is set.
6. FOR ALL valid Configurations, loading, dumping and loading again SHALL produce an equal Configuration, with and without an App_Title (round-trip property).
7. THE `GET /config` response SHALL include a `title` field that holds the App_Title, or null when no App_Title is set.
8. WHERE the `GET /config` response carries a `title`, THE header SHALL show the App_Title as the app name in place of the placeholder `Read-only console`.
9. WHILE the `GET /config` response carries a null `title`, THE header SHALL show the app name `Read-only console`.
10. THE `apps/snmp/devices.yaml` file SHALL set `title: "SNMP network gear"` and THE `apps/modbus/devices.yaml` file SHALL set `title: "Modbus factory line"`.
11. THE `apps/snmp/devices.yaml` and `apps/modbus/devices.yaml` files SHALL hold, for every device, a description with no parenthetical part, for example `Core switch with four ports and an uplink`, and THE change set SHALL update every test and every README table (`apps/*/README.md`, `README.md`) that quotes an old description text.
12. THE Console SHALL show the device name and the description on one Device_Header_Row above the section rule, with the health text at the right end of the same row.
13. WHEN the viewport is 390px wide, THE Console SHALL wrap the Device_Header_Row so that no text is clipped and no horizontal scrolling appears.
14. THE Device_Header_Row SHALL be built by `console.css` and `console.js` only, and `console.js`, `console.css` and the HTML shell SHALL contain no device name and no point name.
15. THE Test_Suite SHALL cover the App_Title in `skeleton/tests/test_config.py` with example tests for a valid title, an absent title, an empty title, a non-text title, a 41-character title and a round trip, SHALL extend the Hypothesis round trip in `skeleton/tests/test_config_properties.py` with an optional title, and SHALL check in `skeleton/tests/test_console.py` that `GET /config` returns the title or null.
