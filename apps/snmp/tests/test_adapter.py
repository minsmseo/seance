"""Tests for the SNMP adapter (tasks 7.1 and 7.3).

The first three tests check the pysnmp 7.1 details the adapter relies on. The probe
is a throwaway helper that lives only in this file: one private loop on one thread,
one SnmpEngine. The rest test the adapter against the Simulator on a free localhost
UDP port, plus a plain UDP socket that never answers. One Simulator, one adapter and
one silent adapter are shared by the module, so no test creates an event loop.

Validates: Requirements 2.1-2.6, 2.8-2.13, 2.15-2.18, 2.20, 2.21, 5.3, 5.4, 5.5, 6.4,
11.1, 12.5, 12.10
"""

from __future__ import annotations

import ast
import asyncio
import socket
import struct
import threading
import time
from collections.abc import Coroutine, Iterator
from pathlib import Path

import pytest
from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    get_cmd,
)

from apps.snmp.adapter import SnmpAdapter
from apps.snmp.simulator import OID_MAP, Simulator
from seance.adapter import AdapterReadError, HealthStatus
from seance.codec import apply_scale, decode
from seance.points import DataType, DeviceConfig, PointConfig

HOST = "127.0.0.1"
GET_TIMEOUT_SECONDS = 2.0
RESULT_TIMEOUT_SECONDS = 5.0
COMMUNITY = "core_switch"
PORT3_OID = "1.3.6.1.2.1.2.2.1.8.3"
COUNTER64_OID = "1.3.6.1.2.1.31.1.1.1.6.5"
UNDEFINED_OID = "1.3.6.1.2.1.1.1.0"


class _Probe:
    """One loop on one daemon thread and one SnmpEngine, used only by these tests."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.loop_ids: set[int] = set()
        self.thread_ids: set[int] = set()
        self.engine_ids: set[int] = set()
        self.engine: SnmpEngine | None = None
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="snmp-probe", daemon=True)
        self._thread.start()
        self._call(self._make_engine())

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    def _call[T](self, coroutine: Coroutine[None, None, T]) -> T:
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        return future.result(timeout=RESULT_TIMEOUT_SECONDS)

    async def _make_engine(self) -> None:
        self.engine = SnmpEngine()

    async def _get(self, oid: str) -> tuple[object, object, object, tuple[ObjectType, ...]]:
        assert self.engine is not None
        self.loop_ids.add(id(asyncio.get_running_loop()))
        self.thread_ids.add(threading.get_ident())
        self.engine_ids.add(id(self.engine))
        target = await UdpTransportTarget.create(
            (HOST, self.port), timeout=GET_TIMEOUT_SECONDS, retries=0
        )
        result = await asyncio.wait_for(
            get_cmd(
                self.engine,
                CommunityData(COMMUNITY, mpModel=1),
                target,
                ContextData(),
                ObjectType(ObjectIdentity(oid)),
                lookupMib=False,
            ),
            GET_TIMEOUT_SECONDS,
        )
        return result

    def get(self, oid: str) -> tuple[object, object, object, tuple[ObjectType, ...]]:
        return self._call(self._get(oid))

    async def _close_engine(self) -> None:
        if self.engine is not None:
            self.engine.close_dispatcher()

    def close(self) -> None:
        self._call(self._close_engine())
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=RESULT_TIMEOUT_SECONDS)


@pytest.fixture(scope="module")
def sim() -> Iterator[Simulator]:
    simulator = Simulator(HOST, 0, seed=1, drift=False)
    simulator.start()
    try:
        yield simulator
    finally:
        simulator.stop()


@pytest.fixture(scope="module")
def probe(sim: Simulator) -> Iterator[_Probe]:
    helper = _Probe(sim.port)
    try:
        yield helper
    finally:
        helper.close()


def test_pysnmp_exception_value_imports() -> None:
    from pysnmp.proto.rfc1905 import EndOfMibView, NoSuchInstance, NoSuchObject

    for cls in (NoSuchObject, NoSuchInstance, EndOfMibView):
        assert isinstance(cls, type)


def test_pysnmp_varbinds_shape_lookup_mib_false(sim: Simulator, probe: _Probe) -> None:
    from pysnmp.proto.rfc1902 import Counter64, Integer32
    from pysnmp.proto.rfc1905 import NoSuchObject

    error_indication, error_status, error_index, var_binds = probe.get(PORT3_OID)
    assert not error_indication
    assert int(error_status) == 0
    assert int(error_index) == 0
    assert isinstance(var_binds, (tuple, list))
    assert len(var_binds) == 1
    oid, value = var_binds[0]
    assert str(oid) == PORT3_OID
    assert isinstance(value, Integer32)
    assert int(value) == sim.get_value("core_switch", "port3_status") == 2

    _, _, _, var_binds = probe.get(COUNTER64_OID)
    oid, value = var_binds[0]
    assert str(oid) == COUNTER64_OID
    assert isinstance(value, Counter64)
    assert int(value) == sim.get_value("core_switch", "uplink_in_octets")

    error_indication, error_status, _, var_binds = probe.get(UNDEFINED_OID)
    assert not error_indication
    assert int(error_status) == 0
    oid, value = var_binds[0]
    assert str(oid) == UNDEFINED_OID
    assert isinstance(value, NoSuchObject)


def test_pysnmp_event_loop_reuse(sim: Simulator, probe: _Probe) -> None:
    threads_before = threading.active_count()
    first = probe.get(PORT3_OID)
    second = probe.get(PORT3_OID)
    assert not first[0]
    assert not second[0]
    for _ in range(30):
        error_indication, error_status, _, var_binds = probe.get(PORT3_OID)
        assert not error_indication
        assert int(error_status) == 0
        assert int(var_binds[0][1]) == 2
    assert len(probe.loop_ids) == 1
    assert len(probe.thread_ids) == 1
    assert len(probe.engine_ids) == 1
    assert threading.active_count() == threads_before


# ---------------------------------------------------------------------------
# Adapter tests (task 7.3)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]
SKELETON_DIR = REPO_ROOT / "skeleton"
SNMP_DIR = REPO_ROOT / "apps" / "snmp"
ADAPTER_FILE = SNMP_DIR / "adapter.py"
SIMULATOR_FILE = SNMP_DIR / "simulator.py"
SNMP_TESTS_DIR = SNMP_DIR / "tests"
SKIPPED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".hypothesis"}

DEVICE_TIMEOUT_SECONDS = 1.0
SILENT_TIMEOUT_SECONDS = 0.5
MANY_READS = 25
THREAD_NAME = "snmp-adapter"


def _oid_text(device: str, name: str) -> str:
    for entry in OID_MAP:
        if entry.device == device and entry.name == name:
            return ".".join(str(arc) for arc in entry.oid)
    raise AssertionError(f"{device} {name} is not in the Simulator map")


def _point(device: str, name: str, data_type: DataType, oid: str | None = None) -> PointConfig:
    text = oid if oid is not None else _oid_text(device, name)
    return PointConfig(name=name, address=f"{device}:{text}", data_type=data_type, unit="x")


def _device(
    name: str, points: tuple[PointConfig, ...], timeout: float = DEVICE_TIMEOUT_SECONDS
) -> DeviceConfig:
    return DeviceConfig(
        name=name, description="test device", timeout_seconds=timeout, points=points
    )


def _assert_plain_sentence(message: str, device: str, point: str) -> None:
    assert device in message
    assert point in message
    assert "pysnmp" not in message.lower()
    assert "traceback" not in message.lower()
    assert 'File "' not in message
    assert "\n" not in message
    assert message.isascii()
    assert message.endswith(".")


@pytest.fixture(scope="module")
def adapter(sim: Simulator) -> Iterator[SnmpAdapter]:
    instance = SnmpAdapter(HOST, sim.port)
    instance.connect()
    try:
        yield instance
    finally:
        instance.close()


@pytest.fixture(scope="module")
def silent_port() -> Iterator[int]:
    """A UDP socket that receives datagrams and never answers."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((HOST, 0))
    try:
        yield int(sock.getsockname()[1])
    finally:
        sock.close()


@pytest.fixture(scope="module")
def silent_adapter(silent_port: int) -> Iterator[SnmpAdapter]:
    instance = SnmpAdapter(HOST, silent_port)
    instance.connect()
    try:
        yield instance
    finally:
        instance.close()


@pytest.fixture(scope="module")
def spare_adapter(sim: Simulator) -> Iterator[SnmpAdapter]:
    """Used only by the lifecycle test that closes the adapter twice."""
    instance = SnmpAdapter(HOST, sim.port)
    instance.connect()
    try:
        yield instance
    finally:
        instance.close()


def test_read_integer_returns_int32_bytes(sim: Simulator, adapter: SnmpAdapter) -> None:
    device = _device("core_switch", ())
    point = _point("core_switch", "port3_status", DataType.INT32)
    raw = adapter.read(device, point)
    assert raw == struct.pack(">i", 2)
    assert decode(DataType.INT32, raw) == sim.get_value("core_switch", "port3_status")


def test_read_timeticks_returns_uint32_bytes(sim: Simulator, adapter: SnmpAdapter) -> None:
    device = _device("core_switch", ())
    point = _point("core_switch", "uptime", DataType.UINT32)
    raw = adapter.read(device, point)
    expected = sim.get_value("core_switch", "uptime")
    assert raw == struct.pack(">I", expected)
    decoded = decode(DataType.UINT32, raw)
    assert decoded == expected
    assert apply_scale(decoded, 0.01) == round(expected * 0.01, 2)


def test_read_counter32_returns_uint32_bytes(sim: Simulator, adapter: SnmpAdapter) -> None:
    device = _device("core_switch", ())
    point = _point("core_switch", "uplink_in_errors", DataType.UINT32)
    raw = adapter.read(device, point)
    expected = sim.get_value("core_switch", "uplink_in_errors")
    assert raw == struct.pack(">I", expected)
    assert decode(DataType.UINT32, raw) == expected


def test_read_counter64_returns_uint64_bytes(sim: Simulator, adapter: SnmpAdapter) -> None:
    device = _device("core_switch", ())
    point = _point("core_switch", "uplink_in_octets", DataType.UINT64)
    raw = adapter.read(device, point)
    expected = sim.get_value("core_switch", "uplink_in_octets")
    assert raw == struct.pack(">Q", expected)
    assert decode(DataType.UINT64, raw) == expected
    assert expected > 2**32


def test_gauge32_converts_to_uint32_bytes() -> None:
    from pysnmp.proto.rfc1902 import Gauge32

    device = _device("ups", ())
    point = _point("ups", "battery_charge", DataType.UINT32)
    assert SnmpAdapter._to_bytes(device, point, Gauge32(4000000000)) == struct.pack(
        ">I", 4000000000
    )


def test_read_undefined_oid_names_device_and_point(adapter: SnmpAdapter) -> None:
    device = _device("core_switch", ())
    point = _point("core_switch", "sys_descr", DataType.INT32, oid=UNDEFINED_OID)
    with pytest.raises(AdapterReadError) as caught:
        adapter.read(device, point)
    assert not isinstance(caught.value, TimeoutError)
    _assert_plain_sentence(str(caught.value), "core_switch", "sys_descr")


def test_read_silence_raises_timeout_within_device_timeout(silent_adapter: SnmpAdapter) -> None:
    device = _device("core_switch", (), timeout=SILENT_TIMEOUT_SECONDS)
    point = _point("core_switch", "port3_status", DataType.INT32)
    started = time.monotonic()
    with pytest.raises(AdapterReadError) as caught:
        silent_adapter.read(device, point)
    elapsed = time.monotonic() - started
    assert isinstance(caught.value, TimeoutError)
    assert elapsed < SILENT_TIMEOUT_SECONDS + 1.0
    _assert_plain_sentence(str(caught.value), "core_switch", "port3_status")


def test_read_type_mismatch_names_device_point_and_types(adapter: SnmpAdapter) -> None:
    device = _device("core_switch", ())
    point = _point("core_switch", "port3_status", DataType.UINT64)
    with pytest.raises(AdapterReadError) as caught:
        adapter.read(device, point)
    message = str(caught.value)
    _assert_plain_sentence(message, "core_switch", "port3_status")
    assert "uint64" in message
    assert "INTEGER" in message


@pytest.mark.parametrize(
    "data_type", [DataType.INT16, DataType.UINT16, DataType.FLOAT32, DataType.BOOL]
)
def test_read_data_type_that_fits_no_snmp_type(adapter: SnmpAdapter, data_type: DataType) -> None:
    device = _device("core_switch", ())
    point = _point("core_switch", "port3_status", data_type)
    with pytest.raises(AdapterReadError) as caught:
        adapter.read(device, point)
    message = str(caught.value)
    _assert_plain_sentence(message, "core_switch", "port3_status")
    assert data_type.value in message


def test_health_ok(adapter: SnmpAdapter) -> None:
    point = _point("core_switch", "port3_status", DataType.INT32)
    assert adapter.health(_device("core_switch", (point,))) is HealthStatus.OK


def test_health_degraded_when_device_answers_with_an_error(adapter: SnmpAdapter) -> None:
    point = _point("core_switch", "sys_descr", DataType.INT32, oid=UNDEFINED_OID)
    assert adapter.health(_device("core_switch", (point,))) is HealthStatus.DEGRADED


def test_health_unreachable_when_device_is_silent(silent_adapter: SnmpAdapter) -> None:
    point = _point("core_switch", "port3_status", DataType.INT32)
    device = _device("core_switch", (point,), timeout=SILENT_TIMEOUT_SECONDS)
    assert silent_adapter.health(device) is HealthStatus.UNREACHABLE


def test_many_reads_keep_one_thread_and_one_loop(adapter: SnmpAdapter) -> None:
    device = _device("core_switch", ())
    point = _point("core_switch", "port3_status", DataType.INT32)
    adapter.read(device, point)
    threads_before = threading.active_count()
    loop_before = adapter._loop
    thread_before = adapter._thread
    assert loop_before is not None
    assert thread_before is not None
    assert thread_before.name == THREAD_NAME
    for _ in range(MANY_READS):
        assert adapter.read(device, point) == struct.pack(">i", 2)
    assert threading.active_count() == threads_before
    assert adapter._loop is loop_before
    assert adapter._thread is thread_before


def test_close_twice_does_not_fail_and_reads_then_say_not_connected(
    spare_adapter: SnmpAdapter,
) -> None:
    device = _device("core_switch", ())
    point = _point("core_switch", "port3_status", DataType.INT32)
    assert spare_adapter.read(device, point) == struct.pack(">i", 2)
    spare_adapter.close()
    spare_adapter.close()
    with pytest.raises(AdapterReadError) as caught:
        spare_adapter.read(device, point)
    assert "not connected" in str(caught.value)
    assert "pysnmp" not in str(caught.value).lower()


# ---------------------------------------------------------------------------
# Source scans
# ---------------------------------------------------------------------------


def _python_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.py")
        if not SKIPPED_DIRS.intersection(path.relative_to(root).parts)
    )


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_no_pysnmp_outside_adapter() -> None:
    offenders: list[str] = []
    for path in _python_files(REPO_ROOT):
        if path == ADAPTER_FILE or SNMP_TESTS_DIR in path.parents:
            continue
        if "pysnmp" in _imported_roots(path):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []
    assert "pysnmp" in _imported_roots(ADAPTER_FILE)


def test_no_set_outside_simulator() -> None:
    write_names = {"set_cmd", "SetRequestPDU", "next_cmd", "bulk_cmd"}
    offenders: list[str] = []
    for path in _python_files(REPO_ROOT):
        if path == SIMULATOR_FILE or SNMP_TESTS_DIR in path.parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.ImportFrom):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.Name):
                names = [node.id]
            elif isinstance(node, ast.Attribute):
                names = [node.attr]
                if node.attr == "SET" and isinstance(node.value, ast.Name):
                    names.append(f"{node.value.id}.SET")
            hits = [name for name in names if name in write_names or name == "PduType.SET"]
            offenders.extend(f"{path.relative_to(REPO_ROOT)}:{node.lineno} {h}" for h in hits)
    assert offenders == []
    adapter_tree = ast.parse(ADAPTER_FILE.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(adapter_tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("pysnmp")
        for alias in node.names
    }
    assert "get_cmd" in imported
    assert not {name for name in imported if name.endswith("_cmd")} - {"get_cmd"}


def test_skeleton_imports_neither_pysnmp_nor_apps() -> None:
    offenders: list[str] = []
    for path in _python_files(SKELETON_DIR):
        found = _imported_roots(path) & {"pysnmp", "apps"}
        offenders.extend(f"{path.relative_to(REPO_ROOT)} imports {name}" for name in sorted(found))
    assert offenders == []
