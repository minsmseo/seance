"""Static checks of the Kiro workspace MCP configuration (requirement 10)."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MCP_PATH = REPO_ROOT / ".kiro" / "settings" / "mcp.json"
GITIGNORE_PATH = REPO_ROOT / ".gitignore"

TOOLS = [
    "list_devices",
    "list_points",
    "read_point",
    "read_points",
    "device_health",
]
DEFAULT_PORT = 8080
MODBUS_PORT = 8081


def _servers() -> dict[str, object]:
    data = json.loads(MCP_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    servers = data["mcpServers"]
    assert isinstance(servers, dict)
    return servers


def _named(name: str) -> dict[str, object]:
    servers = _servers()
    assert name in servers, f"missing '{name}' entry in .kiro/settings/mcp.json"
    entry = servers[name]
    assert isinstance(entry, dict)
    return entry


def _entry() -> dict[str, object]:
    return _named("seance-snmp")


def _port(entry: dict[str, object]) -> int:
    env = entry["env"]
    assert isinstance(env, dict)
    port_text = env["SEANCE_CONSOLE_PORT"]
    assert isinstance(port_text, str)
    assert port_text.isdigit()
    return int(port_text)


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in [k, *_strings(v)]]
    return []


def test_file_is_valid_json() -> None:
    json.loads(MCP_PATH.read_bytes())


def test_exactly_one_seance_snmp_entry() -> None:
    names = [name for name in _servers() if name == "seance-snmp"]
    assert names == ["seance-snmp"], "missing 'seance-snmp' entry in .kiro/settings/mcp.json"


def test_command_and_args() -> None:
    entry = _entry()
    assert entry["command"] == "uv"
    assert entry["args"] == ["run", "python", "-m", "apps.snmp"]


def test_auto_approve_lists_exactly_the_five_tools() -> None:
    approved = _entry()["autoApprove"]
    assert isinstance(approved, list)
    assert len(approved) == len(TOOLS)
    assert sorted(approved) == sorted(TOOLS)


def test_entry_is_enabled() -> None:
    assert _entry().get("disabled", False) is False


def test_console_port_is_valid_and_distinct() -> None:
    port = _port(_entry())
    assert 1 <= port <= 65535
    assert port != DEFAULT_PORT
    assert port != MODBUS_PORT
    assert port != _port(_named("seance-modbus"))


def test_no_value_looks_like_a_secret() -> None:
    entry = _entry()
    env = entry["env"]
    assert isinstance(env, dict)
    name_pattern = re.compile(r"secret|token|password|passwd|api[_-]?key", re.I)
    for key in env:
        assert not name_pattern.search(key), key
    for text in _strings(entry):
        assert not re.search(r"(?i)bearer\s|sk-|ghp_|AKIA", text), text
        assert not (len(text) >= 32 and re.fullmatch(r"[A-Za-z0-9+/=_-]+", text)), text


def test_seance_modbus_entry_is_unchanged() -> None:
    entry = _named("seance-modbus")
    assert entry["command"] == "uv"
    assert entry["args"] == ["run", "python", "-m", "apps.modbus"]
    assert entry["env"] == {"SEANCE_CONSOLE_PORT": "8081"}
    assert entry.get("disabled", False) is False
    approved = entry["autoApprove"]
    assert isinstance(approved, list)
    assert sorted(approved) == sorted(TOOLS)


def test_gitignore_does_not_list_kiro() -> None:
    lines = [line.strip() for line in GITIGNORE_PATH.read_text(encoding="utf-8").splitlines()]
    for line in lines:
        assert ".kiro" not in line, line
