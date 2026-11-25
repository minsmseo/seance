"""Property-based tests for reads through the SNMP adapter and the Tool_Server.

One Simulator (drift off), one adapter and one ToolServer wired to devices.yaml are
shared by every example in this module. The adapter owns one private event loop, and
the tests create no event loop of their own.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.snmp.adapter import SnmpAdapter
from apps.snmp.simulator import OID_MAP, Simulator
from seance.codec import apply_scale, decode, encode, round_value
from seance.config import load_config
from seance.points import Configuration, DeviceConfig, PointConfig
from seance.server import ToolServer

HOST = "127.0.0.1"
CONFIG_PATH = Path(__file__).resolve().parents[1] / "devices.yaml"
CONFIG: Configuration = load_config(CONFIG_PATH)


@dataclass(frozen=True)
class _Case:
    """A configured point and a raw value inside the Simulator's range for it."""

    device: DeviceConfig
    point: PointConfig
    value: int


def _cases() -> st.SearchStrategy[_Case]:
    ranges = {(e.device, e.name): (e.minimum, e.maximum) for e in OID_MAP}
    options: list[st.SearchStrategy[_Case]] = []
    for device in CONFIG.devices:
        for point in device.points:
            low, high = ranges[(device.name, point.name)]
            options.append(
                st.integers(min_value=low, max_value=high).map(
                    lambda value, d=device, p=point: _Case(d, p, value)
                )
            )
    return st.one_of(options)


@pytest.fixture(scope="module")
def simulator() -> Iterator[Simulator]:
    running = Simulator(HOST, 0, 1, drift=False)
    running.start()
    try:
        yield running
    finally:
        running.stop()


@pytest.fixture(scope="module")
def server(simulator: Simulator) -> Iterator[ToolServer]:
    adapter = SnmpAdapter(HOST, simulator.port)
    adapter.connect()
    tool_server = ToolServer(CONFIG, adapter)
    try:
        yield tool_server
    finally:
        tool_server.close()
        adapter.close()


def test_every_configured_point_is_in_the_simulator_map() -> None:
    known = {(e.device, e.name) for e in OID_MAP}
    configured = {(d.name, p.name) for d in CONFIG.devices for p in d.points}
    assert configured <= known


# Feature: app-snmp, Property 2
# **Validates: Requirements 2.6, 2.7, 5.1, 5.3, 5.4, 5.5, 7.12**
@settings(max_examples=150, deadline=None)
@given(case=_cases())
def test_read_returns_simulator_state_decoded_scaled_and_labeled(
    simulator: Simulator, server: ToolServer, case: _Case
) -> None:
    device, point = case.device, case.point
    simulator.set_value(device.name, point.name, case.value)
    in_state = simulator.get_value(device.name, point.name)
    assert in_state == case.value

    result = server.call("read_point", {"device": device.name, "point": point.name})

    assert result.ok, result.text
    payload = result.payload
    assert isinstance(payload, dict)
    decoded = decode(point.data_type, encode(point.data_type, in_state))
    assert decoded == in_state
    labels = dict(point.labels) if point.labels is not None else {}
    assert payload["device"] == device.name
    assert payload["point"] == point.name
    assert payload["unit"] == point.unit
    assert isinstance(payload["timestamp"], str)
    assert datetime.fromisoformat(payload["timestamp"]).tzinfo is not None
    if decoded in labels:
        assert payload["value"] == labels[decoded]
        assert payload["raw"] == decoded
    else:
        expected = round_value(apply_scale(decoded, point.scale), point.data_type, point.decimals)
        assert payload["value"] == expected
        assert "raw" not in payload
