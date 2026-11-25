"""Property-based test: the Modbus app never sends a write function code.

One Simulator, one adapter and one ToolServer are shared by every example in this
module. ToolServer.call is synchronous, so the tests create no event loop of their own.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.modbus import simulator as sim_module
from apps.modbus.adapter import ModbusAdapter
from apps.modbus.simulator import MEMORY_MAP, Simulator
from seance.guard import READ_TOOLS
from seance.points import Configuration, DataType, DeviceConfig, PointConfig
from seance.server import ToolServer

HOST = "127.0.0.1"
READ_FUNCTION_CODES = frozenset({1, 2, 3, 4})

_DEVICE_NAMES = sorted({entry.device for entry in MEMORY_MAP})
_POINT_NAMES = sorted({entry.name for entry in MEMORY_MAP})


def _config() -> Configuration:
    """Build a Configuration that matches the Simulator memory map."""
    devices: list[DeviceConfig] = []
    for name in _DEVICE_NAMES:
        points = tuple(
            PointConfig(
                name=entry.name,
                address=f"{entry.unit}:{entry.table}:{entry.offset}",
                data_type=DataType(entry.data_type),
                unit=entry.engineering_unit,
                scale=entry.scale if entry.scale != 1 else None,
            )
            for entry in MEMORY_MAP
            if entry.device == name
        )
        devices.append(DeviceConfig(name=name, description=f"{name} (test)", points=points))
    return Configuration(devices=tuple(devices))


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
def tool_server(simulator: Simulator) -> Iterator[ToolServer]:
    """One ToolServer wired to the real adapter and the shared Simulator."""
    adapter = ModbusAdapter(HOST, simulator.port)
    adapter.connect()
    server = ToolServer(_config(), adapter)
    try:
        yield server
    finally:
        server.close()
        adapter.close()


_WRITE_SHAPED_TOOLS = st.sampled_from(
    [
        "write_point",
        "write_register",
        "write_coil",
        "write_registers",
        "write_coils",
        "set_point",
        "set_value",
        "mask_write_register",
        "readwrite_registers",
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
        "values": st.lists(_JSON_VALUES, max_size=4),
        "address": _JSON_VALUES,
        "function_code": st.sampled_from([5, 6, 15, 16, 22, 23, 1, 3]),
    },
)


# Feature: app-modbus, Property 3
# **Validates: Requirements 6.1, 6.2, 6.3**
@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(tool=_TOOL_NAMES, args=_ARGUMENTS)
def test_simulator_observes_only_read_function_codes(
    simulator: Simulator, tool_server: ToolServer, tool: str, args: dict[str, object]
) -> None:
    before = len(simulator.function_codes_seen)

    result = tool_server.call(tool, args)

    seen = simulator.function_codes_seen
    assert set(seen) <= READ_FUNCTION_CODES
    if tool not in READ_TOOLS:
        assert result.outcome == "rejected"
        assert len(seen) == before
