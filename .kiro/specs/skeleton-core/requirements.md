# Requirements Document

## Introduction

The Seance skeleton (`skeleton/seance/`) is the shared core for building read-only MCP servers on top of legacy device protocols. It defines the protocol adapter interface, the point model, YAML configuration, a read-only guard, an audit log, the five standard MCP tools and a web console. It contains no protocol code. All tests in this spec use a fake in-memory adapter. The Modbus and SNMP adapters are covered by separate specs.

## Glossary

- **Skeleton**: The shared Python package in `skeleton/seance/` that builds an MCP server from an adapter and a configuration file.
- **Adapter**: A class that implements the ProtocolAdapter interface for one protocol. It is the only code that knows the protocol.
- **ProtocolAdapter**: The interface that an Adapter implements. It declares the `connect`, `close`, `read` and `health` methods.
- **Fake_Adapter**: An in-memory Adapter used only in tests. It performs no network calls.
- **Device**: A machine described in the configuration file and reachable through an Adapter.
- **Point**: A single readable value on a Device, with a name, an address, a data type, a unit and an optional scale factor.
- **Scale_Factor**: A positive number that the Skeleton multiplies with a raw decoded value to produce the reported value.
- **Config_Loader**: The Skeleton component that loads and validates the YAML configuration file.
- **Configuration**: The validated in-memory representation of the YAML configuration file.
- **Read_Only_Guard**: The Skeleton component that rejects every write request before an Adapter is called.
- **Write_Request**: Any tool call that would change state on a Device.
- **Tool_Server**: The Skeleton component that exposes the MCP tools.
- **Tool**: One of the MCP tools `list_devices`, `list_points`, `read_point`, `read_points` and `device_health`.
- **Codec**: The Skeleton component that decodes raw bytes into typed values and encodes typed values into raw bytes for each supported data type.
- **Audit_Log**: The Skeleton component that records one entry for every Tool call.
- **Audit_Entry**: One record in the Audit_Log with a timestamp, tool name, device, point, outcome and duration.
- **Web_Console**: The Skeleton's FastAPI web page that shows devices, points, live values, raw Tool results and recent Audit_Entry records.
- **Timeout**: The maximum time the Skeleton waits for a Device call. The default is 2 seconds.
- **Operator**: A person who writes the YAML configuration file and runs the server.
- **Agent**: An AI agent that calls the Tools through MCP.

## Requirements

### Requirement 1: Protocol adapter interface

**User Story:** As an adapter author, I want one small interface to implement, so that adding a protocol takes one file.

#### Acceptance Criteria

1. WHEN an Adapter is registered, THE Skeleton SHALL require that the Adapter implements the `connect`, `close`, `read` and `health` methods.
2. IF a registered Adapter does not implement a required method, THEN THE Skeleton SHALL stop at startup and report a message that names the missing method and the Adapter.
3. THE ProtocolAdapter SHALL declare its method signatures using only Skeleton types and Python standard library types.
4. THE Skeleton SHALL import no protocol library, including `pymodbus` and `pysnmp`.
5. THE Skeleton SHALL import nothing from the `apps/` directory.

### Requirement 2: Point model and configuration

**User Story:** As an Operator, I want to describe Devices and Points in a YAML file, so that I never edit code to add a sensor.

#### Acceptance Criteria

1. WHEN the server starts, THE Config_Loader SHALL load and validate the YAML configuration file.
2. IF a configuration field is invalid, THEN THE Config_Loader SHALL stop startup and report a message that names the file, the Device and the field.
3. THE Config_Loader SHALL require each Point to have a name, an address, a data type and a unit.
4. WHERE a Point defines a Scale_Factor, THE Config_Loader SHALL accept the Scale_Factor only when the value is a number greater than zero.
5. IF two Points on one Device share a name, THEN THE Config_Loader SHALL reject the Configuration and report the Device and the duplicate name.
6. IF a Point declares a data type that the Codec does not support, THEN THE Config_Loader SHALL reject the Configuration and report the Device, the Point and the data type.
7. THE Config_Loader SHALL apply a Timeout of 2 seconds to each Device that does not define a Timeout.
8. THE Config_Loader SHALL provide a function that dumps a Configuration to YAML text.
9. FOR ALL valid Configurations, loading, then dumping, then loading again SHALL produce a Configuration equal to the first (round-trip property).

### Requirement 3: Value decoding, encoding and scaling

**User Story:** As an Adapter author, I want shared value conversion, so that every protocol reports values the same way.

#### Acceptance Criteria

1. THE Codec SHALL decode raw bytes into a typed value for each supported data type.
2. THE Codec SHALL encode a typed value into raw bytes for each supported data type.
3. FOR ALL supported data types and FOR ALL byte sequences of the length that the data type requires, decoding then encoding SHALL return the original bytes (round-trip property).
4. IF the byte sequence length does not match the length that the data type requires, THEN THE Codec SHALL return an error that names the data type, the expected length and the received length.
5. WHEN a Point defines a Scale_Factor, THE Codec SHALL multiply the decoded value by the Scale_Factor before the value is reported.
6. FOR ALL decoded values and FOR ALL positive Scale_Factor values, THE Codec SHALL produce a scaled value with the same sign as the decoded value (invariant property).

### Requirement 4: Read-only guard

**User Story:** As a plant engineer, I want writes to be impossible by default, so that an Agent can never change a running machine.

#### Acceptance Criteria

1. WHEN a Write_Request is received, THE Read_Only_Guard SHALL reject the Write_Request before any Adapter method is called.
2. FOR ALL tool names and FOR ALL argument sets that form a Write_Request, THE Read_Only_Guard SHALL reject the Write_Request and the Adapter SHALL receive zero calls (invariant property).
3. WHEN the Read_Only_Guard rejects a Write_Request, THE Tool_Server SHALL return a plain sentence stating that the server is read-only and that no change was made to the Device.
4. THE Skeleton SHALL expose no write method on the ProtocolAdapter interface.
5. WHERE an Adapter author opts in to a write for a named Tool, THE Read_Only_Guard SHALL permit Write_Requests for that Tool only.

### Requirement 5: MCP tools

**User Story:** As an Agent, I want the same Tools on every Seance server, so that I can use any Device without relearning.

#### Acceptance Criteria

1. THE Tool_Server SHALL expose the Tools `list_devices`, `list_points`, `read_point`, `read_points` and `device_health`.
2. WHEN `list_devices` is called, THE Tool_Server SHALL return the name and description of every configured Device.
3. WHEN `list_points` is called with a Device name, THE Tool_Server SHALL return the name, data type and unit of every Point on that Device.
4. WHEN a Point is read, THE Tool_Server SHALL return the value, the unit and a timestamp in ISO 8601 format.
5. WHEN `read_points` is called with several Point names, THE Tool_Server SHALL return one result for each requested Point, in the order requested.
6. WHEN `device_health` is called with a Device name, THE Tool_Server SHALL return the Device status reported by the Adapter and a timestamp in ISO 8601 format.
7. IF a Device does not answer within the Timeout, THEN THE Tool_Server SHALL return a short error sentence that names the Device and a suggested next step.
8. IF an unknown Device or Point is requested, THEN THE Tool_Server SHALL return an error sentence that lists the closest matching names.
9. IF an Adapter raises an error, THEN THE Tool_Server SHALL return a short error sentence that states what failed and what to try next, with no stack trace.
10. WHEN a Tool call has arguments that fail validation, THE Tool_Server SHALL return an error sentence that names the invalid argument.

### Requirement 6: Audit log

**User Story:** As a site owner, I want a record of every call, so that I can see what the Agent asked.

#### Acceptance Criteria

1. WHEN a Tool is called, THE Audit_Log SHALL write exactly one Audit_Entry for that call.
2. WHEN a Tool call fails or is rejected by the Read_Only_Guard, THE Audit_Log SHALL write exactly one Audit_Entry for that call with the outcome that describes the failure or rejection.
3. FOR ALL sequences of Tool calls, the number of Audit_Entry records written SHALL equal the number of Tool calls (invariant property).
4. THE Audit_Log SHALL store in each Audit_Entry a timestamp, the Tool name, the Device, the Point, the outcome and the duration in milliseconds.
5. WHEN the Tool call does not name a Device or a Point, THE Audit_Log SHALL store an empty value for the missing field.
6. THE Web_Console SHALL display Audit_Entry records read from the Audit_Log.

### Requirement 7: Web console

**User Story:** As a judge or a new user, I want a page that shows the server working, so that I can try it without installing an Agent.

#### Acceptance Criteria

1. THE Web_Console SHALL list every Device and every Point of the Configuration.
2. WHEN the Web_Console is open, THE Web_Console SHALL display the current value, unit and timestamp of each listed Point.
3. WHEN a user selects a Tool and submits arguments, THE Web_Console SHALL call the Tool and display the raw result.
4. THE Web_Console SHALL display the 50 most recent Audit_Entry records, newest first.
5. WHEN a Tool is called from the Web_Console, THE Audit_Log SHALL write one Audit_Entry for that call.
6. THE Web_Console SHALL operate without an API key.
7. THE Web_Console SHALL use plain HTML, CSS and JavaScript with no frontend framework.
8. WHERE the seance theme is applied, THE Web_Console SHALL display the original Device names, values and error sentences unchanged.

### Requirement 8: Testability and project constraints

**User Story:** As a maintainer, I want the Skeleton tested without hardware or network, so that the suite runs anywhere.

#### Acceptance Criteria

1. THE Skeleton test suite SHALL use the Fake_Adapter and make no network calls.
2. THE Skeleton SHALL declare type hints on every public function and use no `Any` in its public interface.
3. THE Skeleton test suite SHALL include property-based tests in files named `test_*_properties.py` for the correctness properties in Requirements 2, 3, 4 and 6.
4. THE Skeleton SHALL keep source files and documents in UTF-8 with ASCII characters only.

## Correctness Properties for Property-Based Tests

These properties are carried forward for the design and tasks phases.

1. For every tool name and argument set, a Write_Request is rejected and the Adapter receives zero calls (Requirement 4.2).
2. For every supported data type and every byte sequence of the right length, decode then encode returns the original bytes (Requirement 3.3).
3. For every value and every positive Scale_Factor, scaling preserves the sign (Requirement 3.6).
4. For every sequence of Tool calls, the number of Audit_Entry records equals the number of calls (Requirement 6.3).
5. For every valid Configuration, loading then dumping then loading again yields an equal Configuration (Requirement 2.9).

## Task Ordering Guidance

For the tasks phase, order the work as follows: point model and configuration first, then the Codec, then the Read_Only_Guard, then the Audit_Log, then the Tools, then the Web_Console. Each task must leave the test suite passing.
