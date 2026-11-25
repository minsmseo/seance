"""Unit tests for the Tool_Server. Uses the Fake_Adapter; no network."""

import asyncio
import struct
from datetime import datetime
from pathlib import Path

import pytest

from seance.adapter import AdapterReadError, AdapterRegistrationError, HealthStatus
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


def test_read_point_rounds_float32_with_and_without_decimals() -> None:
    raw = struct.pack(">f", 44.39446258544922)
    config = Configuration(
        devices=(
            DeviceConfig(
                name="pump",
                description="Pump",
                timeout_seconds=0.2,
                points=(
                    PointConfig("plain", "1", DataType.FLOAT32, "L/min"),
                    PointConfig("rounded", "2", DataType.FLOAT32, "L/min", decimals=1),
                ),
            ),
        )
    )
    server = ToolServer(config, Fake_Adapter(data=raw))
    plain = server.call("read_point", {"device": "pump", "point": "plain"})
    rounded = server.call("read_point", {"device": "pump", "point": "rounded"})
    assert isinstance(plain.payload, dict)
    assert isinstance(rounded.payload, dict)
    assert plain.payload["value"] == 44.39446
    assert rounded.payload["value"] == 44.4


LABELS = ((1, "up"), (2, "down"))
LABEL_CONFIG = Configuration(
    devices=(
        DeviceConfig(
            name="switch",
            description="Core switch",
            timeout_seconds=0.2,
            points=(
                PointConfig("status", "1", DataType.INT16, "state", labels=LABELS),
                PointConfig("plain", "2", DataType.INT16, "state"),
                PointConfig("scaled", "3", DataType.INT16, "C", 0.5, labels=LABELS),
            ),
        ),
    )
)


def labeled(value: int) -> ToolServer:
    return ToolServer(LABEL_CONFIG, Fake_Adapter(data=struct.pack(">h", value)))


def read_dict(server: ToolServer, point: str) -> dict[str, object]:
    result = server.call("read_point", {"device": "switch", "point": point})
    assert result.ok
    assert isinstance(result.payload, dict)
    return result.payload


def test_labeled_read_returns_text_raw_and_unit() -> None:
    payload = read_dict(labeled(2), "status")
    assert payload["value"] == "down"
    assert payload["raw"] == 2
    assert payload["unit"] == "state"
    assert isinstance(payload["timestamp"], str)


def test_unmapped_integer_keeps_integer_value_without_raw() -> None:
    payload = read_dict(labeled(7), "status")
    assert payload["value"] == 7
    assert "raw" not in payload


def test_point_without_labels_has_no_raw_key() -> None:
    payload = read_dict(labeled(1), "plain")
    assert payload["value"] == 1
    assert set(payload) == {"device", "point", "value", "unit", "timestamp"}


def test_labeled_point_with_scale_maps_unscaled_integer() -> None:
    mapped = read_dict(labeled(1), "scaled")
    assert mapped["value"] == "up"
    assert mapped["raw"] == 1
    unmapped = read_dict(labeled(4), "scaled")
    assert unmapped["value"] == pytest.approx(2.0)
    assert "raw" not in unmapped


def test_read_points_applies_labels() -> None:
    server = labeled(1)
    result = server.call("read_points", {"device": "switch", "points": ["status", "plain"]})
    assert result.ok
    assert isinstance(result.payload, dict)
    first, second = result.payload["results"]  # type: ignore[misc]
    assert first["point"] == "status"
    assert first["value"] == "up"
    assert first["raw"] == 1
    assert second["value"] == 1
    assert "raw" not in second


def test_labeled_calls_write_one_audit_entry_each() -> None:
    server = labeled(1)
    server.call("read_point", {"device": "switch", "point": "status"})
    assert len(server.audit.recent(10)) == 1
    server.call("read_points", {"device": "switch", "points": ["status", "scaled"]})
    entries = server.audit.recent(10)
    assert len(entries) == 2
    assert sorted(e.tool for e in entries) == ["read_point", "read_points"]


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


def test_adapter_read_error_message_is_returned() -> None:
    message = "press has no register at 100. Check the point address."
    server, _ = make(Fake_Adapter(error=AdapterReadError(message)))
    result = server.call("read_point", {"device": "press", "point": "temperature"})
    assert not result.ok
    assert result.outcome == "adapter_error"
    assert result.text == message


def test_adapter_read_error_multiline_message_becomes_one_line() -> None:
    server, _ = make(Fake_Adapter(error=AdapterReadError("first line\n  second\tline\r\nthird")))
    result = server.call("read_point", {"device": "press", "point": "temperature"})
    assert result.outcome == "adapter_error"
    assert result.text == "first line second line third"


def test_adapter_read_error_long_message_is_clipped() -> None:
    server, _ = make(Fake_Adapter(error=AdapterReadError("x" * 500)))
    result = server.call("read_point", {"device": "press", "point": "temperature"})
    assert result.outcome == "adapter_error"
    assert len(result.text) == 200
    assert result.text.endswith("...")
    assert result.text == "x" * 197 + "..."


def test_adapter_read_error_at_limit_is_not_clipped() -> None:
    message = "y" * 200
    server, _ = make(Fake_Adapter(error=AdapterReadError(message)))
    result = server.call("read_point", {"device": "press", "point": "temperature"})
    assert result.text == message


def test_adapter_read_error_on_health_check_is_returned() -> None:
    server, _ = make(Fake_Adapter(error=AdapterReadError("press refused the request.")))
    result = server.call("device_health", {"device": "press"})
    assert result.outcome == "adapter_error"
    assert result.text == "press refused the request."


def test_adapter_read_error_writes_one_audit_entry() -> None:
    server, _ = make(Fake_Adapter(error=AdapterReadError("press refused the request.")))
    server.call("read_point", {"device": "press", "point": "temperature"})
    entries = server.audit.recent(10)
    assert len(entries) == 1
    assert entries[0].tool == "read_point"
    assert entries[0].device == "press"
    assert entries[0].outcome == "adapter_error"


def test_other_exception_keeps_generic_sentence_and_one_audit_entry() -> None:
    server, _ = make(Fake_Adapter(error=ValueError("secret detail")))
    result = server.call("read_point", {"device": "press", "point": "temperature"})
    assert result.outcome == "adapter_error"
    assert "press read failed: the adapter reported an error." in result.text
    assert "secret" not in result.text
    assert len(server.audit.recent(10)) == 1


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


def test_mcp_registers_the_five_tools(session_loop: asyncio.AbstractEventLoop) -> None:
    server, _ = make()
    mcp = server.build_mcp()
    tools = session_loop.run_until_complete(mcp.list_tools())
    assert sorted(t.name for t in tools) == sorted(TOOL_NAMES)


def test_mcp_tool_schema_declares_text_arguments(
    session_loop: asyncio.AbstractEventLoop,
) -> None:
    server, _ = make()
    listed = session_loop.run_until_complete(server.build_mcp().list_tools())
    tools = {t.name: t for t in listed}
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


def test_build_console_has_expected_routes() -> None:
    server, _ = make()
    paths = {getattr(route, "path", "") for route in server.build_console().routes}
    assert {"/", "/points/{device}/{point}", "/tools/{tool_name}", "/audit"} <= paths
