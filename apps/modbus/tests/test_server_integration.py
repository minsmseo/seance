"""Integration test: the skeleton ToolServer over the real ModbusAdapter and a Simulator.

Uses the shipped devices.yaml and a Simulator on a free localhost port. The console is
driven with one FastAPI TestClient (one event loop for the whole module). No other
network is used.
"""

from __future__ import annotations

import html
import json
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.modbus import simulator as sim_module
from apps.modbus.adapter import ModbusAdapter
from apps.modbus.simulator import Simulator
from seance.audit import Audit_Log
from seance.codec import apply_scale
from seance.config import load_config
from seance.points import Configuration
from seance.server import ToolServer

HOST = "127.0.0.1"
CONFIG_PATH = Path(__file__).resolve().parents[1] / "devices.yaml"
DEVICE_NAMES = ("mixing_tank", "feed_pump", "chiller")
FORBIDDEN = ("Traceback", 'File "', "pymodbus", "ModbusException", "ExceptionResponse")
CONSOLE_DEADLINE_SECONDS = 5.0


@pytest.fixture(scope="module")
def config() -> Configuration:
    return load_config(CONFIG_PATH)


@pytest.fixture(scope="module")
def simulator() -> Iterator[Simulator]:
    """One running Simulator for the module, with drift effectively off."""
    patch = pytest.MonkeyPatch()
    patch.setattr(sim_module, "DRIFT_INTERVAL_SECONDS", 3600.0)
    running = Simulator(HOST, 0, 1)
    running.start()
    try:
        yield running
    finally:
        running.stop()
        patch.undo()


@pytest.fixture(scope="module")
def adapter(simulator: Simulator) -> Iterator[ModbusAdapter]:
    connected = ModbusAdapter(HOST, simulator.port)
    connected.connect()
    try:
        yield connected
    finally:
        connected.close()


@pytest.fixture(scope="module")
def tool_server(config: Configuration, adapter: ModbusAdapter) -> Iterator[ToolServer]:
    server = ToolServer(config, adapter)
    try:
        yield server
    finally:
        server.close()


@pytest.fixture(scope="module")
def stopped_port() -> int:
    """A port that held a Simulator a moment ago and now has nothing listening."""
    patch = pytest.MonkeyPatch()
    patch.setattr(sim_module, "DRIFT_INTERVAL_SECONDS", 3600.0)
    try:
        gone = Simulator(HOST, 0, 1)
        gone.start()
        port = gone.port
        gone.stop()
    finally:
        patch.undo()
    return port


def _assert_plain(text: str) -> None:
    for word in FORBIDDEN:
        assert word not in text, f"{word!r} found in {text!r}"
    assert "\n" not in text


# --- Happy path --------------------------------------------------------------------------


def test_list_devices_returns_the_three_devices(tool_server: ToolServer) -> None:
    result = tool_server.call("list_devices")
    assert result.ok
    assert isinstance(result.payload, list)
    names = [item["name"] for item in result.payload if isinstance(item, dict)]
    assert sorted(names) == sorted(DEVICE_NAMES)


def test_read_point_equals_decoded_simulator_memory(
    config: Configuration, simulator: Simulator, tool_server: ToolServer
) -> None:
    for device in config.devices:
        for point in device.points:
            result = tool_server.call("read_point", {"device": device.name, "point": point.name})
            assert result.ok, result.text
            assert isinstance(result.payload, dict)
            expected = apply_scale(simulator.get_value(device.name, point.name), point.scale)
            assert result.payload["value"] == expected, (device.name, point.name)
            assert result.payload["unit"] == point.unit
            timestamp = result.payload["timestamp"]
            assert isinstance(timestamp, str)
            assert timestamp.endswith("+00:00")


def test_device_health_is_ok(config: Configuration, tool_server: ToolServer) -> None:
    for device in config.devices:
        result = tool_server.call("device_health", {"device": device.name})
        assert result.ok, result.text
        assert isinstance(result.payload, dict)
        assert result.payload["status"] == "ok"


# --- Failures ----------------------------------------------------------------------------


def test_point_outside_the_device_range_names_device_and_point(
    config: Configuration, adapter: ModbusAdapter
) -> None:
    pump = next(d for d in config.devices if d.name == "feed_pump")
    bad = replace(pump.points[0], address="2:holding:500")
    broken = Configuration(
        devices=tuple(
            replace(d, points=(bad, *pump.points[1:])) if d.name == "feed_pump" else d
            for d in config.devices
        )
    )
    audit = Audit_Log()
    server = ToolServer(broken, adapter, audit=audit)
    try:
        result = server.call("read_point", {"device": "feed_pump", "point": bad.name})
    finally:
        server.close()
    assert not result.ok
    assert result.outcome == "adapter_error"
    assert "feed_pump" in result.text
    assert bad.name in result.text
    assert "outside the range" in result.text
    _assert_plain(result.text)
    entries = audit.recent(10)
    assert len(entries) == 1
    assert entries[0].outcome == "adapter_error"


def test_stopped_simulator_gives_the_timeout_sentence_for_every_read(
    config: Configuration, stopped_port: int
) -> None:
    silent = ModbusAdapter(HOST, stopped_port)
    audit = Audit_Log()
    server = ToolServer(config, silent, audit=audit)
    calls = 0
    try:
        for device in config.devices:
            for point in device.points:
                started = time.monotonic()
                result = server.call("read_point", {"device": device.name, "point": point.name})
                elapsed = time.monotonic() - started
                calls += 1
                assert not result.ok
                assert result.outcome == "timeout"
                assert elapsed <= device.timeout_seconds
                assert result.text == (
                    f"{device.name} did not respond within {device.timeout_seconds:g}s. "
                    "Try again or check the device connection."
                )
                _assert_plain(result.text)
    finally:
        server.close()
        silent.close()
    entries = audit.recent(calls + 10)
    assert len(entries) == calls
    assert all(entry.outcome == "timeout" for entry in entries)


def test_failed_calls_leave_one_audit_entry_each(
    config: Configuration, adapter: ModbusAdapter
) -> None:
    audit = Audit_Log()
    server = ToolServer(config, adapter, audit=audit)
    calls: list[tuple[str, dict[str, object]]] = [
        ("read_point", {"device": "ghost", "point": "level"}),
        ("read_point", {"device": "mixing_tank", "point": "ghost"}),
        ("read_point", {"device": "mixing_tank"}),
        ("write_point", {"device": "mixing_tank", "point": "level", "value": 1}),
    ]
    try:
        results = [server.call(tool, args) for tool, args in calls]
    finally:
        server.close()
    entries = audit.recent(100)
    assert len(entries) == len(calls)
    for result in results:
        assert not result.ok
        _assert_plain(result.text)
    # recent() is newest first.
    for entry, result in zip(reversed(entries), results, strict=True):
        assert entry.outcome == result.outcome
        assert entry.outcome != "ok"


# --- Console -----------------------------------------------------------------------------


def test_console_shows_three_devices_with_live_values_within_five_seconds(
    config: Configuration, simulator: Simulator, tool_server: ToolServer
) -> None:
    started = time.monotonic()
    with TestClient(tool_server.build_console()) as client:
        response = client.get("/")
        elapsed = time.monotonic() - started
        assert response.status_code == 200
        page = response.text
        for name in DEVICE_NAMES:
            assert name in page
        for device in config.devices:
            for point in device.points:
                value = apply_scale(simulator.get_value(device.name, point.name), point.scale)
                assert html.escape(str(value), quote=True) in page, (device.name, point.name)
        reading = client.get("/points/mixing_tank/level")
        assert reading.status_code == 200
        body = json.loads(reading.text)
        assert body["ok"] is True
        assert body["result"]["unit"] == "percent"
    assert elapsed < CONSOLE_DEADLINE_SECONDS
