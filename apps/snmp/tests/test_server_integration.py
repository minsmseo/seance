"""Integration test: the skeleton ToolServer over the real SnmpAdapter and a Simulator.

Uses the shipped devices.yaml and a Simulator on a free localhost UDP port. The console
is driven with one FastAPI TestClient and the MCP tool list with the session event loop,
so the module creates no event loop of its own. No other network is used.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.modbus.adapter import ModbusAdapter
from apps.snmp.adapter import SnmpAdapter
from apps.snmp.simulator import Simulator
from seance.audit import Audit_Log
from seance.codec import apply_scale, round_value
from seance.config import load_config
from seance.points import Configuration, DeviceConfig
from seance.server import ToolServer

HOST = "127.0.0.1"
APP_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = APP_DIR / "devices.yaml"
MODBUS_CONFIG_PATH = APP_DIR.parent / "modbus" / "devices.yaml"
DEVICE_NAMES = ("core_switch", "edge_router", "ups")
TOOLS = {"list_devices", "list_points", "read_point", "read_points", "device_health"}
FORBIDDEN = ("Traceback", 'File "', "pysnmp", "SnmpEngine", "PySnmpError")
CONSOLE_DEADLINE_SECONDS = 5.0
SILENT_TIMEOUT_SECONDS = 0.5
TIMEOUT_MARGIN_SECONDS = 0.5


@pytest.fixture(scope="module")
def config() -> Configuration:
    return load_config(CONFIG_PATH)


@pytest.fixture(scope="module")
def simulator() -> Iterator[Simulator]:
    """One running Simulator for the module, with periodic drift off."""
    running = Simulator(HOST, 0, 1, drift=False)
    running.start()
    try:
        yield running
    finally:
        running.stop()


@pytest.fixture(scope="module")
def adapter(simulator: Simulator) -> Iterator[SnmpAdapter]:
    connected = SnmpAdapter(HOST, simulator.port)
    connected.connect()
    try:
        yield connected
    finally:
        connected.close()


@pytest.fixture(scope="module")
def tool_server(config: Configuration, adapter: SnmpAdapter) -> Iterator[ToolServer]:
    server = ToolServer(config, adapter)
    try:
        yield server
    finally:
        server.close()


@pytest.fixture(scope="module")
def stopped_port() -> int:
    """A port that held a Simulator a moment ago and now has nothing listening."""
    gone = Simulator(HOST, 0, 1, drift=False)
    gone.start()
    port = gone.port
    gone.stop()
    return port


def _assert_plain(text: str) -> None:
    for word in FORBIDDEN:
        assert word not in text, f"{word!r} found in {text!r}"
    assert "\n" not in text


def _fast_config(config: Configuration) -> Configuration:
    """The same devices with a short timeout, so silence tests stay quick."""
    return Configuration(
        devices=tuple(replace(d, timeout_seconds=SILENT_TIMEOUT_SECONDS) for d in config.devices)
    )


def _device(config: Configuration, name: str) -> DeviceConfig:
    return next(d for d in config.devices if d.name == name)


# --- Happy path --------------------------------------------------------------------------


def test_list_devices_returns_the_three_devices(tool_server: ToolServer) -> None:
    result = tool_server.call("list_devices")
    assert result.ok
    assert isinstance(result.payload, list)
    names = [item["name"] for item in result.payload if isinstance(item, dict)]
    assert sorted(names) == sorted(DEVICE_NAMES)


def test_list_points_read_points_and_device_health_answer(
    config: Configuration, tool_server: ToolServer
) -> None:
    for device in config.devices:
        listed = tool_server.call("list_points", {"device": device.name})
        assert listed.ok, listed.text
        assert isinstance(listed.payload, list)
        assert [p["name"] for p in listed.payload if isinstance(p, dict)] == [
            p.name for p in device.points
        ]

        names = [p.name for p in device.points]
        many = tool_server.call("read_points", {"device": device.name, "points": names})
        assert many.ok, many.text
        assert isinstance(many.payload, dict)
        results = many.payload["results"]
        assert isinstance(results, list)
        assert [r["point"] for r in results if isinstance(r, dict)] == names

        health = tool_server.call("device_health", {"device": device.name})
        assert health.ok, health.text
        assert isinstance(health.payload, dict)
        assert health.payload["status"] == "ok"


def test_port3_status_reads_down_with_raw_unit_and_timestamp(tool_server: ToolServer) -> None:
    result = tool_server.call("read_point", {"device": "core_switch", "point": "port3_status"})
    assert result.ok, result.text
    assert isinstance(result.payload, dict)
    assert result.payload["value"] == "down"
    assert result.payload["raw"] == 2
    assert result.payload["unit"] == "state"
    timestamp = result.payload["timestamp"]
    assert isinstance(timestamp, str)
    assert timestamp.endswith("+00:00")


# --- Failures ----------------------------------------------------------------------------


def test_point_the_device_does_not_define_names_device_and_point(
    tool_server: ToolServer,
) -> None:
    result = tool_server.call("read_point", {"device": "core_switch", "point": "port9_status"})
    assert not result.ok
    assert "core_switch" in result.text
    assert "port9_status" in result.text
    _assert_plain(result.text)


def test_oid_the_device_does_not_hold_names_device_and_point(
    config: Configuration, adapter: SnmpAdapter
) -> None:
    switch = _device(config, "core_switch")
    bad = replace(switch.points[0], name="sys_descr", address="core_switch:1.3.6.1.2.1.1.1.0")
    broken = Configuration(
        devices=tuple(
            replace(d, points=(bad, *switch.points[1:])) if d.name == "core_switch" else d
            for d in config.devices
        )
    )
    audit = Audit_Log()
    server = ToolServer(broken, adapter, audit=audit)
    try:
        result = server.call("read_point", {"device": "core_switch", "point": "sys_descr"})
    finally:
        server.close()
    assert not result.ok
    assert result.outcome == "adapter_error"
    assert "core_switch" in result.text
    assert "sys_descr" in result.text
    _assert_plain(result.text)
    entries = audit.recent(10)
    assert len(entries) == 1
    assert entries[0].outcome == "adapter_error"


def test_stopped_simulator_gives_the_timeout_sentence_for_every_read(
    config: Configuration, stopped_port: int
) -> None:
    fast = _fast_config(config)
    silent = SnmpAdapter(HOST, stopped_port)
    silent.connect()
    audit = Audit_Log()
    server = ToolServer(fast, silent, audit=audit)
    calls = 0
    try:
        for device in fast.devices:
            point = device.points[0]
            expected = (
                f"{device.name} did not respond within {device.timeout_seconds:g}s. "
                "Try again or check the device connection."
            )
            reads: list[tuple[str, dict[str, object]]] = [
                ("read_point", {"device": device.name, "point": point.name}),
                ("read_points", {"device": device.name, "points": [point.name]}),
            ]
            for tool, args in reads:
                started = time.monotonic()
                result = server.call(tool, args)
                elapsed = time.monotonic() - started
                calls += 1
                assert not result.ok
                assert elapsed <= device.timeout_seconds + TIMEOUT_MARGIN_SECONDS
                _assert_plain(result.text)
                if tool == "read_point":
                    assert result.outcome == "timeout"
                    assert result.text == expected
                else:
                    assert expected in result.text
    finally:
        server.close()
        silent.close()
    entries = audit.recent(calls + 10)
    assert len(entries) == calls
    assert all(entry.outcome != "ok" for entry in entries)


def test_failed_calls_leave_one_audit_entry_each(
    config: Configuration, adapter: SnmpAdapter
) -> None:
    audit = Audit_Log()
    server = ToolServer(config, adapter, audit=audit)
    calls: list[tuple[str, dict[str, object]]] = [
        ("read_point", {"device": "ghost", "point": "uptime"}),
        ("read_point", {"device": "core_switch", "point": "ghost"}),
        ("read_point", {"device": "core_switch"}),
        ("write_point", {"device": "core_switch", "point": "port1_status", "value": 1}),
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
        assert response.status_code == 200
        listed = client.get("/config")
        assert listed.status_code == 200
        shown_names = [d["name"] for d in listed.json()["devices"]]
        for name in DEVICE_NAMES:
            assert name in shown_names
        for device in config.devices:
            for point in device.points:
                raw = simulator.get_value(device.name, point.name)
                shown: object = round_value(
                    apply_scale(raw, point.scale), point.data_type, point.decimals
                )
                if point.labels is not None:
                    shown = dict(point.labels).get(raw, shown)
                answer = client.get(f"/points/{device.name}/{point.name}")
                assert answer.status_code == 200, (device.name, point.name)
                payload = answer.json()
                assert payload["ok"] is True, (device.name, point.name)
                assert payload["result"]["value"] == shown, (device.name, point.name)
        elapsed = time.monotonic() - started
    assert elapsed < CONSOLE_DEADLINE_SECONDS


# --- Tool names --------------------------------------------------------------------------


def test_snmp_and_modbus_expose_the_same_five_tool_names(
    config: Configuration, session_loop: asyncio.AbstractEventLoop
) -> None:
    snmp_server = ToolServer(config, SnmpAdapter(HOST, 1))
    modbus_server = ToolServer(load_config(MODBUS_CONFIG_PATH), ModbusAdapter(HOST, 1))
    try:
        snmp_tools = session_loop.run_until_complete(snmp_server.build_mcp().list_tools())
        modbus_tools = session_loop.run_until_complete(modbus_server.build_mcp().list_tools())
    finally:
        snmp_server.close()
        modbus_server.close()
    snmp_names = [t.name for t in snmp_tools]
    modbus_names = [t.name for t in modbus_tools]
    assert len(snmp_names) == len(TOOLS)
    assert set(snmp_names) == TOOLS
    assert set(modbus_names) == TOOLS
