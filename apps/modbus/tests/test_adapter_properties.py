"""Property-based tests for the Modbus adapter.

One Simulator and one adapter are shared by every example in this module, so the
tests create a single asyncio event loop in total.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.modbus import simulator as sim_module
from apps.modbus.adapter import ModbusAdapter
from apps.modbus.simulator import Simulator
from seance.codec import apply_scale, decode
from seance.points import DataType, DeviceConfig, PointConfig

HOST = "127.0.0.1"


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
    """One adapter connected to the shared Simulator."""
    connected = ModbusAdapter(HOST, simulator.port)
    connected.connect()
    yield connected
    connected.close()


@dataclass(frozen=True)
class _Case:
    """A point in the Simulator memory and a raw value inside its declared bounds."""

    device: str
    name: str
    address: str
    data_type: DataType
    value: int | float | bool


def _cases() -> st.SearchStrategy[_Case]:
    def build(
        device: str,
        name: str,
        address: str,
        data_type: DataType,
        values: st.SearchStrategy[int | float | bool],
    ) -> st.SearchStrategy[_Case]:
        return values.map(lambda value: _Case(device, name, address, data_type, value))

    return st.one_of(
        build(
            "mixing_tank",
            "level",
            "1:holding:0",
            DataType.UINT16,
            st.integers(min_value=0, max_value=1000),
        ),
        build(
            "chiller",
            "setpoint",
            "3:holding:0",
            DataType.INT16,
            st.integers(min_value=-100, max_value=300),
        ),
        build(
            "feed_pump",
            "runtime_hours",
            "2:holding:0",
            DataType.UINT32,
            st.integers(min_value=0, max_value=4_000_000_000),
        ),
        build(
            "feed_pump",
            "flow_rate",
            "2:input:0",
            DataType.FLOAT32,
            st.floats(
                min_value=0.0, max_value=80.0, width=32, allow_nan=False, allow_infinity=False
            ),
        ),
        build("feed_pump", "pump_running", "2:coil:0", DataType.BOOL, st.booleans()),
        build("chiller", "fault", "3:discrete:0", DataType.BOOL, st.booleans()),
    )


# Feature: app-modbus, Property 2
# **Validates: Requirements 2.6, 7.12**
@settings(
    max_examples=150,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(case=_cases(), scale=st.sampled_from([None, 0.1, 1.0, 2.5]))
def test_adapter_reads_match_simulator_memory(
    simulator: Simulator, adapter: ModbusAdapter, case: _Case, scale: float | None
) -> None:
    simulator.set_value(case.device, case.name, case.value)
    point = PointConfig(
        name=case.name, address=case.address, data_type=case.data_type, unit="u", scale=scale
    )
    device = DeviceConfig(name=case.device, description="property test", points=(point,))

    raw = adapter.read(device, point)

    in_memory = simulator.get_value(case.device, case.name)
    assert in_memory == case.value
    expected = apply_scale(in_memory, scale)
    assert apply_scale(decode(case.data_type, raw), scale) == expected
