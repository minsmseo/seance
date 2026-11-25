# Implementation Plan: SNMP App

## Overview

The work follows the order set for this spec: the Simulator first, then a checkpoint, then the two skeleton changes (`uint64`, then value labels), each as its own task with its own tests, then a checkpoint, then the Address_Parser and the SNMP_Adapter, then a checkpoint, then the SNMP_Config, the Entry_Point, a checkpoint, the README, the Kiro_MCP_Config, and a final checkpoint. Python 3.12 is the implementation language, as in the design. Every test task is required.

Verification rules for every task:

- Run `uv run ruff check .` and `uv run ruff format --check .` locally.
- Run at most one targeted pytest file, once, and only when the task says so. Never run the full suite locally and never retry after WinError 10014.
- Checkpoints rely on the GitHub Actions (ubuntu) run, which executes the full suite.
- Never run pysnmp locally. Its behavior is verified on GitHub Actions only.

## Tasks

- [x] 1. Build the Simulator
  - [x] 1.1 Create the app package, the OID map and the v2c responder
    - Create `apps/snmp/__init__.py` and `apps/snmp/tests/__init__.py` if the repo layout needs them
    - Add `apps/snmp/tests` to `testpaths` in `pyproject.toml`
    - Create `apps/snmp/simulator.py` with `PduType`, `PduRecord`, `OidEntry`, `SimulatorError` and the single `OidEntry` tuple holding the 19 OIDs, types, initial values, ranges and steps from the design table
    - Write the small BER codec for SNMP v2c: PDUs GET, GETNEXT, SET, GETBULK and the response PDU, and value types Integer32, Counter32, Gauge32, TimeTicks, Counter64, noSuchObject, noSuchInstance and endOfMibView
    - Write `encode_request` and `decode_response` in this file, so that no other file builds a SET PDU
    - Write the request handling: drop malformed datagrams and wrong versions without recording them, record a `PduRecord` for every decoded request, send nothing for an unknown community, answer GET (noSuchObject for an undefined OID), GETNEXT, GETBULK (capped at 20 varbinds), and answer SET with error-status `notWritable` and no state change
    - Do not import `pysnmp`. Type hints on every public function, no `Any`
    - _Requirements: 1.1, 1.2, 1.4, 1.8, 1.9, 1.10, 1.11, 1.12, 4.15, 12.7, 12.8_

  - [x] 1.2 Add drift, seeding, lifecycle and test helpers
    - `Simulator(host, port, seed, drift=True)` with `host`, `port`, `seed`, `running` and `pdus_seen`
    - `drift_step()` takes the state lock and applies the rules in the design table: bounded random step for gauges and integers, non-negative step with wraparound for counters, plus 50 ticks for TimeTicks, status values unchanged
    - One `random.Random(seed)`, drawn in map order, so equal seeds give equal sequences
    - Run one asyncio loop on one daemon thread per Simulator, a UDP endpoint without address reuse, and the drift as one asyncio task that runs every 0.5 seconds unless `drift=False`
    - `start()` accepts port 0 and reports the real port, raises `SimulatorError` on a second start, and turns a busy port into the message "Port N is already in use. Try another port."
    - `stop()` cancels the drift task, closes the transport, stops and closes the loop and joins the thread within 2 seconds
    - `get_value` and `set_value` (clamped) for tests
    - _Requirements: 1.3, 1.5, 1.6, 1.7, 1.13, 1.14, 1.15, 7.8_

  - [x] 1.3 Write unit tests in `apps/snmp/tests/test_simulator.py`
    - Share one module-scoped Simulator on a free localhost UDP port, make no other network call, and create no event loop per test
    - Three devices answer by community, and an unknown community gets silence
    - An undefined OID gets noSuchObject
    - GET, GETNEXT and GETBULK answers, including endOfMibView and the 20-varbind cap
    - A SET gets `notWritable` and changes nothing
    - The PDU record lists every request type in order, and a malformed datagram is not recorded
    - The Default_Seed reports port 3 of `core_switch` as 2 and every other status as healthy
    - Drift changes values at least once per second
    - `stop()` returns within 2 seconds, a new Simulator binds the same port at once, a second `start()` raises, and a busy port gives the message naming the port
    - _Requirements: 1.1, 1.2, 1.4, 1.5, 1.8, 1.9, 1.10, 1.11, 1.12, 1.13, 1.14, 1.15, 12.1, 12.4_

  - [x] 1.4 Write property tests in `apps/snmp/tests/test_simulator_properties.py`
    - **Property 7: BER values round trip**
    - **Validates: Requirements 1.9, 1.10**
    - **Property 8: Drift is deterministic, bounded and monotonic**
    - **Validates: Requirements 1.3, 1.6, 1.7**
    - Tag each test with `Feature: app-snmp, Property N`, run at least 100 examples, and use no socket and no event loop
    - Property 8 drives `drift_step()` on an unstarted Simulator for 0 to 200 steps

- [x] 2. Checkpoint - Simulator
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Skeleton change: `uint64`
  - [x] 3.1 Add `DataType.UINT64` to the points model and the Codec
    - In `skeleton/seance/points.py` add `UINT64 = "uint64"`
    - In `skeleton/seance/codec.py` add length 8, format `>Q` and range 0 to 2**64 - 1
    - Check that `skeleton/seance/config.py` needs no change and that its error message lists `uint64`
    - Change nothing that mentions SNMP, and import no protocol library
    - _Requirements: Skeleton change 1, 4.9, 5.4, 11.1, 11.4_

  - [x] 3.2 Write skeleton unit tests
    - In `skeleton/tests/test_codec.py` test decode, encode and required length for `uint64` at 0 and 2**64 - 1, and that a value above the range and bytes of the wrong length are rejected
    - In `skeleton/tests/test_config.py` test that `type: uint64` loads and that the bad-type message lists `uint64`
    - Fix any skeleton test that hard-codes the list of data types
    - Run `uv run pytest skeleton/tests/test_codec.py` once
    - _Requirements: Skeleton change 1_

  - [x] 3.3 Write property tests for `uint64`
    - **Property 4: `uint64` decode then encode returns the original bytes**
    - **Validates: Requirements 4.9, 5.4**
    - In `skeleton/tests/test_codec_properties.py` check that the existing generators over `list(DataType)` cover `uint64`, and add one property that a positive scale never changes the sign of a decoded `uint64` value
    - Tag with `Feature: app-snmp, Property 4`

- [x] 4. Skeleton change: value labels
  - [x] 4.1 Add `labels` to `PointConfig` and the Config_Loader
    - In `skeleton/seance/points.py` add `labels: tuple[tuple[int, str], ...] | None = None` as the last field
    - In `skeleton/seance/config.py` read an optional `labels` map into `(int, str)` pairs in file order, and write it back in `dump_config` in the same order
    - Reject with a `ConfigError` that names the file, the device and `points[<name>].labels`: labels on a `bool` or `float32` point, a key that is not an integer (text or boolean), empty or non-text label text, and an empty map
    - Existing configs without labels load as before
    - _Requirements: Skeleton change 2 (criteria 3, 4), 4.8_

  - [x] 4.2 Apply labels in the Tool_Server
    - In `skeleton/seance/server.py` change `_read_value` so that a decoded `int` (not `bool`) found in the labels returns `value` as the text and a `raw` key with the decoded integer, with the unit kept
    - An unmapped integer and a point without labels return the same keys and values as before
    - The lookup uses the decoded, unscaled integer, and `read_points` uses the same helper
    - `ToolServer.call` still writes exactly one audit entry
    - _Requirements: 5.1, 5.2, Skeleton change 2 (criteria 1, 2, 3, 5)_

  - [x] 4.3 Write skeleton unit tests
    - In `skeleton/tests/test_config.py` test the loader rejections (bool point, float32 point, non-integer key, boolean key, empty text, empty map), each naming file, device and field, and that `dump_config` then `load_config` keeps labels in order
    - In `skeleton/tests/test_server.py` test a labeled read (`value` text, `raw`, `unit`), an unmapped integer (integer value, no `raw`, no error), a point without labels (same keys as before), a labeled point with a scale (mapped integer is not scaled), `read_points`, and exactly one audit entry per labeled call
    - Use a fake adapter and no network
    - Run `uv run pytest skeleton/tests/test_server.py` once
    - _Requirements: 5.1, 5.2, Skeleton change 2 (criteria 1 to 5)_

  - [x] 4.4 Write property tests for labels
    - **Property 5: Labels map known integers and leave unknown ones alone**
    - **Validates: Requirements 5.1, 5.2**
    - Create `skeleton/tests/test_labels_properties.py` with a fake adapter and a generated label map for integer types
    - Tag with `Feature: app-snmp, Property 5`, and run at least 100 examples
    - Add labels for integer types to the generator in `skeleton/tests/test_config_properties.py` so the config round trip still holds

- [x] 5. Checkpoint - Skeleton changes
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implement the Address_Parser and Address_Formatter
  - [x] 6.1 Create `apps/snmp/address.py`
    - Define `OID_ARC_MAX = 4294967295`, the frozen `SnmpAddress` dataclass and `AddressError`
    - `parse_address(text)` checks in order: exactly two colon-separated parts, the community (non-empty, lowercase letter first, then lowercase letters, digits and underscores), the OID shape (at least two arcs, no empty arc, digits only, no leading zero), the arc maximum, then the first and second arc limits
    - Error sentences name the form `<community>:<oid>`, the field `community` and its characters, the field `oid` and an example OID, or the allowed arc values
    - `format_address` and `format_oid` return the dotted text
    - _Requirements: 3.1, 3.2, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 12.7_

  - [x] 6.2 Write unit tests in `apps/snmp/tests/test_address.py`
    - Valid addresses, including arcs at 0 and 4294967295
    - The exact expected message content for each defect, a name used as an OID (`sysUpTime`), leading zeros, a first arc of 3 and a second arc of 40 under first arc 1
    - _Requirements: 3.1, 3.2, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9_

  - [x] 6.3 Write property test for address round-trip in `apps/snmp/tests/test_address_properties.py`
    - **Property 3: Address round trip**
    - Tag with `Feature: app-snmp, Property 3`, and run at least 100 examples
    - **Validates: Requirements 3.1, 3.2, 3.3**

  - [x] 6.4 Write property test for malformed addresses in `apps/snmp/tests/test_address_properties.py`
    - **Property 6: A malformed address is rejected with a sentence naming the bad field**
    - Tag with `Feature: app-snmp, Property 6`
    - Generate text with exactly one defect and check that the message names the form, `community` or `oid` that matches it
    - **Validates: Requirements 3.4, 3.5, 3.6, 3.7, 3.8, 3.9**

- [x] 7. Implement the SNMP_Adapter
  - [x] 7.1 Add the pysnmp dependency and write the three pysnmp verification tests
    - Check the current pysnmp 7.1 documentation for `get_cmd`, `UdpTransportTarget.create`, `CommunityData` and `lookupMib`
    - Add `pysnmp>=7.1,<8` to `dependencies` in `pyproject.toml` and run `uv sync`
    - Create `apps/snmp/tests/test_adapter.py` with only these three tests, written against the Simulator and without any adapter code beyond a throwaway helper inside the test file:
      - `test_pysnmp_exception_value_imports` imports `NoSuchObject`, `NoSuchInstance` and `EndOfMibView` and checks that the classes exist
      - `test_pysnmp_varbinds_shape_lookup_mib_false` sends a GET with `lookupMib=False` for an integer Point, a Counter64 Point and an undefined OID, and checks the shape of `varBinds`, how to read the OID and the value, and that the undefined OID gives an instance of `NoSuchObject`
      - `test_pysnmp_event_loop_reuse` makes many reads and checks one loop, one thread and one `SnmpEngine`, and that a second read does not fail with a closed-loop error
    - Run `uv run ruff check .` and `uv run ruff format --check .`, and do not run these tests locally
    - Stop and ask the user to push the branch and report the GitHub Actions (ubuntu) result of the three tests, with the failure text if any fails
    - _Requirements: 2.16, 2.18, 2.21, 12.5, 12.10_

  - [x] 7.2 Create `apps/snmp/adapter.py` after the GitHub Actions result of 7.1 is known
    - Write the exception-value imports, the `varBinds` reading and the loop handling exactly as the 7.1 result shows, and if a result differs from the design, record it and stop for a decision before writing code that relies on it
    - `SnmpAdapter(host, port)` implements `connect`, `close`, `read` and `health` of `ProtocolAdapter` and no write method
    - Import only `get_cmd` from the pysnmp command generators, and use `CommunityData(community, mpModel=1)`, `lookupMib=False` and numeric OID text
    - `connect()` starts one daemon thread with one private event loop and creates one `SnmpEngine` on it. `read()` uses `run_coroutine_threadsafe` and never creates a loop. `close()` closes the dispatcher, stops the loop, joins the thread and is safe to call twice
    - Cache one `UdpTransportTarget` per device, with the device timeout and `retries=0`, and wrap each GET in `asyncio.wait_for`
    - Convert the answer to bytes: Integer32 to 4 bytes `int32`, Counter32, Gauge32 and TimeTicks to 4 bytes `uint32`, Counter64 to 8 bytes `uint64`, and raise the type-mismatch sentence for any other pairing
    - Raise `_DeviceSilent(AdapterReadError, TimeoutError)` on no answer, and `AdapterReadError` sentences from fixed templates for noSuchObject, noSuchInstance, endOfMibView and a non-zero error-status, with no stack trace and no pysnmp class name
    - `health` reads the first point and returns `ok`, `degraded` or `unreachable`
    - Import nothing from `apps/` except `apps/snmp/address.py`. Type hints on every public function, no `Any`
    - _Requirements: 2.1, 2.2, 2.3, 2.5, 2.6, 2.8, 2.9, 2.10, 2.11, 2.12, 2.13, 2.14, 2.15, 2.16, 2.17, 2.18, 2.19, 2.20, 5.3, 5.4, 5.5, 6.4_

  - [x] 7.3 Add adapter unit tests to `apps/snmp/tests/test_adapter.py`
    - Keep the three tests from 7.1 and share one module-scoped Simulator and one module-scoped adapter
    - One read per SNMP type with the expected bytes, and the Codec decoding them to the Simulator's state
    - Failures: noSuchObject, silence within the timeout (a socket that never answers), a type mismatch, and a data type that fits no SNMP type, each sentence naming the device and the point and containing no stack trace and no `pysnmp`
    - `health` gives `ok`, `degraded` and `unreachable`
    - Many reads leave the thread count and loop count unchanged, and `close()` twice does not fail
    - `test_no_pysnmp_outside_adapter` and `test_no_set_outside_simulator` as AST scans over the repository and `apps/snmp/`, and a scan that `skeleton/` imports neither `pysnmp` nor `apps`
    - Run `uv run pytest apps/snmp/tests/test_adapter.py` once only if the user asks for a local run, since pysnmp is verified on GitHub Actions
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.8, 2.9, 2.10, 2.11, 2.12, 2.13, 2.15, 2.16, 2.17, 2.18, 2.20, 5.3, 5.4, 5.5, 6.4, 11.1_

- [x] 8. Checkpoint - Address parser and adapter
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Write the SNMP_Config
  - [x] 9.1 Create `apps/snmp/devices.yaml`
    - Define `core_switch`, `edge_router` and `ups` with the 19 Points, OIDs, data types, units, scales and labels from the design tables
    - Every address is `<device>:<oid>` with the community equal to the device name
    - `uptime` points are `uint32` with scale 0.01 and unit `s`, octet counters are `uint64`, and the status points carry labels that cover every value the Simulator can report
    - Add a comment that `memory_used` counts 1 MiB units
    - At least one point each of `uint32`, `int32` and `uint64`, and no empty unit
    - Use ASCII only
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.15, 5.6_

  - [x] 9.2 Write unit tests in `apps/snmp/tests/test_config.py`
    - Load the shipped file with `seance.config.load_config`
    - Assert the three devices, 19 Points, the required Points per device, data type coverage, positive scales, the 0.01 scale on uptime, non-empty units and labels on the status Points
    - Assert that every address parses with a community equal to the device name, and that every Point exists in the Simulator's OID map with a compatible type and labels that cover its reachable values
    - Assert that a bad field gives one message naming the file, the device and the field
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 4.12, 5.6_

  - [x] 9.3 Write property test for reads in `apps/snmp/tests/test_adapter_properties.py`
    - **Property 2: A read returns the Simulator state after decoding, scaling and labeling**
    - Tag with `Feature: app-snmp, Property 2`
    - Share one module-scoped Simulator with `drift=False`, one adapter and one `ToolServer` wired to `devices.yaml`, generate in-range raw values per Point, call `set_value`, read through the `ToolServer`, and compare with the reference computed by the skeleton helpers
    - Set `deadline=None`, create no event loop per example
    - **Validates: Requirements 2.6, 2.7, 5.1, 5.3, 5.4, 5.5, 7.12**

  - [x] 9.4 Write property test for read-only behavior in `apps/snmp/tests/test_readonly_properties.py`
    - **Property 1: Only GET requests reach the Simulator**
    - Tag with `Feature: app-snmp, Property 1`
    - Drive a `ToolServer` wired to the real adapter, `devices.yaml` and a running Simulator with generated tool names and argument sets, including write-shaped ones
    - Compare `len(simulator.pdus_seen)` before and after each sequence, assert that the new records contain only GET, and that a guard-rejected call adds none
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4**

- [x] 10. Implement the Entry_Point
  - [x] 10.1 Create `apps/snmp/__main__.py`
    - Read `SEANCE_SNMP_HOST` (127.0.0.1), `SEANCE_SNMP_PORT` (1161), `SEANCE_CONSOLE_HOST` (127.0.0.1) and `SEANCE_CONSOLE_PORT` (8080), with `StartupError` and `read_port` as in `apps/modbus/__main__.py`, copied and not imported
    - A port that is not an integer from 1 to 65535 stops before serving with one message naming the variable and the range
    - `check_points(config_path)` loads the config, parses every address with a message naming device, point and reason, and compares the community with the device name with a message naming device, point and both values
    - Start the Simulator with seed 1, build the adapter, check the config, then call `build_tool_server` and `serve`, in that order
    - A busy UDP port stops with one message naming the port and `SEANCE_SNMP_PORT`
    - Send every log and message to standard error, and have `main` return 0 on a normal stop and 1 after one startup message
    - When `serve` returns, stop the Simulator and exit
    - Needs no secret and makes no network call beyond its own host
    - _Requirements: 4.11, 4.12, 4.13, 4.14, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.10_

  - [x] 10.2 Write unit tests in `apps/snmp/tests/test___main__.py`
    - Defaults and overrides of the four environment variables
    - Invalid ports (text, 0, 65536) give one message naming the variable and the range
    - A busy port gives one message naming the port and `SEANCE_SNMP_PORT`
    - An invalid address and a community that differs from the device name each give one message naming the device, the point and the reason
    - Startup order and shutdown order, with an injected `serve` and an injected simulator factory
    - Nothing is written to standard output by the Entry_Point itself
    - _Requirements: 4.12, 4.13, 4.14, 7.1, 7.2, 7.3, 7.4, 7.5, 7.7, 7.8, 7.9, 7.10_

  - [x] 10.3 Write integration tests in `apps/snmp/tests/test_server_integration.py`
    - Use the skeleton `ToolServer` with the real adapter, `devices.yaml` and a running Simulator on a free port
    - `list_devices` returns three devices, `list_points`, `read_points` and `device_health` answer, and `read_point` on `core_switch` `port3_status` returns `down` with raw 2, unit and timestamp
    - A point the device does not define gives one sentence naming the device and the point
    - With the Simulator stopped, each read returns the Timeout_Sentence within the device timeout
    - Every failed call leaves exactly one audit entry with the failure outcome, and no result contains a stack trace or `pysnmp`
    - The console shows the three devices with live values within 5 seconds of start
    - A plain test that the SNMP tool names and the Modbus tool names are the same set of exactly `list_devices`, `list_points`, `read_point`, `read_points` and `device_health`
    - _Requirements: 2.19, 5.1, 5.7, 5.8, 5.9, 7.11, 7.12, 8.1, 8.2, 8.3, 10.11_

- [ ] 11. Checkpoint - Config and Entry_Point
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. Write the README
  - [ ] 12.1 Create `apps/snmp/README.md`
    - Use the same section headings as `apps/modbus/README.md`, in the same order: the title, "Run it", "Points", "Tools", "Example questions", "Run the tests" and "Use it from Kiro"
    - State the command `uv run python -m apps.snmp` and the four environment variables with their defaults
    - Explain that the default port is 1161 because port 161 needs elevated privileges
    - List every Point with Device, name, SNMP_Address, data type, unit, scale and labels
    - Give three example questions with the tool calls that answer them, one asking which port of the core switch is down
    - State that selecting a Device by community is a Simulator convention, and that real gear is addressed by host and port with the community kept secret
    - Show how to run the tests of the SNMP app, and describe `.kiro/settings/mcp.json` and how to enable it
    - Use ASCII only
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9_

  - [ ] 12.2 Write unit tests in `apps/snmp/tests/test_readme.py`
    - The README is ASCII only and its headings equal those of `apps/modbus/README.md`, in order
    - It contains the command, the four variable names with defaults, the port 1161 explanation and the community statement
    - Every Point in `devices.yaml` appears with its address, type, unit, scale and labels
    - Three example questions each name existing tool names, and one mentions the core switch port that is down
    - It mentions the test command and `mcp.json`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9_

- [ ] 13. Add the Kiro_MCP_Config
  - [ ] 13.1 Print the `seance-snmp` entry for the user to add
    - The agent cannot write `.kiro/settings/mcp.json`, so do not edit it
    - Print this entry as a JSON object in the reply and ask the user to add it under `mcpServers`, next to the unchanged `seance-modbus` entry:
      - `command` `uv`, `args` `run`, `python`, `-m`, `apps.snmp`
      - `env` with `SEANCE_CONSOLE_PORT` set to `8083`, which differs from 8080, from `seance-modbus` (8081) and from the WSL Modbus entry (8082)
      - `disabled` false, and `autoApprove` listing `list_devices`, `list_points`, `read_point`, `read_points` and `device_health`
      - No secret in the entry
    - Stop and wait for the user to confirm that the entry is added before starting 13.2
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9_

  - [ ] 13.2 Write unit tests in `apps/snmp/tests/test_mcp_config.py`
    - Parse `.kiro/settings/mcp.json` and assert criteria 10.3 to 10.9: one `seance-snmp` entry, the `uv` command and arguments, the five tools in `autoApprove`, the entry enabled, no value that looks like a secret, valid JSON, a console port other than 8080 and other than the `seance-modbus` console port, and the `seance-modbus` entry unchanged
    - When the entry is missing, fail with a message that names the missing `seance-snmp` entry
    - Assert that `.gitignore` does not list `.kiro`
    - _Requirements: 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 10.10_

- [ ] 14. Final checkpoint - Ensure all tests pass
  - Run `uv run ruff check .` and `uv run ruff format --check .` locally
  - Rely on the GitHub Actions (ubuntu) run for the full suite, and do not run it locally
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 12.9, 12.10_

## Notes

- Every test task is required. This spec has no optional tasks.
- Commit messages use the imperative mood and name the spec task, for example `Add Simulator drift and seeding (app-snmp task 1.2)`.
- Test files mirror source files. Property tests live in `test_*_properties.py`.
- All sources and documents use UTF-8 with ASCII characters only.
- Tests start the Simulator on a free localhost UDP port and make no other network call. Share one module-scoped Simulator and create no event loop per test, per example or per tool call.
- Tasks 3 and 4 change only the skeleton, additively, and must land before task 7. If another skeleton gap appears, record it and stop for a decision, and do not work around it in the skeleton.
- `apps/modbus/` source files and the Simulator are not changed by any task. Its tests may be updated when the skeleton gains a data type (decided after the task 3 CI failures in `apps/modbus/tests/test_adapter.py`, where the new `uint64` type broke the literal count of 24 combinations and the register reads at `2:holding:0` and `2:input:0`).
- Task 7.2 must not start until the GitHub Actions result of the three tests from 7.1 has been read.
- Properties 1 and 2 need `devices.yaml`, so their tests are in task 9 and not in task 7.
- Property tests validate universal properties. Unit tests validate examples and edge cases.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3", "1.4"] },
    { "id": 3, "tasks": ["2"] },
    { "id": 4, "tasks": ["3.1"] },
    { "id": 5, "tasks": ["3.2", "3.3"] },
    { "id": 6, "tasks": ["4.1"] },
    { "id": 7, "tasks": ["4.2"] },
    { "id": 8, "tasks": ["4.3", "4.4"] },
    { "id": 9, "tasks": ["5"] },
    { "id": 10, "tasks": ["6.1"] },
    { "id": 11, "tasks": ["6.2", "6.3"] },
    { "id": 12, "tasks": ["6.4"] },
    { "id": 13, "tasks": ["7.1"] },
    { "id": 14, "tasks": ["7.2"] },
    { "id": 15, "tasks": ["7.3"] },
    { "id": 16, "tasks": ["8"] },
    { "id": 17, "tasks": ["9.1"] },
    { "id": 18, "tasks": ["9.2", "10.1"] },
    { "id": 19, "tasks": ["9.3", "10.2"] },
    { "id": 20, "tasks": ["9.4", "10.3"] },
    { "id": 21, "tasks": ["11"] },
    { "id": 22, "tasks": ["12.1"] },
    { "id": 23, "tasks": ["12.2", "13.1"] },
    { "id": 24, "tasks": ["13.2"] },
    { "id": 25, "tasks": ["14"] }
  ]
}
```
