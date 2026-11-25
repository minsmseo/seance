"""pysnmp verification tests for the SNMP adapter (task 7.1).

These three tests check the pysnmp 7.1 details the adapter will rely on. They run
against the Simulator on a free localhost UDP port. The probe below is a throwaway
helper that lives only in this file: one private loop on one thread, one SnmpEngine.
The adapter code is written after the GitHub Actions result of these tests is known.

Validates: Requirements 2.16, 2.18, 2.21, 12.5, 12.10
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine, Iterator

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

from apps.snmp.simulator import Simulator

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
