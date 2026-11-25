"""Unit tests for the Tool_Server. Uses the Fake_Adapter; no network."""

from collections.abc import Coroutine
from datetime import datetime
from pathlib import Path

import pytest

from seance.adapter import AdapterRegistrationError, HealthStatus
from seance.config import ConfigError, dump_config
from seance.guard import Read_Only_Guard
from seance.points import Configuration, DataType, DeviceConfig, PointConfig
from seance.server import TOOL_NAMES, ToolServer, build_tool_server
from tests.fakes import Fake_Adapter

CONFIG = Configuration(
    devices=(
        DeviceConfig(
            name="press",
            description="Hydraulic press",
            timeout_seconds=0.2,
            points=(
                PointConfig("temperature", "100", DataType.INT16, "C", 0.1),
                PointConfig("running", "101", DataType.BOOL, "bool"),
            ),
        ),
        DeviceConfig("lathe", "Metal lathe", 0.2, ()),
    )
)


def make(adapter: Fake_Adapter | None = None) -> tuple[ToolServer, Fake_Adapter]:
    fake = adapter if adapter is not None else Fake_Adapter(data=b"\x00\x64")
    return ToolServer(CONFIG, fake), fake


def test_list_devices_shape() -> None:
    server, _ = make()
    result = server.call("list_devices")
    assert result.ok
    assert result.payload == [
        {"name": "press", "description": "Hydraulic press"},
        {"name": "lathe", "description": "Metal lathe"},
    ]


def test_list_points_shape() -> None:
    server, _ = make()
    result = server.call("list_points", {"device": "press"})
    assert result.payload == [
        {"name": "temperature", "data_type": "int16", "unit": "C"},
        {"name": "running", "data_type": "bool", "unit": "bool"},
    ]


def test_read_point_scales_and_timestamps() -> None:
    server, _ = make()
    result = server.call("read_point", {"device": "press", "point": "temperature"})
    assert result.ok
    assert isinstance(result.payload, dict)
    assert result.payload["value"] == pytest.approx(10.0)
    assert result.payload["unit"] == "C"
    assert isinstance(result.payload["timestamp"], str)
    datetime.fromisoformat(result.payload["timestamp"])


def test_device_health_shape() -> None:
    server, _ = make(Fake_Adapter(health_status=HealthStatus.DEGRADED))
    result = server.call("device_health", {"device": "press"})
    assert isinstance(result.payload, dict)
    assert result.payload["status"] == "degraded"
    datetime.fromisoformat(str(result.payload["timestamp"]))


def test_unknown_device_lists_close_matches() -> None:
    server, fake = make()
    result = server.call("list_points", {"device": "pres"})
    assert not result.ok
    assert result.outcome == "unknown_target"
    assert "Unknown device 'pres'" in result.text
    assert "press" in result.text
    assert fake.call_count == 0


def test_unknown_device_without_close_match_lists_known() -> None:
    server, _ = make()
    result = server.call("read_point", {"device": "zzzzzz", "point": "x"})
    assert "press" in result.text
    assert "lathe" in result.text


def test_unknown_point_lists_close_matches() -> None:
    server, fake = make()
    result = server.call("read_point", {"device": "press", "point": "temperatur"})
    assert "Unknown point 'temperatur' on device 'press'" in result.text
    assert "temperature" in result.text
    assert fake.call_count == 0


def test_invalid_argument_names_the_argument() -> None:
    server, _ = make()
    assert "'device'" in server.call("list_points", {}).text
    assert "'device'" in server.call("list_points", {"device": 5}).text
    assert "'points'" in server.call("read_points", {"device": "press", "points": "a"}).text
    assert server.call("read_point", {"device": "press"}).outcome == "invalid_argument"


def test_timeout_sentence() -> None:
    server, _ = make(Fake_Adapter(data=b"\x00\x01", delay=1.0))
    result = server.call("read_point", {"device": "press", "point": "temperature"})
    assert result.outcome == "timeout"
    assert result.text == (
        "press did not respond within 0.2s. Try again or check the device connection."
    )
    server.close()


def test_adapter_error_sentence_hides_exception() -> None:
    server, _ = make(Fake_Adapter(error=RuntimeError("secret socket detail")))
    result = server.call("read_point", {"device": "press", "point": "temperature"})
    assert result.outcome == "adapter_error"
    assert "press read failed" in result.text
    assert "Try" in result.text
    assert "secret" not in result.text
    assert "Traceback" not in result.text


def test_wrong_length_data_is_an_adapter_error() -> None:
    server, _ = make(Fake_Adapter(data=b"\x00"))
    result = server.call("read_point", {"device": "press", "point": "temperature"})
    assert result.outcome == "adapter_error"
    assert "int16" in result.text


def test_read_points_inline_error_for_unknown_name() -> None:
    server, _ = make()
    result = server.call("read_points", {"device": "press", "points": ["running", "nope"]})
    assert not result.ok
    assert isinstance(result.payload, dict)
    results = result.payload["results"]
    assert isinstance(results, list)
    first, second = results
    assert isinstance(first, dict) and first["point"] == "running"
    assert isinstance(second, dict) and "Unknown point 'nope'" in str(second["error"])


def test_write_request_is_rejected_without_adapter_call() -> None:
    server, fake = make()
    result = server.call("write_point", {"device": "press", "point": "temperature", "value": 1})
    assert result.outcome == "rejected"
    assert "read-only" in result.text
    assert fake.call_count == 0


def test_opted_in_tool_without_handler_is_not_available() -> None:
    fake = Fake_Adapter()
    server = ToolServer(CONFIG, fake, Read_Only_Guard(frozenset({"write_point"})))
    result = server.call("write_point", {})
    assert result.outcome == "unknown_tool"
    assert fake.call_count == 0


def test_every_call_writes_one_audit_entry() -> None:
    server, _ = make()
    server.call("list_devices")
    server.call("read_point", {"device": "nope", "point": "x"})
    server.call("write_point", {"device": "press"})
    entries = server.audit.recent(10)
    assert [e.outcome for e in entries] == ["rejected", "unknown_target", "ok"]
    assert entries[0].device == "press"
    assert entries[2].device == ""


def _drive[T](coro: Coroutine[object, object, T]) -> T:
    """Run a coroutine that never suspends, without creating an event loop or sockets."""
    try:
        coro.send(None)
    except StopIteration as done:
        return done.value  # type: ignore[no-any-return]
    coro.close()
    raise RuntimeError("coroutine suspended")


def test_mcp_registers_the_five_tools() -> None:
    server, _ = make()
    mcp = server.build_mcp()
    tools = _drive(mcp.list_tools())
    assert sorted(t.name for t in tools) == sorted(TOOL_NAMES)


def test_mcp_tool_schema_declares_text_arguments() -> None:
    server, _ = make()
    tools = {t.name: t for t in _drive(server.build_mcp().list_tools())}
    properties = tools["read_points"].input_schema["properties"]
    assert properties["device"]["type"] == "string"
    assert properties["points"]["type"] == "array"


def _write_config(tmp_path: Path) -> Path:
    path = tmp_path / "devices.yaml"
    path.write_text(dump_config(CONFIG), encoding="utf-8")
    return path


def test_startup_connects_once(tmp_path: Path) -> None:
    fake = Fake_Adapter()
    server = build_tool_server(_write_config(tmp_path), fake)
    assert fake.calls["connect"] == 1
    assert fake.call_count == 1
    server.close()


def test_startup_rejects_incomplete_adapter(tmp_path: Path) -> None:
    class Broken:
        def connect(self) -> None: ...

    with pytest.raises(AdapterRegistrationError):
        build_tool_server(_write_config(tmp_path), Broken())  # type: ignore[arg-type]


def test_startup_fails_on_missing_config(tmp_path: Path) -> None:
    fake = Fake_Adapter()
    with pytest.raises(ConfigError):
        build_tool_server(tmp_path / "missing.yaml", fake)
    assert fake.call_count == 0
