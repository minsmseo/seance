# Seance Modbus app

A read-only MCP server for a simulated batch mixing line that speaks Modbus TCP. One command starts the simulator, the MCP server and the web console together. It needs no hardware and no secret.

The line has three devices: `mixing_tank` (unit 1), `feed_pump` (unit 2) and `chiller` (unit 3). The app sends only Modbus read function codes 1, 2, 3 and 4. It never writes to a device.

## Run it

```
uv sync
uv run python -m apps.modbus
```

The MCP server talks over standard input and output. Logs and messages go to standard error. The web console opens on `http://127.0.0.1:8080` by default.

Four environment variables change the defaults:

| Variable | Default | Meaning |
| --- | --- | --- |
| `SEANCE_MODBUS_HOST` | `127.0.0.1` | Host the simulator listens on |
| `SEANCE_MODBUS_PORT` | `5020` | Port the simulator listens on |
| `SEANCE_CONSOLE_HOST` | `127.0.0.1` | Host the web console listens on |
| `SEANCE_CONSOLE_PORT` | `8080` | Port the web console listens on |

A port must be an integer from 1 to 65535. If the simulator port is already in use, the app stops with a message that suggests setting `SEANCE_MODBUS_PORT`.

## Points

Addresses have the form `<unit>:<table>:<offset>`. The table is `coil`, `discrete`, `input` or `holding`. A scale converts the raw register to the unit (value = raw * scale). "none" means the raw value is used as it is.

| Device | Name | Address | Data type | Unit | Scale |
| --- | --- | --- | --- | --- | --- |
| mixing_tank | level | 1:holding:0 | uint16 | percent | 0.1 |
| mixing_tank | agitator_speed | 1:holding:1 | uint32 | rpm | none |
| mixing_tank | temperature | 1:input:0 | int16 | degC | 0.1 |
| mixing_tank | agitator_running | 1:coil:0 | bool | state | none |
| mixing_tank | low_level | 1:discrete:0 | bool | state | none |
| feed_pump | runtime_hours | 2:holding:0 | uint32 | h | none |
| feed_pump | flow_rate | 2:input:0 | float32 | L/min | none |
| feed_pump | pump_running | 2:coil:0 | bool | state | none |
| feed_pump | overload_trip | 2:discrete:0 | bool | state | none |
| chiller | setpoint | 3:holding:0 | int16 | degC | 0.1 |
| chiller | supply_temp | 3:input:0 | float32 | degC | none |
| chiller | compressor_on | 3:coil:0 | bool | state | none |
| chiller | fault | 3:discrete:0 | bool | state | none |

The float32 points `flow_rate` and `supply_temp` are rounded to 1 decimal place. The 32-bit values use the high word first, and each word is big-endian.

## Tools

| Tool | Arguments | Answers |
| --- | --- | --- |
| `list_devices` | none | Which devices exist |
| `list_points` | `device` | Which points a device has |
| `read_point` | `device`, `point` | One value with unit and timestamp |
| `read_points` | `device`, `points` | Several values of one device |
| `device_health` | `device` | `ok`, `degraded` or `unreachable` |

## Example questions

1. Is the mixing tank running low?
   - `read_point` with `device` = `mixing_tank`, `point` = `low_level`
   - `read_point` with `device` = `mixing_tank`, `point` = `level` for the level in percent

2. How warm is the batch, and is the chiller keeping up?
   - `read_point` with `device` = `mixing_tank`, `point` = `temperature`
   - `read_points` with `device` = `chiller`, `points` = `["setpoint", "supply_temp", "compressor_on"]`

3. Can I trust the feed pump readings, and is the pump in trouble?
   - `device_health` with `device` = `feed_pump`
   - `list_points` with `device` = `feed_pump` to see what it reports
   - `read_points` with `device` = `feed_pump`, `points` = `["pump_running", "flow_rate", "overload_trip"]`

## Run the tests

```
uv run pytest apps/modbus/tests
```

The tests start the simulator on a free localhost port and make no other network call.

## Use it from Kiro

The workspace file `.kiro/settings/mcp.json` defines one server, `seance-modbus`. It starts the app with `uv run python -m apps.modbus` and sets `SEANCE_CONSOLE_PORT` to a value other than 8080, so a console that is already running does not block Kiro. All five tools are listed under `autoApprove` because every tool is read-only.

To enable it, open the workspace in Kiro, check that the `seance-modbus` entry is enabled in the MCP servers panel, and ask a question such as "list the devices on the Modbus line". If the file does not exist yet, it is added by task 12 of the app-modbus spec.
