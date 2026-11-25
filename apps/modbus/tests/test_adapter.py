"""Unit tests for the Modbus adapter.

Every test talks only to a Simulator on 127.0.0.1 and an OS-assigned port. One
Simulator is shared by the module, and two more are started and stopped for the
unreachable cases, so the tests create three asyncio event loops in total.
"""

from __future__ import annotations

import ast
import struct
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from apps.modbus import simulator as sim_module
from apps.modbus.adapter import ModbusAdapter
from apps.modbus.simulator import Simulator
from seance.adapter import AdapterReadError, HealthStatus
from seance.codec import required_length
from seance.points import DataType, DeviceConfig, PointConfig

HOST = "127.0.0.1"
MODBUS_DIR = Path(__file__).resolve().parent.parent
FORBIDDEN_WORDS = (
    "pymodbus",
    "Modbus Error",
    "ModbusIOException",
    "ModbusException",
    "ExcCodes",
    "ExceptionResponse",
    "Traceback",
)

TABLES = ("coil", "discrete", "holding", "input")
BIT_TABLES = ("coil", "discrete")


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
    """An adapter connected to the shared Simulator."""
    connected = ModbusAdapter(HOST, simulator.port)
    connected.connect()
    yield connected
    connected.close()


def _device(*points: PointConfig, name: str = "feed_pump") -> DeviceConfig:
    return DeviceConfig(name=name, description="test device", points=tuple(points))


def _point(name: str, address: str, data_type: DataType) -> PointConfig:
    return PointConfig(name=name, address=address, data_type=data_type, unit="u")


# --- One read per table, right function code ---------------------------------------------


@pytest.mark.parametrize(
    ("table", "data_type", "function_code"),
    [
        ("coil", DataType.BOOL, 1),
        ("discrete", DataType.BOOL, 2),
        ("holding", DataType.UINT16, 3),
        ("input", DataType.UINT16, 4),
    ],
)
def test_each_table_is_read_with_its_function_code(
    simulator: Simulator,
    adapter: ModbusAdapter,
    table: str,
    data_type: DataType,
    function_code: int,
) -> None:
    point = _point("p", f"2:{table}:0", data_type)
    before = simulator.function_codes_seen
    adapter.read(_device(point), point)
    assert simulator.function_codes_seen[len(before) :] == (function_code,)


def test_read_never_sends_a_function_code_outside_one_to_four(
    simulator: Simulator, adapter: ModbusAdapter
) -> None:
    before = len(simulator.function_codes_seen)
    for table in TABLES:
        data_type = DataType.BOOL if table in BIT_TABLES else DataType.UINT16
        point = _point("p", f"2:{table}:0", data_type)
        adapter.read(_device(point), point)
    assert set(simulator.function_codes_seen[before:]) == {1, 2, 3, 4}


# --- Data type and table combinations ----------------------------------------------------

COMBINATIONS = [(data_type, table) for data_type in DataType for table in TABLES]


def test_there_are_24_combinations() -> None:
    assert len(COMBINATIONS) == 24


@pytest.mark.parametrize(("data_type", "table"), COMBINATIONS)
def test_data_type_and_table_combination(
    adapter: ModbusAdapter, data_type: DataType, table: str
) -> None:
    point = _point("probe_point", f"2:{table}:0", data_type)
    device = _device(point)
    fits = (data_type == DataType.BOOL) == (table in BIT_TABLES)
    if fits:
        raw = adapter.read(device, point)
        assert len(raw) == required_length(data_type)
        return
    with pytest.raises(AdapterReadError) as caught:
        adapter.read(device, point)
    message = str(caught.value)
    assert "probe_point" in message
    assert data_type.value in message
    assert table in message


def test_register_bytes_are_high_word_first(simulator: Simulator, adapter: ModbusAdapter) -> None:
    simulator.set_value("feed_pump", "runtime_hours", 0x12345678)
    point = _point("runtime_hours", "2:holding:0", DataType.UINT32)
    assert adapter.read(_device(point), point) == bytes.fromhex("12345678")
    simulator.set_value("feed_pump", "flow_rate", 1.0)
    point = _point("flow_rate", "2:input:0", DataType.FLOAT32)
    assert adapter.read(_device(point), point) == struct.pack(">f", 1.0)


def test_negative_int16_bytes_are_twos_complement(
    simulator: Simulator, adapter: ModbusAdapter
) -> None:
    simulator.set_value("chiller", "setpoint", -50)
    point = _point("setpoint", "3:holding:0", DataType.INT16)
    assert adapter.read(_device(point, name="chiller"), point) == b"\xff\xce"


def test_bit_is_one_byte(simulator: Simulator, adapter: ModbusAdapter) -> None:
    point = _point("pump_running", "2:coil:0", DataType.BOOL)
    simulator.set_value("feed_pump", "pump_running", True)
    assert adapter.read(_device(point), point) == b"\x01"
    simulator.set_value("feed_pump", "pump_running", False)
    assert adapter.read(_device(point), point) == b"\x00"


# --- Bad address -------------------------------------------------------------------------


def test_bad_address_names_the_point_and_the_problem(adapter: ModbusAdapter) -> None:
    point = _point("broken_point", "2:holding", DataType.UINT16)
    with pytest.raises(AdapterReadError) as caught:
        adapter.read(_device(point), point)
    message = str(caught.value)
    assert "broken_point" in message
    assert "<unit>:<table>:<offset>" in message


# --- Health ------------------------------------------------------------------------------


def test_health_ok_against_a_running_simulator(adapter: ModbusAdapter) -> None:
    point = _point("runtime_hours", "2:holding:0", DataType.UINT32)
    assert adapter.health(_device(point)) == HealthStatus.OK


def test_health_degraded_when_the_simulator_answers_with_an_exception(
    adapter: ModbusAdapter,
) -> None:
    point = _point("missing", "2:holding:500", DataType.UINT16)
    assert adapter.health(_device(point)) == HealthStatus.DEGRADED


def test_health_unreachable_when_the_simulator_is_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sim_module, "DRIFT_INTERVAL_SECONDS", 3600.0)
    stopped = Simulator(HOST, 0, 1)
    stopped.start()
    port = stopped.port
    stopped.stop()
    silent = ModbusAdapter(HOST, port)
    try:
        point = _point("runtime_hours", "2:holding:0", DataType.UINT32)
        device = DeviceConfig(
            name="feed_pump", description="test", timeout_seconds=0.5, points=(point,)
        )
        assert silent.health(device) == HealthStatus.UNREACHABLE
    finally:
        silent.close()


def test_read_against_a_stopped_simulator_raises_a_short_plain_sentence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sim_module, "DRIFT_INTERVAL_SECONDS", 3600.0)
    stopped = Simulator(HOST, 0, 1)
    stopped.start()
    port = stopped.port
    stopped.stop()
    silent = ModbusAdapter(HOST, port)
    try:
        point = _point("runtime_hours", "2:holding:0", DataType.UINT32)
        device = DeviceConfig(
            name="feed_pump", description="test", timeout_seconds=0.5, points=(point,)
        )
        started = time.monotonic()
        with pytest.raises(AdapterReadError) as caught:
            silent.read(device, point)
        assert time.monotonic() - started < 5.0
        message = str(caught.value)
        assert "feed_pump" in message
        assert "runtime_hours" in message
        _assert_plain(message)
    finally:
        silent.close()


# --- Exception sentences -----------------------------------------------------------------


def _assert_plain(message: str) -> None:
    for word in FORBIDDEN_WORDS:
        assert word not in message, f"{word!r} found in {message!r}"
    assert "\n" not in message


def test_illegal_data_address_sentence_names_device_and_point(adapter: ModbusAdapter) -> None:
    point = _point("missing_point", "2:holding:500", DataType.UINT16)
    with pytest.raises(AdapterReadError) as caught:
        adapter.read(_device(point, name="feed_pump"), point)
    message = str(caught.value)
    assert "feed_pump" in message
    assert "missing_point" in message
    assert "outside the range" in message
    _assert_plain(message)


def test_illegal_bit_address_sentence_names_device_and_point(adapter: ModbusAdapter) -> None:
    point = _point("missing_bit", "2:coil:9", DataType.BOOL)
    with pytest.raises(AdapterReadError) as caught:
        adapter.read(_device(point, name="feed_pump"), point)
    message = str(caught.value)
    assert "feed_pump" in message
    assert "missing_bit" in message
    _assert_plain(message)


def test_other_exception_sentence_names_device_and_point(adapter: ModbusAdapter) -> None:
    # The Simulator answers an unknown unit id with the gateway-no-response exception.
    point = _point("far_point", "9:holding:0", DataType.UINT16)
    with pytest.raises(AdapterReadError) as caught:
        adapter.read(_device(point, name="ghost_device"), point)
    message = str(caught.value)
    assert "ghost_device" in message
    assert "far_point" in message
    assert "gateway" in message
    _assert_plain(message)


# --- Source scan -------------------------------------------------------------------------

WRITE_METHODS = frozenset(
    {
        "write_coil",
        "write_coils",
        "write_register",
        "write_registers",
        "mask_write_register",
        "readwrite_registers",
    }
)


def _python_files() -> list[Path]:
    return sorted(path for path in MODBUS_DIR.rglob("*.py") if "__pycache__" not in path.parts)


def _imports_pymodbus(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] == "pymodbus" for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and (node.module or "").split(".")[0] == "pymodbus":
                return True
    return False


def test_only_adapter_and_simulator_import_pymodbus() -> None:
    sources = [
        path for path in _python_files() if "tests" not in path.relative_to(MODBUS_DIR).parts
    ]
    importers = {path.name for path in sources if _imports_pymodbus(path)}
    assert importers == {"adapter.py", "simulator.py"}


def test_no_file_under_apps_modbus_calls_a_pymodbus_write_method() -> None:
    offenders: list[str] = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in WRITE_METHODS:
                    offenders.append(f"{path.name}:{node.lineno} {node.func.attr}")
    assert offenders == []


def test_adapter_has_no_write_method() -> None:
    public = [name for name in dir(ModbusAdapter) if not name.startswith("_")]
    assert sorted(public) == ["close", "connect", "health", "read"]
