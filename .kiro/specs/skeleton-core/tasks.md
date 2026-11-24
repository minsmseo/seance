# Implementation Plan: skeleton-core

## Overview

Build the `skeleton/seance/` Python 3.12 package in this order: point model and configuration, Codec, read-only guard, audit log, MCP tools, web console. Every task leaves `uv run pytest` and `uv run ruff check .` passing. All tests use an in-memory Fake_Adapter (`skeleton/tests/fakes.py`) and make no network calls. No protocol adapter is built in this spec. Source files and documents are ASCII only.

The Codec has no slot in the requested order, so it is built right after configuration. The Tools need it, and the Config_Loader needs the supported data types.

## Tasks

- [x] 1. Set up the package, point model and adapter interface
  - [x] 1.1 Create project scaffolding
    - Create `pyproject.toml` (Python 3.12, `uv`, dependencies: `mcp`, `fastapi`, `pyyaml`, `uvicorn`; dev: `pytest`, `hypothesis`, `ruff`, `httpx`)
    - Create `skeleton/seance/__init__.py` and `skeleton/tests/__init__.py`
    - Configure `pytest` and `ruff` in `pyproject.toml`
    - _Requirements: 8.2, 8.4_

  - [x] 1.2 Implement the point model, ProtocolAdapter and Fake_Adapter
    - In `skeleton/seance/points.py`: `DataType`, `PointConfig`, `DeviceConfig`, `Configuration` as frozen dataclasses with full type hints and no `Any`
    - In `skeleton/seance/adapter.py`: `HealthStatus`, `ProtocolAdapter` (`connect`, `close`, `read`, `health`, no write method), `AdapterRegistrationError` and a registration check that names the adapter class and the missing method
    - In `skeleton/tests/fakes.py`: `Fake_Adapter` with configurable bytes, errors, delay and a call counter
    - _Requirements: 1.1, 1.2, 1.3, 2.3, 4.4, 8.1, 8.2_

  - [x] 1.3 Write unit tests for adapter registration and layering
    - Test that a missing method raises `AdapterRegistrationError` naming the method and class
    - Test that no module under `skeleton/seance/` imports `pymodbus`, `pysnmp` or `apps`
    - Test that `ProtocolAdapter` exposes no write method
    - Create `skeleton/tests/test_adapter.py`
    - _Requirements: 1.2, 1.4, 1.5, 4.4_

- [x] 2. Implement configuration loading and dumping
  - [x] 2.1 Implement `Config_Loader` in `skeleton/seance/config.py`
    - `load_config(path) -> Configuration` and `dump_config(config) -> str`
    - `ConfigError(file, device, field, reason)` naming the file, device and field
    - Require name, address, data type and unit on each Point; accept `scale` only when it is a number greater than zero
    - Reject duplicate Point names per Device and unsupported data types
    - Default `timeout_seconds` to 2.0
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8_

  - [x] 2.2 Write property test for configuration round-trip
    - **Property 1: Configuration round-trip**
    - **Validates: Requirements 2.9**
    - Create `skeleton/tests/test_config_properties.py` with a `hypothesis` strategy for valid Configurations

  - [x] 2.3 Write unit tests for the Config_Loader
    - Missing required Point field, duplicate Point name, unsupported data type, invalid scale, default timeout, error messages naming file, device and field
    - Create `skeleton/tests/test_config.py`
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

- [x] 3. Implement the Codec
  - [x] 3.1 Implement decode, encode and scaling in `skeleton/seance/codec.py`
    - `decode`, `encode`, `apply_scale` for `INT16`, `UINT16`, `INT32`, `UINT32`, `FLOAT32`, `BOOL`
    - `CodecLengthError` naming the data type, expected length and received length
    - Use `RawValue = int | float | bool`
    - _Requirements: 3.1, 3.2, 3.4, 3.5_

  - [x] 3.2 Write property test for decode-then-encode round-trip
    - **Property 2: Codec decode-then-encode round-trip**
    - **Validates: Requirements 3.3**
    - Create `skeleton/tests/test_codec_properties.py`

  - [x] 3.3 Write property test for wrong-length input
    - **Property 3: Codec rejects wrong-length input**
    - **Validates: Requirements 3.4**
    - Add to `skeleton/tests/test_codec_properties.py`

  - [x] 3.4 Write property test for scaling
    - **Property 4: Scaling preserves sign**
    - **Validates: Requirements 3.5, 3.6**
    - Add to `skeleton/tests/test_codec_properties.py`

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement the read-only guard
  - [x] 5.1 Implement `Read_Only_Guard` in `skeleton/seance/guard.py`
    - `Read_Only_Guard(allowed_write_tools: frozenset[str] = frozenset())`
    - `check(tool_name, args) -> GuardResult` returning `Allowed` or `Rejected(message)`
    - Treat any tool name outside the five read tools as a Write_Request unless opted in
    - Rejection message states that the server is read-only and that no change was made
    - _Requirements: 4.1, 4.2, 4.3, 4.5_

  - [x] 5.2 Write property test for guard rejection
    - **Property 5: The guard rejects every write request and the adapter is never called**
    - **Validates: Requirements 4.1, 4.2, 4.3**
    - Create `skeleton/tests/test_guard_properties.py` using the Fake_Adapter call counter

  - [x] 5.3 Write property test for opt-in writes
    - **Property 6: Opt-in write tools are the only tools ever permitted to write**
    - **Validates: Requirements 4.5**
    - Add to `skeleton/tests/test_guard_properties.py`

  - [x] 5.4 Write unit tests for the guard
    - Concrete tool name and argument examples with and without opt-in
    - Create `skeleton/tests/test_guard.py`
    - _Requirements: 4.1, 4.3, 4.5_

- [x] 6. Implement the audit log
  - [x] 6.1 Implement `Audit_Log` in `skeleton/seance/audit.py`
    - `AuditEntry` dataclass with timestamp, tool, device, point, outcome and `duration_ms`
    - `record(entry)` and `recent(n)` returning newest first
    - Empty strings for missing device or point
    - _Requirements: 6.4, 6.5_

  - [x] 6.2 Write unit tests for the audit log
    - Ordering and truncation of `recent(n)`, empty fields, stored fields
    - Create `skeleton/tests/test_audit.py`
    - _Requirements: 6.4, 6.5, 7.4_

- [ ] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. Implement the MCP tools
  - [ ] 8.1 Build the Tool_Server core and discovery tools in `skeleton/seance/server.py`
    - Build the MCP server from a Configuration, adapter, guard and audit log
    - Shared `_call_tool` wrapper that validates arguments, calls the guard and records exactly one Audit_Entry in a `finally` block
    - `list_devices` and `list_points`
    - Unknown device or point errors listing close matches via `difflib.get_close_matches`
    - Invalid-argument errors naming the argument
    - _Requirements: 5.1, 5.2, 5.3, 5.8, 5.10, 6.1, 6.2_

  - [ ] 8.2 Add read and health tools with timeouts
    - `read_point`, `read_points` (requested order) and `device_health`
    - Run adapter calls under the Device Timeout; decode and scale via the Codec
    - Return value, unit and ISO 8601 timestamp
    - Timeout and adapter-error sentences with a next step and no stack trace
    - _Requirements: 3.5, 5.4, 5.5, 5.6, 5.7, 5.9_

  - [ ] 8.3 Wire startup
    - Check adapter registration, load Configuration, call `connect` once before serving
    - Return the guard's plain-sentence rejection for Write_Requests without calling the adapter
    - _Requirements: 1.2, 4.1, 4.3, 5.1_

  - [ ] 8.4 Write unit tests for the tools
    - Shapes for `list_devices` and `list_points`, unknown device and point messages, close-match suggestions, timeout sentence, adapter-error sentence
    - Create `skeleton/tests/test_server.py`
    - _Requirements: 5.2, 5.3, 5.7, 5.8, 5.9, 5.10_

  - [ ] 8.5 Write property tests for read results
    - **Property 7: `read_points` preserves request order**
    - **Validates: Requirements 5.5**
    - **Property 8: Successful reads carry value, unit and a valid timestamp**
    - **Validates: Requirements 5.4, 5.6**
    - Create `skeleton/tests/test_server_properties.py`

  - [ ] 8.6 Write property test for error sentences
    - **Property 9: Error responses are short, plain sentences with no stack trace**
    - **Validates: Requirements 5.7, 5.8, 5.9, 5.10**
    - Add to `skeleton/tests/test_server_properties.py`

  - [ ] 8.7 Write property test for audit entry count
    - **Property 10: Audit entry count matches call count**
    - **Validates: Requirements 6.1, 6.2, 6.3**
    - Create `skeleton/tests/test_audit_properties.py` driving the Tool_Server with the Fake_Adapter

  - [ ] 8.8 Write property test for audit fields
    - **Property 11: Audit entries record the field that was supplied and leave the rest empty**
    - **Validates: Requirements 6.4, 6.5**
    - Add to `skeleton/tests/test_audit_properties.py`

- [ ] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Implement the web console
  - [ ] 10.1 Implement FastAPI routes in `skeleton/seance/console/app.py`
    - `GET /`, `GET /points/{device}/{point}`, `POST /tools/{tool_name}`, `GET /audit` (50 most recent, newest first)
    - Calls go through the Tool_Server so each writes one Audit_Entry
    - No API key
    - _Requirements: 6.6, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

  - [ ] 10.2 Add plain HTML, CSS and JavaScript assets
    - Templates and static files under `skeleton/seance/console/` with no frontend framework
    - Seance theme on labels only; device names, values and error sentences render unchanged
    - _Requirements: 7.1, 7.2, 7.7, 7.8_

  - [ ] 10.3 Mount the console in `skeleton/seance/server.py`
    - Mount the console app on server startup
    - _Requirements: 7.1, 7.6_

  - [ ] 10.4 Write route tests for the console
    - Use FastAPI `TestClient` with the Fake_Adapter
    - Check device and point listing, live values, tool invocation with raw result, 50-entry audit view, audit entry written per console call, unchanged names and errors
    - Create `skeleton/tests/test_console.py`
    - _Requirements: 6.6, 7.1, 7.2, 7.3, 7.4, 7.5, 7.8_

- [ ] 11. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- All tasks are required, including test tasks. No task is optional
- Each task references specific requirements for traceability
- Property tests use `hypothesis` with at least 100 iterations and are tagged `Feature: skeleton-core, Property N`
- Property tests live in `test_*_properties.py` files
- No task builds a protocol adapter

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3", "2.1", "3.1"] },
    { "id": 3, "tasks": ["2.2", "2.3", "3.2"] },
    { "id": 4, "tasks": ["3.3"] },
    { "id": 5, "tasks": ["3.4"] },
    { "id": 6, "tasks": ["4"] },
    { "id": 7, "tasks": ["5.1"] },
    { "id": 8, "tasks": ["5.2", "5.4", "6.1"] },
    { "id": 9, "tasks": ["5.3", "6.2"] },
    { "id": 10, "tasks": ["7"] },
    { "id": 11, "tasks": ["8.1"] },
    { "id": 12, "tasks": ["8.2"] },
    { "id": 13, "tasks": ["8.3"] },
    { "id": 14, "tasks": ["8.4"] },
    { "id": 15, "tasks": ["8.5", "8.7"] },
    { "id": 16, "tasks": ["8.6", "8.8"] },
    { "id": 17, "tasks": ["9"] },
    { "id": 18, "tasks": ["10.1"] },
    { "id": 19, "tasks": ["10.2"] },
    { "id": 20, "tasks": ["10.3"] },
    { "id": 21, "tasks": ["10.4"] },
    { "id": 22, "tasks": ["11"] }
  ]
}
```
