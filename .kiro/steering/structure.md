# Structure

```
.kiro/
  steering/            product.md, tech.md, structure.md
  specs/               one folder per spec
  hooks/
skeleton/
  seance/
    adapter.py         ProtocolAdapter interface
    points.py          Point model: name, address, type, unit, scale
    guard.py           read-only guard
    audit.py           audit log
    config.py          YAML loading and validation
    server.py          builds an MCP server from an adapter and a config
    console/           shared web console
  tests/
apps/
  modbus/
    adapter.py         the only file that knows Modbus
    simulator.py
    devices.yaml
    tests/
    README.md
  snmp/
    adapter.py         the only file that knows SNMP
    simulator.py
    devices.yaml
    tests/
    README.md
docs/
  add-a-protocol.md
LICENSE
README.md
```

## Conventions

- One adapter file per app. If an app needs a second protocol file, raise it as a skeleton design problem first.
- Each app folder runs on its own: it has its own README, config and tests.
- MCP tool names are the same across apps: `list_devices`, `list_points`, `read_point`, `read_points`, `device_health`. An agent that learned one app can use the other.
- Test files mirror source files: `guard.py` is tested by `tests/test_guard.py`.
- Property-based tests go in files named `test_*_properties.py`.
- Commit messages use the imperative mood and name the spec task they complete.
- Source files and documents are UTF-8 and use ASCII characters only.
- Never add `.kiro` or anything under it to `.gitignore`.
