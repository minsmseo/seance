# Requirements Document

## Introduction

The SNMP app is the second application built on the Seance skeleton. It lives in `apps/snmp/` and exposes simulated network gear over SNMP v2c through the five read-only MCP tools. The gear is a core switch, an edge router and a UPS. One command starts the simulator, the MCP server and the web console together, so anyone can ask a forty-year-old management protocol what it is doing without hardware.

The goal is to prove that the skeleton is protocol-agnostic. The SNMP_App adds only four things to the skeleton: a Simulator, an SNMP_Adapter, an Address_Parser and a devices file. The SNMP_Adapter is the only file that imports `pysnmp`. The app is read-only: the adapter sends SNMP GET requests only and never sends SET.

The SNMP_App uses the skeleton's public interface as it is: `ProtocolAdapter`, `AdapterReadError`, `PointConfig`, `DeviceConfig`, `load_config`, `build_tool_server` and `serve`. Two skeleton gaps are listed under "Skeleton Changes". Each is a generic, protocol-agnostic feature and a separate task. The SNMP_App does not change `apps/modbus/`.

## Glossary

- **Seance_Skeleton**: The code in `skeleton/seance/` that provides the Tool_Server, Codec, Read_Only_Guard, Audit_Log, Config_Loader and Web_Console.
- **SNMP_App**: The application in `apps/snmp/`, made of the Simulator, the SNMP_Adapter, the Address_Parser, the SNMP_Config and the Entry_Point.
- **Modbus_App**: The application in `apps/modbus/`. The SNMP_App uses it as the reference for conventions and for the tool-name comparison.
- **Simulator**: The SNMP v2c agent in `apps/snmp/simulator.py` that simulates the three Devices on one UDP port. It is a minimal v2c responder on an asyncio UDP socket and does not import pysnmp. Only the SNMP_Adapter imports pysnmp.
- **SNMP_Adapter**: The `ProtocolAdapter` implementation in `apps/snmp/adapter.py`. It is the only file in the repository that imports pysnmp.
- **SNMP_Config**: The YAML file `apps/snmp/devices.yaml` that describes the three Devices and their Points.
- **Entry_Point**: The module `apps/snmp/__main__.py`, started with `uv run python -m apps.snmp`.
- **Device**: One of Core_Switch, Edge_Router or UPS. The Simulator tells the Devices apart by the SNMP community string of the request.
- **Core_Switch**: The Device named `core_switch`, community `core_switch`.
- **Edge_Router**: The Device named `edge_router`, community `edge_router`.
- **UPS**: The Device named `ups`, community `ups`.
- **Point**: One readable value of a Device, as defined by `PointConfig` in the Seance_Skeleton.
- **OID**: A numeric object identifier in dotted decimal form, such as `1.3.6.1.2.1.1.3.0`. It has at least two arcs, and each arc is a decimal integer without leading zeros.
- **SNMP_Address**: The text in the `address` field of a Point, in the form `<community>:<oid>`. `<community>` is the Device community, made of lowercase letters, digits and underscores, starting with a letter. `<oid>` is an OID. The design may refine this form, but the form SHALL stay self-contained, name the Device to ask and carry a numeric OID.
- **Address_Parser**: The function in the SNMP_App that turns SNMP_Address text into a community and an OID, or returns an error sentence.
- **Address_Formatter**: The function in the SNMP_App that turns a community and an OID into SNMP_Address text.
- **PDU_Type**: One of GET, GETNEXT, GETBULK or SET, the SNMP request kinds the Simulator records.
- **PDU_Record**: The Simulator's list of every PDU_Type it receives, in order, with the community and the OIDs of the request.
- **SNMP_Error**: A noSuchObject, noSuchInstance or noSuchName answer, an SNMP error-status in a response, or a missing response within the timeout.
- **Counter64**: The SNMP 64-bit unsigned counter type. It needs an unsigned 64-bit data type in the Codec.
- **Value_Labels**: An optional map on a Point from raw integer values to short text, such as 1 to `up` and 2 to `down`. The Tool_Server returns the text as the value and keeps the raw integer next to it.
- **Default_Seed**: The random seed the Simulator and the README use when no other seed is given.
- **Drift**: A slow, bounded change of a simulated value over time.
- **Audit_Log**: The Seance_Skeleton record of one entry per tool call.
- **Tool_Server**: The Seance_Skeleton component that serves the tools `list_devices`, `list_points`, `read_point`, `read_points` and `device_health`.
- **Web_Console**: The Seance_Skeleton web page that shows devices, values and the audit log.
- **Timeout_Sentence**: The sentence the Tool_Server returns when a device does not answer within the device's configured timeout.
- **Kiro_MCP_Config**: The workspace file `.kiro/settings/mcp.json` that lets Kiro start the SNMP_App as an MCP server.
- **Example_Question**: A question in the README that an agent can answer with the tools of the SNMP_App.

## Requirements

### Requirement 1: Simulated network gear

**User Story:** As a developer without hardware, I want simulated SNMP gear that behaves plausibly, so that I can try the app anywhere.

#### Acceptance Criteria

1. THE Simulator SHALL serve SNMP v2c over UDP on a host and port given at construction.
2. THE Simulator SHALL simulate exactly three Devices: Core_Switch, Edge_Router and UPS, each selected by its community string.
3. WHEN the Simulator is started with a given random seed, THE Simulator SHALL produce the same sequence of values as every other run with that seed.
4. WHEN the Simulator is started with the Default_Seed, THE Simulator SHALL report the operational status of Core_Switch port 3 as down and every other status Point as healthy.
5. WHILE the Simulator runs, THE Simulator SHALL apply Drift to the analog values and counters of every Device at least once per second.
6. WHILE the Simulator runs, THE Simulator SHALL keep every drifting value inside the minimum and maximum declared for that value.
7. WHILE the Simulator runs, THE Simulator SHALL keep every counter non-decreasing until it wraps at its type maximum.
8. WHEN a request names a community that is not one of the three Devices, THE Simulator SHALL send no response.
9. WHEN a GET request names an OID that the Device does not define, THE Simulator SHALL answer with noSuchObject for that OID.
10. THE Simulator SHALL answer GET, GETNEXT and GETBULK requests for the OIDs of the Devices.
11. WHEN the Simulator receives a SET request, THE Simulator SHALL answer with an SNMP error-status and leave every value unchanged.
12. THE Simulator SHALL record the PDU_Type of every request it receives in the PDU_Record, for use by tests.
13. THE Simulator SHALL run on one event loop per Simulator instance.
14. WHEN the Simulator is stopped, THE Simulator SHALL close its event loop, release its UDP port and stop its Drift task within 2 seconds.
15. WHEN the Simulator is started again on the same port after a stop, THE Simulator SHALL bind the port without error.

### Requirement 2: SNMP read adapter

**User Story:** As a network engineer, I want the adapter to read values and nothing else, so that no tool call can change running equipment.

#### Acceptance Criteria

1. THE SNMP_Adapter SHALL implement the `connect`, `close`, `read` and `health` methods of `ProtocolAdapter`.
2. THE SNMP_Adapter SHALL implement no method that writes to a device.
3. THE SNMP_Adapter SHALL send only SNMP GET requests.
4. THE SNMP_App SHALL contain no call to a pysnmp SET method and no SET PDU in any file outside the Simulator.
5. WHEN `read` is called, THE SNMP_Adapter SHALL send one GET request to the configured host and port, with the community and OID of the Point's SNMP_Address.
6. WHEN `read` receives a value, THE SNMP_Adapter SHALL return its raw bytes, big-endian, with the length that the Codec requires for the Point's data type.
7. WHEN `read` returns bytes for a Point, THE Seance_Skeleton Codec and scale SHALL produce a value equal to the value decoded and scaled directly from the Simulator's state for that Point.
8. IF the Simulator answers a GET with noSuchObject, noSuchInstance or an SNMP error-status, THEN THE SNMP_Adapter SHALL raise `AdapterReadError` with one sentence that names the Device and the Point and states the failure in plain words.
9. IF the Simulator does not answer a GET within the timeout, THEN THE SNMP_Adapter SHALL raise `AdapterReadError` with one sentence that names the Device and the Point and says the Device did not answer.
10. IF the value type returned for a Point does not fit the Point's data type, THEN THE SNMP_Adapter SHALL raise `AdapterReadError` with one sentence that names the Point, the data type and the returned SNMP type.
11. WHEN `health` is called for a Device, THE SNMP_Adapter SHALL return `ok` if the Device answers a GET of its first configured Point, `degraded` if the Device answers with an SNMP_Error, and `unreachable` if the Device does not answer.
12. THE SNMP_Adapter SHALL apply a timeout of 2 seconds to every SNMP request unless the Device configures another timeout.
13. THE SNMP_Adapter SHALL send no retries beyond the timeout of one request.
14. WHEN `connect` is called, THE SNMP_Adapter SHALL prepare its SNMP engine for the configured host and port.
15. WHEN `close` is called, THE SNMP_Adapter SHALL release its SNMP engine and its resources.
16. THE SNMP_Adapter SHALL be the only file in the repository that imports `pysnmp`.
17. THE SNMP_Adapter SHALL import nothing from other files in `apps/` except the Address_Parser of the SNMP_App.
18. THE SNMP_Adapter SHALL reuse one event loop for all of its requests and create no event loop per read.
19. IF the adapter raises `AdapterReadError`, THEN THE Audit_Log SHALL contain exactly one entry for that call with outcome `adapter_error`.
20. IF an SNMP failure sentence is returned to the agent, THEN THE sentence SHALL contain no stack trace and no pysnmp class name.
21. WHEN the first adapter task is executed, THE SNMP_App tests SHALL verify, in tests that run on GitHub Actions (ubuntu) and not on the local machine, (a) the pysnmp import paths of NoSuchObject, NoSuchInstance and EndOfMibView, (b) the shape of the varBinds returned for a GET with lookupMib=False, and (c) that the adapter keeps a single private event loop, a single thread and a single SnmpEngine across many reads, before any later task relies on them. The Windows event loop type is a documented untested risk, and any fix for it SHALL be confined to `adapter.py`.

### Requirement 3: SNMP address parsing and formatting

**User Story:** As an operator, I want SNMP addresses written in one plain form, so that I can read and edit the config without a manual.

#### Acceptance Criteria

1. WHEN a valid SNMP_Address text is given, THE Address_Parser SHALL return its community and OID.
2. THE Address_Formatter SHALL format a community and an OID into SNMP_Address text.
3. FOR ALL valid SNMP_Address texts, parsing then formatting then parsing SHALL return the same community and OID, and formatting SHALL return the original text (round-trip property).
4. IF an SNMP_Address text does not have exactly two colon-separated parts, THEN THE Address_Parser SHALL return an error sentence that shows the form `<community>:<oid>`.
5. IF the community of an SNMP_Address text is empty or has a character other than a lowercase letter, a digit or an underscore, THEN THE Address_Parser SHALL return an error sentence that names the field `community` and the allowed characters.
6. IF the OID of an SNMP_Address text has fewer than two arcs, an empty arc, a non-numeric arc or an arc with leading zeros, THEN THE Address_Parser SHALL return an error sentence that names the field `oid` and shows an example OID.
7. IF the first arc of an OID is greater than 2, or the first arc is less than 2 and the second arc is greater than 39, THEN THE Address_Parser SHALL return an error sentence that names the field `oid` and the allowed arc values.
8. THE Address_Parser SHALL accept arcs up to 4294967295.
9. THE Address_Parser SHALL accept a numeric OID only and SHALL reject an OID written with names.

### Requirement 4: Point configuration

**User Story:** As an operator, I want the three devices and their points described in YAML, so that I can add a sensor without editing code.

#### Acceptance Criteria

1. THE SNMP_Config SHALL define the three Devices `core_switch`, `edge_router` and `ups`.
2. THE SNMP_Config SHALL define exactly 19 Points in total.
3. THE SNMP_Config SHALL define for `core_switch` the Points uptime, operational status of ports 1 to 4, uplink in octets, uplink out octets and uplink in errors.
4. THE SNMP_Config SHALL define for `edge_router` the Points uptime, cpu load, memory used, wan link status, wan in octets and wan out octets.
5. THE SNMP_Config SHALL define for `ups` the Points battery charge, runtime remaining, on battery, output load and temperature.
6. THE SNMP_Config SHALL give every Point a name, an SNMP_Address, a data type and a unit.
7. WHERE a raw value needs conversion to an engineering unit, THE SNMP_Config SHALL give the Point a scale greater than zero.
8. WHERE a Point is an integer status, THE SNMP_Config SHALL give the Point Value_Labels that name every status value the Simulator can report for that Point.
9. THE SNMP_Config SHALL include at least one Point of each data type: uint32, int32 and uint64.
10. THE SNMP_Config SHALL contain no unit that is empty text.
11. WHEN the SNMP_App starts, THE SNMP_App SHALL load the SNMP_Config with the Seance_Skeleton Config_Loader.
12. IF the SNMP_Config has an invalid field, THEN THE SNMP_App SHALL stop before serving and print one message that names the file, the Device and the field.
13. WHEN the SNMP_App starts, THE SNMP_App SHALL parse the SNMP_Address of every Point, and IF any is invalid, THEN THE SNMP_App SHALL stop before serving and print one message that names the Device, the Point and the reason.
14. IF the community of a Point's SNMP_Address differs from the Device name, THEN THE SNMP_App SHALL stop before serving and print one message that names the Device, the Point and both values.
15. THE SNMP_Config SHALL use the OIDs of the standard MIBs (MIB-II, IF-MIB, HOST-RESOURCES-MIB, UPS-MIB) where one exists, and OIDs under the private enterprise arc `1.3.6.1.4.1.99999` where none exists.

### Requirement 5: Value kinds and failed reads

**User Story:** As an agent, I want status values as words and short sentences when a read fails, so that I know what is wrong and what to try next.

#### Acceptance Criteria

1. WHEN a Point has Value_Labels and its decoded integer is in the map, THE Tool_Server SHALL return the mapped text as the value of the Point and the decoded integer as the raw value of the Point, for example value `down` with raw 2.
2. IF a Point has Value_Labels and its decoded integer is not in the map, THEN THE Tool_Server SHALL return the integer as the value of the Point, without an error.
3. WHEN a Point reads a Counter32, Gauge32 or TimeTicks value, THE SNMP_Adapter SHALL return 4 bytes that the Codec decodes as `uint32`.
4. WHEN a Point reads a Counter64 value, THE SNMP_Adapter SHALL return 8 bytes that the Codec decodes as `uint64`.
5. WHEN a Point reads an INTEGER value, THE SNMP_Adapter SHALL return 4 bytes that the Codec decodes as `int32`.
6. WHEN the Simulator reports uptime in TimeTicks, THE SNMP_Config SHALL scale the Point by 0.01 to give seconds.
7. WHILE the Simulator is stopped, THE Tool_Server SHALL return the Seance_Skeleton Timeout_Sentence for every read within the Device's configured timeout.
8. IF a read fails, THEN THE Tool_Server SHALL return a sentence that names the Device and the Point.
9. WHEN a read fails, THE Audit_Log SHALL contain exactly one entry for that call with the outcome of the failure.

### Requirement 6: Read-only behavior on the wire

**User Story:** As a network engineer, I want proof that the app cannot write, so that I can trust it near real equipment.

#### Acceptance Criteria

1. FOR ALL sequences of valid tool calls, THE Simulator SHALL observe no SET PDU.
2. FOR ALL sequences of valid tool calls, THE Simulator SHALL observe only GET PDUs from the SNMP_Adapter.
3. WHEN a write tool name or a write argument set reaches the Tool_Server, THE Simulator SHALL receive zero requests for that call.
4. THE SNMP_Adapter SHALL send no GETNEXT, GETBULK or SET request.

### Requirement 7: Entry point

**User Story:** As a judge or a new user, I want one command that starts everything, so that I can see it work in seconds.

#### Acceptance Criteria

1. WHEN `uv run python -m apps.snmp` is run, THE Entry_Point SHALL start the Simulator, the MCP server and the Web_Console in that order.
2. THE Entry_Point SHALL read the Simulator host from the environment variable `SEANCE_SNMP_HOST` and use `127.0.0.1` when it is not set.
3. THE Entry_Point SHALL read the Simulator port from the environment variable `SEANCE_SNMP_PORT` and use `1161` when it is not set.
4. THE Entry_Point SHALL read the Web_Console host from the environment variable `SEANCE_CONSOLE_HOST` and use `127.0.0.1` when it is not set.
5. THE Entry_Point SHALL read the Web_Console port from the environment variable `SEANCE_CONSOLE_PORT` and use `8080` when it is not set.
6. THE Entry_Point SHALL need no secret, no privileged port and no network access beyond its own host.
7. IF an environment variable holds a port that is not an integer from 1 to 65535, THEN THE Entry_Point SHALL stop before serving and print one message that names the variable and the allowed range.
8. IF the Simulator port is already in use, THEN THE Entry_Point SHALL stop and print one message that names the port and suggests setting `SEANCE_SNMP_PORT`.
9. WHILE the MCP server uses standard output for the MCP protocol, THE Entry_Point SHALL write every log and message to standard error.
10. WHEN the MCP server stops, THE Entry_Point SHALL stop the Web_Console and the Simulator and exit.
11. WHEN the SNMP_App starts, THE Web_Console SHALL show the three Devices with live values within 5 seconds.
12. WHEN a Point is read, THE Tool_Server SHALL return a value equal to the Simulator's state after decoding and scaling.

### Requirement 8: Tool parity with the Modbus app

**User Story:** As an agent, I want the same five tools on every Seance app, so that what I learned on one app works on the other.

#### Acceptance Criteria

1. THE SNMP_App Tool_Server SHALL expose exactly the tools `list_devices`, `list_points`, `read_point`, `read_points` and `device_health`.
2. THE SNMP_App Tool_Server and the Modbus_App Tool_Server SHALL expose the same set of five tool names.
3. THE SNMP_App SHALL add no tool that the Modbus_App does not expose.

### Requirement 9: Documentation

**User Story:** As a new user, I want a README in the app folder, so that I can run and understand the app on its own.

#### Acceptance Criteria

1. THE README SHALL have the same section headings as `apps/modbus/README.md`, in the same order: the title, "Run it", "Points", "Tools", "Example questions", "Run the tests" and "Use it from Kiro".
2. THE README SHALL state the command `uv run python -m apps.snmp` and the four environment variables with their defaults.
3. THE README SHALL explain that the default port is 1161 because port 161 needs elevated privileges.
4. THE README SHALL list every Point with its Device, name, SNMP_Address, data type, unit, scale and labels.
5. THE README SHALL give three Example_Questions that an agent can answer with the tools of the SNMP_App, each with the tool calls that answer it, and one SHALL ask which port of the core switch is down.
6. THE README SHALL show how to run the tests of the SNMP_App.
7. THE README SHALL describe the Kiro_MCP_Config and how to enable it.
8. THE README SHALL contain ASCII characters only.
9. THE README SHALL state that selecting a Device by the community string is a Simulator convention, and that real gear is addressed by host and port with the community kept as a secret.

### Requirement 10: Kiro workspace MCP configuration

**User Story:** As a Kiro user, I want the workspace to know this server, so that Kiro can query the simulated gear without manual setup.

#### Acceptance Criteria

1. WHEN the SNMP_App tasks reach the MCP configuration task, THE agent SHALL print the `seance-snmp` entry as a JSON object for the user to add to `.kiro/settings/mcp.json`, because the agent cannot write that file.
2. THE Kiro_MCP_Config SHALL be the file `.kiro/settings/mcp.json` in the workspace root.
3. THE Kiro_MCP_Config SHALL define one entry under `mcpServers` named `seance-snmp`.
4. THE Kiro_MCP_Config SHALL set the entry's `command` to `uv` and its `args` to `run`, `python`, `-m` and `apps.snmp`.
5. THE Kiro_MCP_Config SHALL list the tools `list_devices`, `list_points`, `read_point`, `read_points` and `device_health` under `autoApprove`, because every tool is read-only.
6. THE Kiro_MCP_Config SHALL leave the entry enabled and SHALL contain no secret.
7. THE Kiro_MCP_Config SHALL be valid JSON.
8. THE Kiro_MCP_Config SHALL set the console port in the entry's `env` to a value that differs from the default 8080 and from the console port of the `seance-modbus` entry.
9. THE Kiro_MCP_Config SHALL keep the existing `seance-modbus` entry unchanged.
10. WHEN the user has added the entry, THE SNMP_App tests SHALL validate the entry against criteria 3 to 9.
11. WHEN Kiro starts the entry, THE SNMP_App SHALL answer the `list_devices` tool with the three Devices.

### Requirement 11: Protocol-agnostic skeleton

**User Story:** As a maintainer, I want the skeleton to stay free of SNMP, so that the second app proves the design.

#### Acceptance Criteria

1. THE Seance_Skeleton SHALL import neither `pysnmp` nor any module under `apps/`.
2. THE SNMP_App SHALL add no file to `skeleton/` except for the changes under "Skeleton Changes".
3. THE SNMP_App SHALL change no file under `apps/modbus/`.
4. THE SNMP_App SHALL need no change to the Seance_Skeleton beyond the two changes under "Skeleton Changes".
5. IF a further skeleton gap is found while building the SNMP_App, THEN THE SNMP_App tasks SHALL record the gap and stop for a decision, and SHALL NOT edit the skeleton to work around the gap.

### Requirement 12: Testability and project constraints

**User Story:** As a maintainer, I want the app tested without hardware, so that the suite runs anywhere.

#### Acceptance Criteria

1. THE SNMP_App tests SHALL start the Simulator on a free localhost UDP port and make no other network calls.
2. THE SNMP_App SHALL keep its tests in `apps/snmp/tests/`, with one test file per source file, and SHALL add `apps/snmp/tests` to `testpaths` in `pyproject.toml`.
3. THE SNMP_App SHALL keep its property-based tests in files named `test_*_properties.py`.
4. THE SNMP_App tests SHALL share one module-scoped Simulator and SHALL create no event loop per test, per example or per tool call.
5. THE SNMP_App SHALL declare `pysnmp` as a dependency in `pyproject.toml`, after the current pysnmp documentation has been checked for the API in use.
6. THE SNMP_App SHALL define every test task as required, with no optional tasks.
7. THE SNMP_App SHALL give every public function type hints and SHALL NOT use `Any` in a public signature.
8. THE SNMP_App source files and documents SHALL use UTF-8 with ASCII characters only.
9. WHEN `uv run ruff check .` and `uv run ruff format --check .` are run, THE SNMP_App SHALL pass both.
10. THE SNMP_App SHALL be verified by the full test suite on GitHub Actions, and local verification SHALL be limited to ruff and at most one targeted pytest file per run.

## Skeleton Changes

The SNMP_App works with the skeleton's public interface as it is, with two exceptions. Each is generic and protocol-agnostic, additive, and its own task with its own tests, as `AdapterReadError` was. Neither mentions SNMP, and neither imports pysnmp.

### Skeleton change 1: unsigned 64-bit data type

Why it is needed: SNMP Counter64 values (the uplink and wan octet counters) exceed 32 bits. `DataType` and the Codec have no 64-bit type.

Proposed change: add `DataType.UINT64` (`"uint64"`), 8 bytes, big-endian, range 0 to 2^64-1. THE Codec SHALL decode, encode and report the required length for it, and the Config_Loader SHALL accept it. The round-trip property SHALL cover `uint64`, and scaling SHALL keep the sign of the value. Existing types and signatures do not change.

### Skeleton change 2: value labels

Why it is needed: an integer status such as ifOperStatus (1 up, 2 down) should read as `up` or `down` for the agent. `PointConfig` has no way to name integer values, and `bool` accepts only the bytes 0 and 1.

Proposed change: add an optional field `labels: tuple[tuple[int, str], ...] | None = None` to `PointConfig`, read from an optional YAML `labels` map of integer to non-empty text. Labels are allowed on integer data types only. WHEN a Point has labels and the decoded, unscaled integer is in the map, THE Tool_Server SHALL return the text as `value`. Otherwise the Tool_Server SHALL return the integer. The Config_Loader SHALL reject labels on bool and float32 points and empty text, with a message that names the file, the device and the field. The change needs skeleton tests, including that the Audit_Log still receives exactly one entry per call. Existing configs behave as before.

Acceptance criteria for the change:

1. WHEN a Point has Value_Labels and its decoded, unscaled integer is in the map, THE Tool_Server SHALL return the mapped text as the value of the Point and the decoded integer as the raw value of the Point in the same tool result.
2. IF a Point has Value_Labels and its decoded, unscaled integer is not in the map, THEN THE Tool_Server SHALL return the integer as the value of the Point, without an error, and without a label.
3. WHERE a Point has no Value_Labels, THE Tool_Server SHALL return the same tool result as before this change.
4. IF Value_Labels are given on a bool or float32 Point or with an empty text, THEN THE Config_Loader SHALL reject the config with a message that names the file, the device and the field.
5. WHEN a Point with Value_Labels is read, THE Audit_Log SHALL contain exactly one entry for that call.

## Correctness Properties for Property-Based Tests

These properties are carried forward for the design and tasks phases.

1. For every sequence of valid tool calls, the Simulator never observes a SET PDU, and observes only GET PDUs (Requirements 6.1 and 6.2).
2. For every Point and every Simulator state, the value returned by `read_point` equals the Simulator's value after decoding, scaling and labeling (Requirements 2.7 and 7.12).
3. For every valid SNMP_Address text, parsing then formatting returns the same text (Requirement 3.3).
4. For every `uint64` value, decoding then encoding returns the original bytes (Skeleton change 1).
5. For every Point with labels and every integer, the value returned is the mapped text if the integer is in the map, and the integer otherwise with no error. When the integer is in the map, the result also carries the raw integer, equal to the input (Requirement 5.1 and 5.2, Skeleton change 2).

One plain test, not a property, checks that the SNMP_App and the Modbus_App expose exactly the same five tool names (Requirement 8).

## Task Ordering Guidance

For the tasks phase, order the work as follows:

1. The Simulator, with its tests.
2. Checkpoint.
3. The skeleton changes, each as its own task with its own tests: `uint64` first, then labels.
4. Checkpoint.
5. The Address_Parser, then the SNMP_Adapter.
6. Checkpoint.
7. The SNMP_Config and its config tests.
8. The Entry_Point.
9. Checkpoint.
10. The README.
11. The Kiro_MCP_Config: print the `seance-snmp` entry for the user to add, then write the tests for it.
12. Final checkpoint.

Each task must leave the test suite passing on GitHub Actions. Every test task is required. Local runs are limited to ruff and one targeted pytest file, and the full suite is never run locally.
