# Seance SNMP app

A read-only MCP server for simulated network gear that speaks SNMP v2c. One command starts the simulator, the MCP server and the web console together. It needs no hardware and no secret.

The gear has three devices: `core_switch` (four ports and an uplink), `edge_router` (one WAN link) and `ups` (an uninterruptible power supply). The app sends only SNMP GET requests. It never sends a SET to a device.

## Run it

```
uv sync
uv run python -m apps.snmp
```

The MCP server talks over standard input and output. Logs and messages go to standard error. The web console opens on `http://127.0.0.1:8080` by default.

Four environment variables change the defaults:

| Variable | Default | Meaning |
| --- | --- | --- |
| `SEANCE_SNMP_HOST` | `127.0.0.1` | Host the simulator listens on |
| `SEANCE_SNMP_PORT` | `1161` | UDP port the simulator listens on |
| `SEANCE_CONSOLE_HOST` | `127.0.0.1` | Host the web console listens on |
| `SEANCE_CONSOLE_PORT` | `8080` | Port the web console listens on |

The default SNMP port is 1161 and not the standard 161, because port 161 needs elevated privileges (root on Linux and macOS, administrator rights on some systems). A port must be an integer from 1 to 65535. If the simulator port is already in use, the app stops with a message that suggests setting `SEANCE_SNMP_PORT`.

Selecting a device by community is a Simulator convention. The simulator answers three devices on one host and one port, and it tells them apart by the community string, which equals the device name. Real gear is addressed by host and port, and its community is a secret. Keep the community of real gear out of the address, out of the config file and out of the logs.

## Points

Addresses have the form `<community>:<oid>`, for example `core_switch:1.3.6.1.2.1.1.3.0`. The community equals the device name. The OID is numeric and dotted. A scale converts the raw value to the unit (value = raw * scale). "none" means the raw value is used as it is. Labels map a raw integer to a word. When a label exists, the tool returns the word as `value` and the integer as `raw`.

Interface status labels follow ifOperStatus: 1=up, 2=down, 3=testing, 4=unknown, 5=dormant, 6=notPresent, 7=lowerLayerDown. The `on_battery` labels follow upsOutputSource: 1=other, 2=none, 3=normal, 4=bypass, 5=battery, 6=booster, 7=reducer.

| Device | Name | Address | Data type | Unit | Scale | Labels |
| --- | --- | --- | --- | --- | --- | --- |
| core_switch | uptime | core_switch:1.3.6.1.2.1.1.3.0 | uint32 | s | 0.01 | none |
| core_switch | port1_status | core_switch:1.3.6.1.2.1.2.2.1.8.1 | int32 | state | none | 1=up, 2=down, 3=testing, 4=unknown, 5=dormant, 6=notPresent, 7=lowerLayerDown |
| core_switch | port2_status | core_switch:1.3.6.1.2.1.2.2.1.8.2 | int32 | state | none | 1=up, 2=down, 3=testing, 4=unknown, 5=dormant, 6=notPresent, 7=lowerLayerDown |
| core_switch | port3_status | core_switch:1.3.6.1.2.1.2.2.1.8.3 | int32 | state | none | 1=up, 2=down, 3=testing, 4=unknown, 5=dormant, 6=notPresent, 7=lowerLayerDown |
| core_switch | port4_status | core_switch:1.3.6.1.2.1.2.2.1.8.4 | int32 | state | none | 1=up, 2=down, 3=testing, 4=unknown, 5=dormant, 6=notPresent, 7=lowerLayerDown |
| core_switch | uplink_in_octets | core_switch:1.3.6.1.2.1.31.1.1.1.6.5 | uint64 | B | none | none |
| core_switch | uplink_out_octets | core_switch:1.3.6.1.2.1.31.1.1.1.10.5 | uint64 | B | none | none |
| core_switch | uplink_in_errors | core_switch:1.3.6.1.2.1.2.2.1.14.5 | uint32 | errors | none | none |
| edge_router | uptime | edge_router:1.3.6.1.2.1.1.3.0 | uint32 | s | 0.01 | none |
| edge_router | cpu_load | edge_router:1.3.6.1.2.1.25.3.3.1.2.1 | int32 | percent | none | none |
| edge_router | memory_used | edge_router:1.3.6.1.2.1.25.2.3.1.6.1 | int32 | MiB | none | none |
| edge_router | wan_link_status | edge_router:1.3.6.1.2.1.2.2.1.8.1 | int32 | state | none | 1=up, 2=down, 3=testing, 4=unknown, 5=dormant, 6=notPresent, 7=lowerLayerDown |
| edge_router | wan_in_octets | edge_router:1.3.6.1.2.1.31.1.1.1.6.1 | uint64 | B | none | none |
| edge_router | wan_out_octets | edge_router:1.3.6.1.2.1.31.1.1.1.10.1 | uint64 | B | none | none |
| ups | battery_charge | ups:1.3.6.1.2.1.33.1.2.4.0 | int32 | percent | none | none |
| ups | runtime_remaining | ups:1.3.6.1.2.1.33.1.2.3.0 | int32 | min | none | none |
| ups | on_battery | ups:1.3.6.1.2.1.33.1.4.1.0 | int32 | state | none | 1=other, 2=none, 3=normal, 4=bypass, 5=battery, 6=booster, 7=reducer |
| ups | output_load | ups:1.3.6.1.2.1.33.1.4.4.1.5.1 | int32 | percent | none | none |
| ups | temperature | ups:1.3.6.1.2.1.33.1.2.7.0 | int32 | degC | none | none |

Uptime is TimeTicks (hundredths of a second), so the scale 0.01 gives seconds. `memory_used` counts allocation units, and the simulator treats one unit as 1 MiB. The octet counters are 64-bit and use the skeleton type `uint64`.

With the default simulator seed, port 3 of `core_switch` reports status 2 (down) and every other status is healthy.

## Tools

| Tool | Arguments | Answers |
| --- | --- | --- |
| `list_devices` | none | Which devices exist |
| `list_points` | `device` | Which points a device has |
| `read_point` | `device`, `point` | One value with unit and timestamp |
| `read_points` | `device`, `points` | Several values of one device |
| `device_health` | `device` | `ok`, `degraded` or `unreachable` |

These are the same five tools as in the Modbus app. An agent that learned one app can use the other.

## Example questions

1. Which port of the core switch is down?
   - `read_points` with `device` = `core_switch`, `points` = `["port1_status", "port2_status", "port3_status", "port4_status"]`
   - The answer for `port3_status` is `down` with `raw` 2.

2. Is the UPS running on battery, and how long will it last?
   - `read_points` with `device` = `ups`, `points` = `["on_battery", "battery_charge", "runtime_remaining"]`

3. Is the edge router healthy, and is the WAN link up?
   - `device_health` with `device` = `edge_router`
   - `read_points` with `device` = `edge_router`, `points` = `["wan_link_status", "cpu_load", "memory_used"]`

## Run the tests

```
uv run pytest apps/snmp/tests
```

The tests start the simulator on a free localhost UDP port and make no other network call. The full suite, including the pysnmp tests, runs on GitHub Actions (ubuntu).

## Use it from Kiro

The workspace file `.kiro/settings/mcp.json` defines the MCP servers for Kiro. The SNMP app has one entry, `seance-snmp`. It starts the app with `uv run python -m apps.snmp` and sets `SEANCE_CONSOLE_PORT` to 8083, a value that differs from 8080 and from the console ports of the Modbus entries, so a console that is already running does not block Kiro. All five tools are listed under `autoApprove` because every tool is read-only. The entry holds no secret.

To enable it, open the workspace in Kiro, check that the `seance-snmp` entry is enabled in the MCP servers panel (`"disabled": false` in the file), and ask a question such as "which port of the core switch is down". If the entry is not in the file yet, it is added by task 13 of the app-snmp spec.
