# Implementation Plan: Modbus App

## Overview

The work follows the order set for this spec: the Simulator first, then the skeleton change `AdapterReadError` as its own task (it must land before the adapter), then the Address_Parser and the Modbus_Adapter, then the Modbus_Config, then the Entry_Point, then the README, then the Kiro_MCP_Config. Python 3.12 is the implementation language, as in the design. Every test task is required. Each task leaves `uv run pytest`, `uv run ruff check .` and `uv run ruff format --check .` passing.

## Tasks

- [x] 1. Build the Simulator
  - [x] 1.1 Create the app package and the Simulator memory map
    - Create `apps/modbus/__init__.py` and `apps/modbus/tests/__init__.py` if the repo layout needs them
    - Create `apps/modbus/simulator.py` with a `Simulator(host, port, seed)` class built on the pymodbus simulator datastore
    - Check the current pymodbus documentation for `SimData`, `SimDevice` and the server start and stop calls before writing code
    - Define three devices on unit ids: `mixing_tank`, `feed_pump`, `chiller`, each with coil, discrete, holding and input tables
    - Store uint16, int16, uint32 and float32 values with the high word first and each word big-endian
    - Run the server on a background thread, start and stop methods, and a `function_codes_seen` thread-safe record of every function code received
    - Undefined offsets and function codes outside 1 to 4 must get pymodbus exception responses
    - Type hints on every public function, no `Any`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.9, 1.10, 6.2, 10.6_

  - [x] 1.2 Add drift, seeding, the low-level flag and clean stop
    - A drift thread changes each analog value at least once per second by a bounded random step, clamped to its declared minimum and maximum
    - Seed a private random generator from the constructor so equal seeds give equal sequences
    - Set the mixing tank low-level discrete input when the level falls below its low limit, and clear it when the level rises above
    - `stop()` releases the port and joins the drift thread within 2 seconds
    - Expose a way to read and set a point value in the Simulator's memory, for tests
    - _Requirements: 1.5, 1.6, 1.7, 1.8, 1.11_

  - [x] 1.3 Write unit tests in `apps/modbus/tests/test_simulator.py`
    - Start the Simulator on a free localhost port picked at test setup, make no other network call
    - Three devices answer on their unit ids
    - An undefined offset answers "illegal data address" and an unsupported function code answers "illegal function"
    - Drift keeps every value inside its bounds, and equal seeds give equal sequences
    - The low-level discrete input follows the level
    - `stop()` returns within 2 seconds and the port can be bound again
    - `function_codes_seen` records the codes of the requests sent
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 6.2, 10.1, 10.2_

- [x] 2. Checkpoint - Simulator
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Skeleton change: AdapterReadError
  - [x] 3.1 Add `AdapterReadError` and handle it in the Tool_Server
    - In `skeleton/seance/adapter.py` add `AdapterReadError(message: str)` as an additive exception class
    - In `skeleton/seance/server.py`, when an adapter raises `AdapterReadError`, return its message as the tool result with outcome `adapter_error`, clipped to one line and a maximum length
    - Any other exception keeps today's generic sentence
    - No existing signature changes, and the skeleton must not import from `apps/` or import `pymodbus` or `pysnmp`
    - _Requirements: 5.1, 5.2, 5.4, 10.5, Skeleton change 1_

  - [x] 3.2 Write skeleton unit tests
    - In `skeleton/tests/test_adapter.py` test that `AdapterReadError` carries its message
    - In `skeleton/tests/test_server.py` test that the message is returned with outcome `adapter_error`, that multi-line and very long messages are clipped, that other exceptions still give the generic sentence, and that the audit log gets exactly one entry for the call
    - Use a fake adapter and no network
    - _Requirements: 5.1, 5.2, 5.4, 5.5, Skeleton change 1_

- [x] 4. Checkpoint - Skeleton change
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement the Address_Parser and Address_Formatter
  - [x] 5.1 Create `apps/modbus/address.py`
    - Define `Table` (StrEnum), the frozen `ModbusAddress` dataclass and `AddressError`
    - `parse_address(text)` requires exactly three colon-separated parts, then validates unit, table and offset in that order
    - Unit and offset are decimal with no leading zeros, ranges 1 to 247 and 0 to 65535
    - Error sentences name the field and the allowed range, list the four tables, or show `<unit>:<table>:<offset>`
    - `format_address(address)` returns `<unit>:<table>:<offset>`
    - _Requirements: 3.1, 3.2, 3.4, 3.5, 3.6, 3.7, 10.6_

  - [x] 5.2 Write unit tests in `apps/modbus/tests/test_address.py`
    - Concrete valid addresses for each table and the boundary values 1, 247, 0 and 65535
    - Concrete malformed addresses with the exact expected message content for each of the four error kinds, plus leading zeros and non-numeric parts
    - _Requirements: 3.1, 3.2, 3.4, 3.5, 3.6, 3.7_

  - [x] 5.3 Write property test for address round-trip in `apps/modbus/tests/test_address_properties.py`
    - **Property 1: Address round-trip**
    - Tag with `Feature: app-modbus, Property 1`
    - Run at least 100 examples
    - **Validates: Requirements 3.3**

  - [x] 5.4 Write property test for invalid address text in `apps/modbus/tests/test_address_properties.py`
    - **Property 4: Invalid address text is rejected with a field-naming sentence**
    - Tag with `Feature: app-modbus, Property 4`
    - Generate text malformed in exactly one of: part count, unit range, offset range, table name
    - **Validates: Requirements 3.4, 3.5, 3.6, 3.7**

- [x] 6. Implement the Modbus_Adapter
  - [x] 6.1 Create `apps/modbus/adapter.py`
    - Check the current pymodbus client documentation for method names and the `device_id` parameter before writing code
    - `ModbusAdapter(host, port)` implements `connect`, `close`, `read` and `health` of `ProtocolAdapter` and no write method
    - `read` parses the address, checks that the data type fits the table (`bool` only with `coil` and `discrete`, the other four types only with `holding` and `input`), and calls `read_coils`, `read_discrete_inputs`, `read_holding_registers` or `read_input_registers` (function codes 1, 2, 3, 4)
    - Use `seance.codec.required_length` for the byte count, pack registers high word first and each word big-endian, pack a bit into one byte
    - Apply the device timeout, with 2 seconds as the default
    - Raise `AdapterReadError` with short sentences for a bad address, a data type that does not fit the table, an illegal data address (outside the Device's range) and other Modbus exceptions in plain words, never with a pymodbus class name or stack trace
    - `health` reads the first configured point and returns `ok`, `degraded` (exception response) or `unreachable` (no answer)
    - Import nothing from `apps/` except `apps/modbus/address.py`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.7, 2.8, 2.9, 2.10, 2.11, 2.12, 3.8, 5.1, 5.2, 5.4, 10.6_

  - [x] 6.2 Write unit tests in `apps/modbus/tests/test_adapter.py`
    - One read per table showing the right function code, using `Simulator.function_codes_seen`
    - All 24 data type and table combinations, as a parametrized test, with the expected fit or the error naming point, type and table
    - The three `health` outcomes against a running Simulator, a Simulator that answers with an exception, and a stopped Simulator
    - Illegal data address and other exception sentences name the device and the point and contain no pymodbus class name
    - A source scan test that `pymodbus` is imported only by `apps/modbus/adapter.py` and `apps/modbus/simulator.py` and that no file under `apps/modbus/` calls a pymodbus write method
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.7, 2.9, 2.10, 2.11, 2.12, 3.8, 5.1, 5.2, 5.4, 6.4_

  - [x] 6.3 Write property test for adapter reads in `apps/modbus/tests/test_adapter_properties.py`
    - **Property 2: Adapter reads match the simulator's memory**
    - Tag with `Feature: app-modbus, Property 2`
    - Generate in-range values for uint16, int16, uint32, float32 and bool, set them in the Simulator memory, read through the adapter, and compare with the value decoded and scaled directly from the memory
    - **Validates: Requirements 2.6, 7.12**

  - [x] 6.4 Write property test for read-only behavior in `apps/modbus/tests/test_readonly_properties.py`
    - **Property 3: The Simulator observes only read function codes**
    - Tag with `Feature: app-modbus, Property 3`
    - Drive a `ToolServer` wired to the real adapter and a running Simulator with generated tool names and argument sets, including write-shaped ones, and assert that `function_codes_seen` is a subset of 1 to 4 and that a guard-rejected call adds no request
    - **Validates: Requirements 6.1, 6.2, 6.3**

- [x] 7. Checkpoint - Address parser and adapter
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Write the Modbus_Config
  - [x] 8.1 Create `apps/modbus/devices.yaml`
    - Define `mixing_tank`, `feed_pump` and `chiller` with 11 to 13 points in total
    - Every point has a name, address in `<unit>:<table>:<offset>` form, data type and a non-empty unit
    - At least one point per table and one per data type (uint16, int16, uint32, float32)
    - Scale greater than zero where a register needs conversion
    - Addresses and types must match the Simulator memory map
    - Use ASCII only
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.10, 10.7_

  - [x] 8.2 Write unit tests in `apps/modbus/tests/test_config.py`
    - Load the shipped file with `seance.config.load_config`
    - Assert the three devices, the point count, table and data type coverage, positive scales, non-empty units and that every address parses
    - Assert that every point reads through the adapter from a running Simulator without error, so the file and the Simulator memory map agree
    - Assert that a bad field gives one message naming the file, the device and the field
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10_

- [x] 9. Implement the Entry_Point
  - [x] 9.1 Create `apps/modbus/__main__.py`
    - Read `SEANCE_MODBUS_HOST` (127.0.0.1), `SEANCE_MODBUS_PORT` (5020), `SEANCE_CONSOLE_HOST` (127.0.0.1) and `SEANCE_CONSOLE_PORT` (8080)
    - A port that is not an integer from 1 to 65535 stops before serving with one message naming the variable and the range
    - Start the Simulator, then build the adapter and call `load_config`, `build_tool_server` and `serve`, in that order
    - Parse every point address at startup and stop with one message naming the device, the point and the reason
    - A port already in use stops with one message naming the port and suggesting `SEANCE_MODBUS_PORT`
    - Send every log and message to standard error
    - When the MCP server stops, stop the console and the Simulator and exit
    - Needs no secret and makes no network call beyond its own host
    - _Requirements: 4.7, 4.8, 4.9, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.10, 10.6_

  - [x] 9.2 Write unit tests in `apps/modbus/tests/test___main__.py`
    - Defaults and overrides of the four environment variables
    - Invalid ports (text, 0, 65536) give one message naming the variable and the range
    - A port in use gives one message naming the port and `SEANCE_MODBUS_PORT`
    - An invalid address in a config gives one message naming device, point and reason
    - Startup order and shutdown order, with the MCP stdio loop replaced by a fake
    - Nothing is written to standard output by the Entry_Point itself
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.7, 7.8, 7.9, 7.10, 4.9_

  - [x] 9.3 Write integration tests in `apps/modbus/tests/test_server_integration.py`
    - Use the skeleton `ToolServer` with the real adapter, `devices.yaml` and a running Simulator on a free port
    - `list_devices` returns three devices, `read_point` returns the value, unit and timestamp, equal to the decoded Simulator memory, and `device_health` returns `ok`
    - A point outside the Device's range gives one sentence naming the device and the point
    - With the Simulator stopped, each read returns the Timeout_Sentence within the device timeout
    - Every failed call leaves exactly one audit entry with the failure outcome, and no result contains a stack trace or a pymodbus class name
    - The console shows the three devices with live values within 5 seconds of start
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 7.11, 7.12, 9.8_

- [ ] 10. Checkpoint - Config and Entry_Point
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Write the README
  - [ ] 11.1 Create `apps/modbus/README.md`
    - State the command `uv run python -m apps.modbus` and the four environment variables with their defaults
    - List every point with device, name, address, data type, unit and scale
    - Give three example questions, each with the tool calls that answer it
    - Show how to run the tests of the Modbus app
    - Describe `.kiro/settings/mcp.json` and how to enable it
    - Use ASCII only
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [ ] 11.2 Write unit tests in `apps/modbus/tests/test_readme.py`
    - The README is ASCII only, contains the command and the four variable names with defaults
    - Every point in `devices.yaml` appears in the README with its address, type, unit and scale
    - Three example questions each name existing tool names
    - The README mentions the test command and `mcp.json`
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

- [ ] 12. Add the Kiro_MCP_Config
  - [ ] 12.1 Create `.kiro/settings/mcp.json`
    - One entry `seance-modbus` under `mcpServers`, with `command` `uv` and `args` `run`, `python`, `-m`, `apps.modbus`
    - `autoApprove` lists `list_devices`, `list_points`, `read_point`, `read_points` and `device_health`
    - The entry is enabled, has no secret, and sets `SEANCE_CONSOLE_PORT` in `env` to a value other than 8080
    - Valid JSON, ASCII only, and no change to `.gitignore` that hides `.kiro`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_

  - [ ] 12.2 Write unit tests in `apps/modbus/tests/test_mcp_config.py`
    - Parse the file and assert each point of requirement 9, including that the console port differs from the default and that no value looks like a secret
    - Assert that `.gitignore` does not list `.kiro`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_

- [ ] 13. Final checkpoint - Ensure all tests pass
  - Run `uv run pytest`, `uv run ruff check .` and `uv run ruff format --check .`
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 10.8_

## Notes

- Every test task is required. This spec has no optional tasks.
- Commit messages use the imperative mood and name the spec task, for example `Add Simulator drift and seeding (app-modbus task 1.2)`.
- Test files mirror source files. Property tests live in `test_*_properties.py`.
- All sources and documents use UTF-8 with ASCII characters only.
- Tests start the Simulator on a free localhost port and make no other network call.
- Task 3 changes only the skeleton, additively, and must land before task 6.
- Property tests validate universal properties. Unit tests validate examples and edge cases.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3"] },
    { "id": 3, "tasks": ["2"] },
    { "id": 4, "tasks": ["3.1"] },
    { "id": 5, "tasks": ["3.2"] },
    { "id": 6, "tasks": ["4"] },
    { "id": 7, "tasks": ["5.1"] },
    { "id": 8, "tasks": ["5.2", "6.1"] },
    { "id": 9, "tasks": ["5.3", "6.2"] },
    { "id": 10, "tasks": ["5.4", "6.3"] },
    { "id": 11, "tasks": ["6.4"] },
    { "id": 12, "tasks": ["7"] },
    { "id": 13, "tasks": ["8.1"] },
    { "id": 14, "tasks": ["8.2", "9.1"] },
    { "id": 15, "tasks": ["9.2", "9.3"] },
    { "id": 16, "tasks": ["10"] },
    { "id": 17, "tasks": ["11.1", "12.1"] },
    { "id": 18, "tasks": ["11.2", "12.2"] },
    { "id": 19, "tasks": ["13"] }
  ]
}
```
