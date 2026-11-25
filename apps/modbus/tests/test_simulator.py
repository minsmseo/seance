"""Unit tests for the Modbus simulator.

Every test talks only to a simulator on 127.0.0.1 and an OS-assigned port (port 0).
Each Simulator creates one event loop for its whole life, so tests share one running
simulator and start their own only to stop it, compare seeds, count function codes or
check the real drift thread.
Drift is driven by ``drift_step()``; the drift thread is slowed down so it cannot
interleave with the steps, except in the one test that checks the real thread.
"""

from __future__ import annotations

import socket
import struct
import time
from collections.abc import Callable, Iterator

import pytest
from pymodbus.client import ModbusTcpClient
from pymodbus.constants import ExcCodes

from apps.modbus import simulator as sim_module
from apps.modbus.simulator import (
    LEVEL_LOW_LIMIT_RAW,
    MEMORY_MAP,
    MapEntry,
    Simulator,
    SimulatorError,
)

HOST = "127.0.0.1"
ILLEGAL_FUNCTION = ExcCodes.ILLEGAL_FUNCTION
ILLEGAL_ADDRESS = ExcCodes.ILLEGAL_ADDRESS

SimulatorFactory = Callable[[int], Simulator]


def _can_bind(port: int) -> bool:
    """Return True if a plain socket can bind the localhost port right now."""
    with socket.socket() as probe:
        try:
            probe.bind((HOST, port))
        except OSError:
            return False
    return True


def _wait_until_bindable(port: int, timeout: float) -> bool:
    """Poll until the port can be bound. Windows holds a just-closed port for a moment."""
    deadline = time.monotonic() + timeout
    while not _can_bind(port):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)
    return True


def _started(seed: int) -> Simulator:
    """Start a simulator on an OS-assigned port (port 0). One start, one event loop."""
    simulator = Simulator(HOST, 0, seed)
    simulator.start()
    return simulator


@pytest.fixture
def make_simulator(monkeypatch: pytest.MonkeyPatch) -> Iterator[SimulatorFactory]:
    """Return a factory for started simulators with a slow drift thread; stop them at the end."""
    monkeypatch.setattr(sim_module, "DRIFT_INTERVAL_SECONDS", 3600.0)
    started: list[Simulator] = []

    def factory(seed: int) -> Simulator:
        simulator = _started(seed)
        started.append(simulator)
        return simulator

    yield factory
    for simulator in started:
        simulator.stop()


@pytest.fixture(scope="module")
def shared_simulator() -> Iterator[Simulator]:
    """One started simulator (seed 1) for the whole module.

    Each Simulator creates an asyncio event loop. On Windows every loop leaves a
    loopback socket pair in TIME_WAIT, so tests that can share one simulator do.
    """
    patch = pytest.MonkeyPatch()
    patch.setattr(sim_module, "DRIFT_INTERVAL_SECONDS", 3600.0)
    running = _started(1)
    try:
        yield running
    finally:
        running.stop()
        patch.undo()


def _reset(running: Simulator) -> None:
    """Return a shared simulator to its start state: initial values and a reseeded drift."""
    for want_bool in (False, True):
        for entry in MEMORY_MAP:
            if (entry.data_type == "bool") == want_bool:
                running.set_value(entry.device, entry.name, entry.initial)
    running.rng.seed(running.seed)


@pytest.fixture
def simulator(shared_simulator: Simulator) -> Simulator:
    """The shared simulator, reset to its start state for this test."""
    _reset(shared_simulator)
    return shared_simulator


def _connected(running: Simulator) -> Iterator[ModbusTcpClient]:
    modbus_client = ModbusTcpClient(HOST, port=running.port, timeout=2)
    assert modbus_client.connect()
    yield modbus_client
    modbus_client.close()


@pytest.fixture
def client(simulator: Simulator) -> Iterator[ModbusTcpClient]:
    """A pymodbus client connected to the shared simulator."""
    yield from _connected(simulator)


@pytest.fixture
def own_simulator(make_simulator: SimulatorFactory) -> Simulator:
    """A started simulator (seed 1) for one test: used when it stops it or counts requests."""
    return make_simulator(1)


@pytest.fixture
def own_client(own_simulator: Simulator) -> Iterator[ModbusTcpClient]:
    """A pymodbus client connected to the test's own simulator."""
    yield from _connected(own_simulator)


def _words(entry: MapEntry) -> int:
    return 2 if entry.data_type in ("uint32", "float32") else 1


def _read_entry(client: ModbusTcpClient, entry: MapEntry) -> int | float | bool:
    """Read one memory map entry over the wire and decode it."""
    if entry.table == "coil":
        bits = client.read_coils(entry.offset, count=1, device_id=entry.unit).bits
        return bool(bits[0])
    if entry.table == "discrete":
        bits = client.read_discrete_inputs(entry.offset, count=1, device_id=entry.unit).bits
        return bool(bits[0])
    read = (
        client.read_holding_registers if entry.table == "holding" else client.read_input_registers
    )
    words = read(entry.offset, count=_words(entry), device_id=entry.unit).registers
    raw = b"".join(word.to_bytes(2, "big") for word in words)
    if entry.data_type == "uint16":
        return int.from_bytes(raw, "big")
    if entry.data_type == "int16":
        return int.from_bytes(raw, "big", signed=True)
    if entry.data_type == "uint32":
        return int.from_bytes(raw, "big")
    return float(struct.unpack(">f", raw)[0])


def _snapshot(simulator: Simulator) -> dict[tuple[str, str], int | float | bool]:
    return {(e.device, e.name): simulator.get_value(e.device, e.name) for e in MEMORY_MAP}


def test_three_devices_answer_on_their_unit_ids(client: ModbusTcpClient) -> None:
    units = {entry.unit for entry in MEMORY_MAP}
    assert units == {1, 2, 3}
    for entry in MEMORY_MAP:
        value = _read_entry(client, entry)
        assert value == pytest.approx(entry.initial), f"{entry.device}.{entry.name}"


def test_all_four_tables_are_served_by_every_device() -> None:
    for unit in (1, 2, 3):
        tables = {entry.table for entry in MEMORY_MAP if entry.unit == unit}
        assert tables == {"coil", "discrete", "holding", "input"}


def test_all_four_data_types_are_stored() -> None:
    types = {entry.data_type for entry in MEMORY_MAP}
    assert {"uint16", "int16", "uint32", "float32"} <= types


def test_uint32_and_float32_use_high_word_first(
    simulator: Simulator, client: ModbusTcpClient
) -> None:
    simulator.set_value("feed_pump", "runtime_hours", 0x12345678)
    words = client.read_holding_registers(0, count=2, device_id=2).registers
    assert words == [0x1234, 0x5678]
    simulator.set_value("feed_pump", "flow_rate", 1.0)
    words = client.read_input_registers(0, count=2, device_id=2).registers
    assert words == [0x3F80, 0x0000]


def test_negative_int16_is_twos_complement(simulator: Simulator, client: ModbusTcpClient) -> None:
    simulator.set_value("mixing_tank", "temperature", -50)
    words = client.read_input_registers(0, count=1, device_id=1).registers
    assert words == [0xFFCE]


def test_undefined_register_offset_answers_illegal_data_address(client: ModbusTcpClient) -> None:
    response = client.read_holding_registers(50, count=1, device_id=1)
    assert response.isError()
    assert response.exception_code == ILLEGAL_ADDRESS
    response = client.read_input_registers(7, count=1, device_id=3)
    assert response.isError()
    assert response.exception_code == ILLEGAL_ADDRESS


def test_undefined_bit_offset_answers_illegal_data_address(client: ModbusTcpClient) -> None:
    response = client.read_coils(5, count=1, device_id=2)
    assert response.isError()
    assert response.exception_code == ILLEGAL_ADDRESS
    response = client.read_discrete_inputs(1, count=1, device_id=3)
    assert response.isError()
    assert response.exception_code == ILLEGAL_ADDRESS


def test_read_that_runs_past_the_defined_bits_answers_illegal_data_address(
    client: ModbusTcpClient,
) -> None:
    response = client.read_coils(0, count=2, device_id=1)
    assert response.isError()
    assert response.exception_code == ILLEGAL_ADDRESS


def test_unsupported_function_code_answers_illegal_function(client: ModbusTcpClient) -> None:
    response = client.read_exception_status(device_id=1)
    assert response.isError()
    assert response.exception_code == ILLEGAL_FUNCTION


def test_function_codes_seen_records_requests_in_order(
    own_simulator: Simulator, own_client: ModbusTcpClient
) -> None:
    assert own_simulator.function_codes_seen == ()
    own_client.read_coils(0, count=1, device_id=1)
    own_client.read_discrete_inputs(0, count=1, device_id=1)
    own_client.read_holding_registers(0, count=1, device_id=1)
    own_client.read_input_registers(0, count=1, device_id=1)
    own_client.read_exception_status(device_id=1)
    own_client.read_holding_registers(50, count=1, device_id=1)
    assert own_simulator.function_codes_seen == (1, 2, 3, 4, 7, 3)


def test_function_codes_seen_is_a_snapshot(
    own_simulator: Simulator, own_client: ModbusTcpClient
) -> None:
    before = own_simulator.function_codes_seen
    own_client.read_holding_registers(0, count=1, device_id=1)
    assert before == ()
    assert own_simulator.function_codes_seen == (3,)


def test_drift_keeps_every_value_inside_its_bounds(simulator: Simulator) -> None:
    analog = [entry for entry in MEMORY_MAP if entry.data_type != "bool"]
    for start in ("minimum", "maximum"):
        for entry in analog:
            simulator.set_value(entry.device, entry.name, getattr(entry, start))
        for _ in range(40):
            simulator.drift_step()
            for entry in analog:
                value = simulator.get_value(entry.device, entry.name)
                assert entry.minimum <= value <= entry.maximum, f"{entry.device}.{entry.name}"


def test_drift_moves_values(simulator: Simulator) -> None:
    before = _snapshot(simulator)
    for _ in range(10):
        simulator.drift_step()
    assert _snapshot(simulator) != before


def test_equal_seeds_give_equal_sequences(
    simulator: Simulator, make_simulator: SimulatorFactory
) -> None:
    first = simulator
    second = make_simulator(simulator.seed)
    for _ in range(25):
        first.drift_step()
        second.drift_step()
        assert _snapshot(first) == _snapshot(second)


def test_different_seeds_give_different_sequences(
    simulator: Simulator, make_simulator: SimulatorFactory
) -> None:
    first = simulator
    second = make_simulator(2)
    for _ in range(25):
        first.drift_step()
        second.drift_step()
    assert _snapshot(first) != _snapshot(second)


def test_seed_is_exposed(simulator: Simulator) -> None:
    assert simulator.seed == 1


def test_low_level_input_follows_the_level(simulator: Simulator, client: ModbusTcpClient) -> None:
    assert _read_entry(client, _entry("low_level")) is False
    simulator.set_value("mixing_tank", "level", LEVEL_LOW_LIMIT_RAW - 1)
    assert simulator.get_value("mixing_tank", "low_level") is True
    assert client.read_discrete_inputs(0, count=1, device_id=1).bits[0] is True
    simulator.set_value("mixing_tank", "level", LEVEL_LOW_LIMIT_RAW + 1)
    assert simulator.get_value("mixing_tank", "low_level") is False
    assert client.read_discrete_inputs(0, count=1, device_id=1).bits[0] is False


def test_low_level_input_is_unchanged_at_the_limit(simulator: Simulator) -> None:
    simulator.set_value("mixing_tank", "level", LEVEL_LOW_LIMIT_RAW - 1)
    simulator.set_value("mixing_tank", "level", LEVEL_LOW_LIMIT_RAW)
    assert simulator.get_value("mixing_tank", "low_level") is True
    simulator.set_value("mixing_tank", "level", LEVEL_LOW_LIMIT_RAW + 1)
    simulator.set_value("mixing_tank", "level", LEVEL_LOW_LIMIT_RAW)
    assert simulator.get_value("mixing_tank", "low_level") is False


def test_low_level_input_is_refreshed_by_drift(simulator: Simulator) -> None:
    simulator.set_value("mixing_tank", "level", LEVEL_LOW_LIMIT_RAW - 1)
    simulator.set_value("mixing_tank", "low_level", False)
    simulator.drift_step()
    assert simulator.get_value("mixing_tank", "low_level") is True


def test_drift_thread_changes_values_at_least_once_per_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sim_module, "DRIFT_INTERVAL_SECONDS", 0.5)
    running = _started(3)
    try:
        before = _snapshot(running)
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline and _snapshot(running) == before:
            time.sleep(0.05)
        assert _snapshot(running) != before
    finally:
        running.stop()


def test_stop_returns_within_two_seconds_and_releases_the_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sim_module, "DRIFT_INTERVAL_SECONDS", 0.5)
    stopping = _started(1)
    started = time.monotonic()
    stopping.stop()
    assert time.monotonic() - started < 2.0
    assert not stopping.running
    assert _wait_until_bindable(stopping.port, 2.0 - (time.monotonic() - started))


def test_stop_with_a_connected_client_still_releases_the_port(
    own_simulator: Simulator, own_client: ModbusTcpClient
) -> None:
    own_client.read_holding_registers(0, count=1, device_id=1)
    started = time.monotonic()
    own_simulator.stop()
    assert time.monotonic() - started < 2.0
    assert _wait_until_bindable(own_simulator.port, 2.0 - (time.monotonic() - started))


def test_stop_is_safe_when_not_running() -> None:
    Simulator(HOST, 0, 1).stop()


def test_start_on_a_busy_port_raises_one_sentence() -> None:
    with socket.socket() as blocker:
        blocker.bind((HOST, 0))
        port: int = blocker.getsockname()[1]
        busy = Simulator(HOST, port, 1)
        with pytest.raises(SimulatorError, match="already in use"):
            busy.start()
        with pytest.raises(SimulatorError, match="Create a new Simulator"):
            busy.start()


def test_port_zero_reports_the_real_port_after_start(simulator: Simulator) -> None:
    assert simulator.port != 0
    assert not _can_bind(simulator.port)


def test_start_on_a_running_simulator_raises(simulator: Simulator) -> None:
    with pytest.raises(SimulatorError, match="already running"):
        simulator.start()


def test_second_start_after_stop_raises_and_creates_no_new_loop() -> None:
    once = _started(1)
    loop = once._loop  # the test checks that the one loop is kept and closed
    once.stop()
    assert loop is not None
    assert loop.is_closed()
    with pytest.raises(SimulatorError, match="Create a new Simulator"):
        once.start()
    assert once._loop is loop


def test_unknown_point_raises_one_sentence(simulator: Simulator) -> None:
    with pytest.raises(SimulatorError, match="Unknown point"):
        simulator.get_value("mixing_tank", "nope")


def _entry(name: str) -> MapEntry:
    return next(entry for entry in MEMORY_MAP if entry.name == name)
