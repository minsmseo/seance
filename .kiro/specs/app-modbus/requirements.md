# Requirements Document

## Introduction

The Modbus app is the first application built on the Seance skeleton. It lives in `apps/modbus/` and exposes a simulated batch mixing line over Modbus TCP. The line has three devices: a mixing tank, a feed pump and a chiller. One command starts the simulator, the MCP server and the web console together, so anyone can ask a forty-year-old protocol what it is doing without hardware.

The app is read-only. The adapter sends only Modbus read function codes 1, 2, 3 and 4. The adapter is the only file that imports `pymodbus`. The app uses the skeleton's public interface as it is: `ProtocolAdapter`, `PointConfig`, `DeviceConfig`, `load_config`, `build_tool_server` and `serve`. The one skeleton gap found while writing these requirements is listed under "Skeleton Changes" and is a separate task.

## Glossary

- **Seance_Skeleton**: The code in `skeleton/seance/` that provides the Tool_Server, Codec, Read_Only_Guard, Audit_Log, Config_Loader and Web_Console.
- **Modbus_App**: The application in `apps/modbus/`, made of the Simulator, the Modbus_Adapter, the Modbus_Config and the Entry_Point.
- **Simulator**: The Modbus TCP server in `apps/modbus/simulator.py`, built with pymodbus, that simulates the batch mixing line.
- **Modbus_Adapter**: The `ProtocolAdapter` implementation in `apps/modbus/adapter.py`. It is the only file in the repository that imports pymodbus.
- **Modbus_Config**: The YAML file `apps/modbus/devices.yaml` that describes the three devices and their points.
- **Entry_Point**: The module `apps/modbus/__main__.py`, started with `uv run python -m apps.modbus`.
- **Device**: One of Mixing_Tank, Feed_Pump or Chiller. Each Device has its own Modbus unit id on the one Simulator.
- **Mixing_Tank**: The Device named `mixing_tank` that holds the batch and reports level, temperature and agitator state.
- **Feed_Pump**: The Device named `feed_pump` that moves material into the Mixing_Tank.
- **Chiller**: The Device named `chiller` that cools the Mixing_Tank.
- **Point**: One readable value of a Device, as defined by `PointConfig` in the Seance_Skeleton.
- **Modbus_Address**: The text in the `address` field of a Point, in the form `<unit>:<table>:<offset>`. `<unit>` is a decimal unit id from 1 to 247. `<table>` is one of `coil`, `discrete`, `input` or `holding`. `<offset>` is a decimal register or bit offset from 0 to 65535. Neither `<unit>` nor `<offset>` has leading zeros.
- **Table**: One of the four Modbus data tables: coils (function code 1), discrete inputs (function code 2), holding registers (function code 3) and input registers (function code 4).
- **Read_Function_Code**: One of the Modbus function codes 1, 2, 3 and 4.
- **Register_Word_Order**: The order of the two 16-bit registers of a 32-bit value. The Modbus_App uses the high word first, and each word is big-endian.
- **Address_Parser**: The function in the Modbus_App that turns Modbus_Address text into a unit id, a Table and an offset, or returns an error sentence.
- **Address_Formatter**: The function in the Modbus_App that turns a unit id, a Table and an offset into Modbus_Address text.
- **Audit_Log**: The Seance_Skeleton record of one entry per tool call.
- **Drift**: A slow, bounded change of a simulated value over time.
- **Tool_Server**: The Seance_Skeleton component that serves the tools `list_devices`, `list_points`, `read_point`, `read_points` and `device_health`.
- **Web_Console**: The Seance_Skeleton web page that shows devices, values and the audit log.
- **Timeout_Sentence**: The sentence the Tool_Server returns when a device does not answer within the device's configured timeout.
- **Kiro_MCP_Config**: The workspace file `.kiro/settings/mcp.json` that lets Kiro start the Modbus_App as an MCP server.
- **Example_Question**: A question in the README that an agent can answer with the tools of the Modbus_App.

## Requirements

### Requirement 1: Simulated batch mixing line

**User Story:** As a developer without hardware, I want a simulated Modbus line that behaves plausibly, so that I can try the app anywhere.

#### Acceptance Criteria

1. THE Simulator SHALL serve Modbus TCP on a host and port given at construction.
2. THE Simulator SHALL simulate exactly three Devices: Mixing_Tank, Feed_Pump and Chiller, each on its own unit id.
3. THE Simulator SHALL expose holding registers, input registers, coils and discrete inputs.
4. THE Simulator SHALL store values of the types uint16, int16, uint32 and float32 using the Register_Word_Order.
5. WHILE the Simulator runs, THE Simulator SHALL apply Drift to the analog values of every Device at least once per second.
6. WHILE the Simulator runs, THE Simulator SHALL keep every drifting value inside the minimum and maximum declared for that value.
7. WHEN the Simulator is started with a given random seed, THE Simulator SHALL produce the same sequence of values as every other run with that seed.
8. WHEN a Mixing_Tank level falls below its low limit, THE Simulator SHALL set the Mixing_Tank low-level discrete input.
9. WHEN a read request addresses a Table offset that the Device does not define, THE Simulator SHALL answer with the Modbus exception "illegal data address".
10. WHEN a request carries a function code other than 1, 2, 3 or 4, THE Simulator SHALL answer with the Modbus exception "illegal function".
11. WHEN the Simulator is stopped, THE Simulator SHALL release its port and stop its Drift thread within 2 seconds.

### Requirement 2: Modbus read adapter

**User Story:** As a plant engineer, I want the adapter to read values and nothing else, so that no tool call can change a running machine.

#### Acceptance Criteria

1. THE Modbus_Adapter SHALL implement the `connect`, `close`, `read` and `health` methods of `ProtocolAdapter`.
2. THE Modbus_Adapter SHALL implement no method that writes to a device.
3. THE Modbus_Adapter SHALL send only Read_Function_Codes.
4. WHEN `read` is called for a Point whose Table is `coil`, `discrete`, `holding` or `input`, THE Modbus_Adapter SHALL send function code 1, 2, 3 or 4 respectively.
5. WHEN `read` is called, THE Modbus_Adapter SHALL return the raw bytes of the Point, big-endian, with the length that the Codec requires for the Point's data type.
6. WHEN `read` returns bytes for a Point, THE Seance_Skeleton Codec and scale SHALL produce a value equal to the value decoded and scaled directly from the Simulator's memory for that Point.
7. WHEN `health` is called for a Device, THE Modbus_Adapter SHALL return `ok` if the Device answers a read of its first configured Point, `degraded` if the Device answers with a Modbus exception, and `unreachable` if the Device does not answer.
8. THE Modbus_Adapter SHALL apply a timeout of 2 seconds to every Modbus request unless the Device configures another timeout.
9. WHEN `connect` is called, THE Modbus_Adapter SHALL open its connection to the configured host and port.
10. WHEN `close` is called, THE Modbus_Adapter SHALL close its connection and release its resources.
11. THE Modbus_Adapter SHALL be the only file in the repository that imports `pymodbus`.
12. THE Modbus_Adapter SHALL import nothing from other files in `apps/` except the Modbus_Address parser of the Modbus_App.

### Requirement 3: Modbus address parsing and formatting

**User Story:** As an operator, I want Modbus addresses written in one plain form, so that I can read and edit the config without a manual.

#### Acceptance Criteria

1. WHEN a valid Modbus_Address text is given, THE Address_Parser SHALL return its unit id, Table and offset.
2. THE Address_Formatter SHALL format a unit id, a Table and an offset into a Modbus_Address text.
3. FOR ALL valid Modbus_Address texts, parsing then formatting then parsing SHALL return the same unit id, Table and offset, and formatting SHALL return the original text (round-trip property).
4. IF a Modbus_Address text has a unit id outside 1 to 247, THEN THE Address_Parser SHALL return an error sentence that names the field `unit` and the allowed range.
5. IF a Modbus_Address text has an offset outside 0 to 65535, THEN THE Address_Parser SHALL return an error sentence that names the field `offset` and the allowed range.
6. IF a Modbus_Address text has a Table other than `coil`, `discrete`, `input` or `holding`, THEN THE Address_Parser SHALL return an error sentence that lists the four allowed Tables.
7. IF a Modbus_Address text does not have exactly three colon-separated parts, THEN THE Address_Parser SHALL return an error sentence that shows the form `<unit>:<table>:<offset>`.
8. IF the data type of a Point does not fit its Table, THEN THE Modbus_Adapter SHALL return an error sentence that names the Point, the data type and the Table. The `bool` type fits only `coil` and `discrete`. The types int16, uint16, uint32 and float32 fit only `holding` and `input`.

### Requirement 4: Point configuration

**User Story:** As an operator, I want the three devices and their points described in YAML, so that I can add a sensor without editing code.

#### Acceptance Criteria

1. THE Modbus_Config SHALL define the three Devices `mixing_tank`, `feed_pump` and `chiller`.
2. THE Modbus_Config SHALL define between 11 and 13 Points in total.
3. THE Modbus_Config SHALL give every Point a name, a Modbus_Address, a data type and a unit.
4. WHERE a raw register value needs conversion to an engineering unit, THE Modbus_Config SHALL give the Point a scale greater than zero.
5. THE Modbus_Config SHALL include at least one Point of each Table.
6. THE Modbus_Config SHALL include at least one Point of each data type: uint16, int16, uint32 and float32.
7. WHEN the Modbus_App starts, THE Modbus_App SHALL load the Modbus_Config with the Seance_Skeleton Config_Loader.
8. IF the Modbus_Config has an invalid field, THEN THE Modbus_App SHALL stop before serving and print one message that names the file, the Device and the field.
9. WHEN the Modbus_App starts, THE Modbus_App SHALL parse the Modbus_Address of every Point and IF any is invalid, THEN THE Modbus_App SHALL stop before serving and print one message that names the Device, the Point and the reason.
10. THE Modbus_Config SHALL contain no unit that is empty text.

### Requirement 5: Out-of-range and failed reads

**User Story:** As an agent, I want a short sentence when a read fails, so that I know what to try next.

#### Acceptance Criteria

1. IF a Point's offset lies outside the register range that the Device defines, THEN THE Tool_Server SHALL return one sentence that names the Device and the Point and says the address is outside the Device's range.
2. IF the Simulator answers a read with a Modbus exception other than "illegal data address", THEN THE Tool_Server SHALL return one sentence that names the Device and the Point and states the exception in plain words.
3. WHILE the Simulator is stopped, THE Tool_Server SHALL return the Seance_Skeleton Timeout_Sentence for every read within the Device's configured timeout.
4. IF a read fails, THEN THE Tool_Server SHALL return a sentence that contains no stack trace and no pymodbus class name.
5. WHEN a read fails, THE Audit_Log SHALL contain exactly one entry for that call with the outcome of the failure.

### Requirement 6: Read-only behavior on the wire

**User Story:** As a plant engineer, I want proof that the app cannot write, so that I can trust it near real equipment.

#### Acceptance Criteria

1. FOR ALL sequences of tool calls, THE Simulator SHALL observe only Read_Function_Codes.
2. THE Simulator SHALL record the function code of every request it receives, for use by tests.
3. WHEN a write tool name or a write argument set reaches the Tool_Server, THE Simulator SHALL receive zero requests for that call.
4. THE Modbus_App SHALL contain no call to a pymodbus write method in any file.

### Requirement 7: Entry point

**User Story:** As a judge or a new user, I want one command that starts everything, so that I can see it work in seconds.

#### Acceptance Criteria

1. WHEN `uv run python -m apps.modbus` is run, THE Entry_Point SHALL start the Simulator, the MCP server and the Web_Console in that order.
2. THE Entry_Point SHALL read the Simulator host from the environment variable `SEANCE_MODBUS_HOST` and use `127.0.0.1` when it is not set.
3. THE Entry_Point SHALL read the Simulator port from the environment variable `SEANCE_MODBUS_PORT` and use `5020` when it is not set.
4. THE Entry_Point SHALL read the Web_Console host from the environment variable `SEANCE_CONSOLE_HOST` and use `127.0.0.1` when it is not set.
5. THE Entry_Point SHALL read the Web_Console port from the environment variable `SEANCE_CONSOLE_PORT` and use `8080` when it is not set.
6. THE Entry_Point SHALL need no secret and no network access beyond its own host.
7. IF an environment variable holds a port that is not an integer from 1 to 65535, THEN THE Entry_Point SHALL stop before serving and print one message that names the variable and the allowed range.
8. IF the Simulator port is already in use, THEN THE Entry_Point SHALL stop and print one message that names the port and suggests setting `SEANCE_MODBUS_PORT`.
9. WHILE the MCP server uses standard output for the MCP protocol, THE Entry_Point SHALL write every log and message to standard error.
10. WHEN the MCP server stops, THE Entry_Point SHALL stop the Web_Console and the Simulator and exit.
11. WHEN the Modbus_App starts, THE Web_Console SHALL show the three Devices with live values within 5 seconds.
12. WHEN a Point is read, THE Tool_Server SHALL return a value equal to the Simulator's register contents after decoding and scaling.

### Requirement 8: Documentation

**User Story:** As a new user, I want a README in the app folder, so that I can run and understand the app on its own.

#### Acceptance Criteria

1. THE README SHALL state the command `uv run python -m apps.modbus` and the four environment variables with their defaults.
2. THE README SHALL list every Point with its Device, name, Modbus_Address, data type, unit and scale.
3. THE README SHALL give three Example_Questions that an agent can answer with the tools of the Modbus_App, each with the tool calls that answer it.
4. THE README SHALL show how to run the tests of the Modbus_App.
5. THE README SHALL describe the Kiro_MCP_Config and how to enable it.
6. THE README SHALL contain ASCII characters only.

### Requirement 9: Kiro workspace MCP configuration

**User Story:** As a Kiro user, I want the workspace to know this server, so that Kiro can query the simulated line without manual setup.

#### Acceptance Criteria

1. THE Kiro_MCP_Config SHALL be the file `.kiro/settings/mcp.json` in the workspace root.
2. THE Kiro_MCP_Config SHALL define one entry under `mcpServers` named `seance-modbus`.
3. THE Kiro_MCP_Config SHALL set the entry's `command` to `uv` and its `args` to `run`, `python`, `-m` and `apps.modbus`.
4. THE Kiro_MCP_Config SHALL list the tools `list_devices`, `list_points`, `read_point`, `read_points` and `device_health` under `autoApprove`, because every tool is read-only.
5. THE Kiro_MCP_Config SHALL leave the entry enabled and SHALL contain no secret.
6. THE Kiro_MCP_Config SHALL be valid JSON.
7. THE Kiro_MCP_Config SHALL set the console port in the entry's `env` to a value that differs from the default, so that a console already running does not block Kiro.
8. WHEN Kiro starts the entry, THE Modbus_App SHALL answer the `list_devices` tool with the three Devices.

### Requirement 10: Testability and project constraints

**User Story:** As a maintainer, I want the app tested without hardware, so that the suite runs anywhere.

#### Acceptance Criteria

1. THE Modbus_App tests SHALL start the Simulator on a free localhost port and make no other network calls.
2. THE Modbus_App SHALL keep its tests in `apps/modbus/tests/`, with one test file per source file.
3. THE Modbus_App SHALL keep its property-based tests in files named `test_*_properties.py`.
4. THE Modbus_App SHALL define every test task as required, with no optional tasks.
5. THE Modbus_App SHALL import from the Seance_Skeleton and SHALL NOT change the Seance_Skeleton public interface.
6. THE Modbus_App SHALL give every public function type hints and SHALL NOT use `Any` in a public signature.
7. THE Modbus_App source files and documents SHALL use UTF-8 with ASCII characters only.
8. WHEN `uv run pytest`, `uv run ruff check .` and `uv run ruff format --check .` are run, THE Modbus_App SHALL pass all three.

## Skeleton Changes

The Modbus_App works with the skeleton's public interface as it is, with one exception that must be a separate task.

### Skeleton change 1: pass an adapter's short failure sentence to the agent

Why it is needed: when `ProtocolAdapter.read` raises, `ToolServer._with_timeout` returns "<device> read failed: the adapter reported an error." That sentence names the Device but not the Point, and it cannot say that the address is outside the Device's range. Requirement 5.1 and the acceptance criterion "WHEN a register address in the config is outside the device's range THEN the tool SHALL return a short sentence naming the device and the point" cannot be met without a way for an adapter to supply its own sentence.

Proposed change, kept additive: add one exception class, `AdapterReadError(message: str)`, to `skeleton/seance/adapter.py`. WHEN an adapter raises `AdapterReadError`, THE Tool_Server SHALL return the message as the tool result with outcome `adapter_error`, clipped to one line and a maximum length. Any other exception SHALL keep today's generic sentence. No existing signature changes, and adapters that do not use it behave as before. The change needs skeleton tests, including that the audit log still receives exactly one entry.

## Correctness Properties for Property-Based Tests

These properties are carried forward for the design and tasks phases.

1. For every sequence of tool calls, the Simulator observes only function codes 1 to 4 (Requirement 6.1).
2. For every supported data type and every register content, the value read through the Modbus_Adapter equals the value decoded directly from the Simulator's memory (Requirement 2.6).
3. For every valid Modbus_Address text, parsing then formatting returns the same text (Requirement 3.3).

## Task Ordering Guidance

For the tasks phase, order the work as follows: the Simulator first, then the skeleton change as its own task (it unblocks Requirement 5.1 and must land before the adapter), then the Address_Parser and the Modbus_Adapter, then the Modbus_Config, then the Entry_Point, then the README, then the Kiro_MCP_Config. Each task must leave the test suite passing. Every test task is required.
