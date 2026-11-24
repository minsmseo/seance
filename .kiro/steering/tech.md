# Tech

## Stack

- Python 3.12
- `uv` for environments and dependency management
- Official MCP Python SDK for the server layer
- `pymodbus` for Modbus TCP (client and simulator)
- `pysnmp` for SNMP (client and simulator)
- FastAPI and plain HTML, CSS and JavaScript for the web console (no frontend framework)
- `pytest` for unit tests, `hypothesis` for property-based tests
- `ruff` for lint and format

Check the current documentation of a library before using an API from memory.

## Commands

- Install: `uv sync`
- Test: `uv run pytest`
- Lint: `uv run ruff check .`
- Format: `uv run ruff format .`

## Rules

- Type hints on every public function. No `Any` in the skeleton's public interface.
- The skeleton must not import from `apps/`. Apps import from the skeleton.
- The skeleton must not import `pymodbus` or `pysnmp`. Protocol libraries belong to adapters.
- No network calls in unit tests. Use the simulators or fakes.
- Configuration comes from a YAML file per app, validated at startup. Fail fast with a message naming the bad field.
- Errors returned to the agent are short sentences that say what failed and what to try next. Never return a stack trace.
- Timeouts on every device call. Default 2 seconds.

## Property-based testing targets

- The read-only guard rejects every write request for every possible tool name and argument set.
- Decoding then encoding a register value returns the original bytes for every supported data type.
- Unit scaling never changes the sign of a value.
- The audit log contains exactly one entry per tool call, including failed calls.

## Deployment

Each app runs as one container: simulator, MCP server and web console together. The container must start with a single command and no secrets.
