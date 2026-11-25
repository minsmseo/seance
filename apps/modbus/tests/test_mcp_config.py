"""Static checks of the Kiro workspace MCP configuration (requirement 9)."""

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


def _load() -> dict[str, object]:
    data = json.loads(MCP_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _entry() -> dict[str, object]:
    servers = _load()["mcpServers"]
    assert isinstance(servers, dict)
    entry = servers["seance-modbus"]
    assert isinstance(entry, dict)
    return entry


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in [k, *_strings(v)]]
    return []


def test_file_is_valid_json_and_ascii() -> None:
    raw = MCP_PATH.read_bytes()
    raw.decode("ascii")
    json.loads(raw)


def test_single_entry_named_seance_modbus() -> None:
    servers = _load()["mcpServers"]
    assert isinstance(servers, dict)
    assert list(servers) == ["seance-modbus"]


def test_command_and_args() -> None:
    entry = _entry()
    assert entry["command"] == "uv"
    assert entry["args"] == ["run", "python", "-m", "apps.modbus"]


def test_auto_approve_lists_exactly_the_five_tools() -> None:
    approved = _entry()["autoApprove"]
    assert isinstance(approved, list)
    assert len(approved) == len(TOOLS)
    assert sorted(approved) == sorted(TOOLS)


def test_entry_is_enabled() -> None:
    assert _entry().get("disabled", False) is False


def test_console_port_differs_from_default_and_is_valid() -> None:
    env = _entry()["env"]
    assert isinstance(env, dict)
    port_text = env["SEANCE_CONSOLE_PORT"]
    assert isinstance(port_text, str)
    assert port_text.isdigit()
    port = int(port_text)
    assert 1 <= port <= 65535
    assert port != DEFAULT_PORT


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


def test_no_machine_specific_paths() -> None:
    for text in _strings(_load()):
        assert not re.search(r"(?i)\b[a-z]:[\\/]", text), text
        assert not text.startswith(("/", "\\", "~")), text
        assert "\\" not in text, text
        assert "/Users/" not in text and "/home/" not in text, text


def test_gitignore_does_not_list_kiro() -> None:
    lines = [line.strip() for line in GITIGNORE_PATH.read_text(encoding="utf-8").splitlines()]
    for line in lines:
        assert ".kiro" not in line, line
