"""Property-based test: the SNMP app only ever sends GET requests to the Simulator.

One Simulator (drift off), one adapter and one ToolServer wired to devices.yaml are
shared by every example in this module. ToolServer.call is synchronous, so the tests
create no event loop of their own.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.snmp.adapter import SnmpAdapter
from apps.snmp.simulator import PduType, Simulator
from seance.config import load_config
from seance.guard import READ_TOOLS
from seance.points import Configuration
from seance.server import ToolServer

HOST = "127.0.0.1"
CONFIG_PATH = Path(__file__).resolve().parents[1] / "devices.yaml"
CONFIG: Configuration = load_config(CONFIG_PATH)

_DEVICE_NAMES = sorted(d.name for d in CONFIG.devices)
_POINT_NAMES = sorted({p.name for d in CONFIG.devices for p in d.points})


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


_WRITE_SHAPED_TOOLS = st.sampled_from(
    [
        "write_point",
        "set_point",
        "set_value",
        "snmp_set",
        "snmpset",
        "SET",
        "set_oid",
        "write_oid",
        "reset_device",
        "WRITE_POINT",
        "read_point ",
        "Read_Point",
        "",
    ]
)

_TOOL_NAMES = st.one_of(
    st.sampled_from(sorted(READ_TOOLS)),
    _WRITE_SHAPED_TOOLS,
    st.text(max_size=30),
)

_NAMES = st.one_of(
    st.sampled_from(_DEVICE_NAMES),
    st.sampled_from(_POINT_NAMES),
    st.text(max_size=20),
)

_JSON_VALUES = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**31), max_value=2**31),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=20),
    st.lists(_NAMES, max_size=4),
)

_ARGUMENTS = st.fixed_dictionaries(
    {},
    optional={
        "device": _NAMES,
        "point": _NAMES,
        "points": st.lists(_NAMES, max_size=4),
        "value": _JSON_VALUES,
        "oid": _JSON_VALUES,
        "community": _JSON_VALUES,
        "address": _JSON_VALUES,
    },
)

_CALLS = st.lists(st.tuples(_TOOL_NAMES, _ARGUMENTS), min_size=1, max_size=4)


# Feature: app-snmp, Property 1
# **Validates: Requirements 6.1, 6.2, 6.3, 6.4**
@settings(max_examples=150, deadline=None)
@given(calls=_CALLS)
def test_simulator_observes_only_get_requests(
    simulator: Simulator, server: ToolServer, calls: list[tuple[str, dict[str, object]]]
) -> None:
    for tool, args in calls:
        before = len(simulator.pdus_seen)

        result = server.call(tool, args)

        new_records = simulator.pdus_seen[before:]
        assert all(record.pdu_type == PduType.GET for record in new_records)
        if tool not in READ_TOOLS:
            assert result.outcome == "rejected"
            assert len(new_records) == 0
