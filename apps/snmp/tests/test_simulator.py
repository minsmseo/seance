"""Unit tests for the SNMP simulator.

One Simulator is shared by the module, on a free localhost UDP port. The client side
is a plain UDP socket with a timeout, so no test creates an event loop of its own.

Validates: Requirements 1.1, 1.2, 1.4, 1.5, 1.8, 1.9, 1.10, 1.11, 1.12, 1.13, 1.14,
1.15, 12.1, 12.4
"""

from __future__ import annotations

import socket
import time
from collections.abc import Iterator

import pytest

from apps.snmp.simulator import (
    MAX_BULK_VARBINDS,
    NOT_WRITABLE,
    OID_MAP,
    PduRecord,
    PduType,
    Response,
    Simulator,
    SimulatorError,
    SnmpType,
    decode_response,
    encode_request,
)

HOST = "127.0.0.1"
TIMEOUT = 1.0
SILENCE_TIMEOUT = 0.4
UPTIME_OID = "1.3.6.1.2.1.1.3.0"
FIRST_STATUS_OID = "1.3.6.1.2.1.2.2.1.8.1"
PORT3_OID = "1.3.6.1.2.1.2.2.1.8.3"
LAST_CORE_OID = "1.3.6.1.2.1.31.1.1.1.10.5"
DEVICES = ("core_switch", "edge_router", "ups")


@pytest.fixture(scope="module")
def sim() -> Iterator[Simulator]:
    simulator = Simulator(HOST, 0, seed=1, drift=False)
    simulator.start()
    try:
        yield simulator
    finally:
        simulator.stop()


def exchange(port: int, data: bytes, timeout: float = TIMEOUT) -> bytes | None:
    """Send one datagram and return the answer, or None when nothing came back."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.settimeout(timeout)
        client.sendto(data, (HOST, port))
        try:
            answer, _ = client.recvfrom(65535)
        except TimeoutError:
            return None
    return answer


def ask(
    port: int,
    pdu_type: PduType,
    community: str,
    oids: tuple[str, ...],
    non_repeaters: int = 0,
    max_repetitions: int = 10,
) -> Response:
    raw = exchange(
        port,
        encode_request(
            pdu_type,
            community,
            oids,
            non_repeaters=non_repeaters,
            max_repetitions=max_repetitions,
        ),
    )
    assert raw is not None, "the simulator stayed silent"
    return decode_response(raw)


def test_start_picks_a_real_port(sim: Simulator) -> None:
    assert sim.running
    assert sim.port != 0


@pytest.mark.parametrize("device", DEVICES)
def test_each_device_answers_by_community(sim: Simulator, device: str) -> None:
    entry = next(e for e in OID_MAP if e.device == device)
    response = ask(sim.port, PduType.GET, device, (".".join(map(str, entry.oid)),))
    assert response.error_status == 0
    assert response.varbinds[0].value_type == entry.snmp_type
    assert response.varbinds[0].value == entry.initial


def test_unknown_community_gets_silence(sim: Simulator) -> None:
    raw = exchange(sim.port, encode_request(PduType.GET, "nobody", (UPTIME_OID,)), SILENCE_TIMEOUT)
    assert raw is None


def test_undefined_oid_gets_no_such_object(sim: Simulator) -> None:
    response = ask(sim.port, PduType.GET, "ups", ("1.3.6.1.2.1.99.99.0",))
    assert response.error_status == 0
    assert response.varbinds[0].oid == "1.3.6.1.2.1.99.99.0"
    assert response.varbinds[0].value_type == SnmpType.NO_SUCH_OBJECT


def test_get_returns_each_requested_oid_in_order(sim: Simulator) -> None:
    response = ask(sim.port, PduType.GET, "core_switch", (PORT3_OID, UPTIME_OID))
    assert [v.oid for v in response.varbinds] == [PORT3_OID, UPTIME_OID]
    assert response.varbinds[1].value_type == SnmpType.TIMETICKS


def test_getnext_returns_the_following_oid(sim: Simulator) -> None:
    response = ask(sim.port, PduType.GETNEXT, "core_switch", (UPTIME_OID,))
    assert response.varbinds[0].oid == FIRST_STATUS_OID
    assert response.varbinds[0].value == 1


def test_getnext_past_the_last_oid_gets_end_of_mib_view(sim: Simulator) -> None:
    response = ask(sim.port, PduType.GETNEXT, "core_switch", (LAST_CORE_OID,))
    assert response.varbinds[0].value_type == SnmpType.END_OF_MIB_VIEW


def test_getbulk_walks_forward_and_ends_with_end_of_mib_view(sim: Simulator) -> None:
    response = ask(sim.port, PduType.GETBULK, "ups", ("1.3.6.1",), 0, 10)
    types = [v.value_type for v in response.varbinds]
    assert types[-1] == SnmpType.END_OF_MIB_VIEW
    assert types[:-1] == [SnmpType.INTEGER] * 5
    oids = [v.oid for v in response.varbinds[:-1]]
    assert len(set(oids)) == 5


def test_getbulk_non_repeaters_use_getnext_once(sim: Simulator) -> None:
    response = ask(sim.port, PduType.GETBULK, "core_switch", (UPTIME_OID, UPTIME_OID), 1, 2)
    assert [v.oid for v in response.varbinds][0] == FIRST_STATUS_OID
    assert len(response.varbinds) == 1 + 2


def test_getbulk_is_capped_at_twenty_varbinds(sim: Simulator) -> None:
    oids = ("1.3.6.1", "1.3.6.1.2", "1.3.6.1.2.1")
    response = ask(sim.port, PduType.GETBULK, "core_switch", oids, 0, 50)
    assert MAX_BULK_VARBINDS == 20
    assert len(response.varbinds) == 20


def test_set_gets_not_writable_and_changes_nothing(sim: Simulator) -> None:
    before = sim.get_value("core_switch", "port3_status")
    response = ask(sim.port, PduType.SET, "core_switch", (PORT3_OID,))
    assert response.error_status == NOT_WRITABLE
    assert response.error_index == 1
    assert sim.get_value("core_switch", "port3_status") == before
    after = ask(sim.port, PduType.GET, "core_switch", (PORT3_OID,))
    assert after.varbinds[0].value == before


def test_pdu_record_lists_every_request_type_in_order(sim: Simulator) -> None:
    start = len(sim.pdus_seen)
    kinds = (PduType.GET, PduType.GETNEXT, PduType.GETBULK, PduType.SET)
    for kind in kinds:
        ask(sim.port, kind, "ups", (UPTIME_OID,))
    new = sim.pdus_seen[start:]
    assert [r.pdu_type for r in new] == list(kinds)
    assert all(r == PduRecord(r.pdu_type, "ups", (UPTIME_OID,)) for r in new)


def test_malformed_datagram_is_not_recorded(sim: Simulator) -> None:
    start = len(sim.pdus_seen)
    assert exchange(sim.port, b"\x30\x05garbage", SILENCE_TIMEOUT) is None
    ask(sim.port, PduType.GET, "ups", (UPTIME_OID,))
    new = sim.pdus_seen[start:]
    assert [r.pdu_type for r in new] == [PduType.GET]


def test_default_seed_reports_port3_down_and_other_statuses_healthy(sim: Simulator) -> None:
    assert sim.seed == 1
    assert sim.get_value("core_switch", "port3_status") == 2
    for entry in OID_MAP:
        is_status = entry.name.endswith("_status") or entry.name == "power_source"
        if is_status and (entry.device, entry.name) != ("core_switch", "port3_status"):
            healthy = 3 if entry.name == "power_source" else 1
            assert sim.get_value(entry.device, entry.name) == healthy, entry.name


def test_drift_changes_values_within_one_second() -> None:
    drifting = Simulator(HOST, 0, seed=1, drift=True)
    drifting.start()
    try:
        before = drifting.get_value("core_switch", "uptime")
        time.sleep(1.2)
        response = ask(drifting.port, PduType.GET, "core_switch", (UPTIME_OID,))
        assert response.varbinds[0].value != before
        assert drifting.get_value("core_switch", "port3_status") == 2
    finally:
        drifting.stop()


def test_stop_is_fast_and_the_port_can_be_bound_again() -> None:
    first = Simulator(HOST, 0, seed=1, drift=True)
    first.start()
    port = first.port
    began = time.monotonic()
    first.stop()
    assert time.monotonic() - began < 2.0
    assert not first.running
    second = Simulator(HOST, port, seed=1, drift=False)
    second.start()
    try:
        assert second.port == port
    finally:
        second.stop()


def test_second_start_raises() -> None:
    simulator = Simulator(HOST, 0, seed=1, drift=False)
    simulator.start()
    try:
        with pytest.raises(SimulatorError, match="already running"):
            simulator.start()
    finally:
        simulator.stop()


def test_busy_port_message_names_the_port(sim: Simulator) -> None:
    other = Simulator(HOST, sim.port, seed=1, drift=False)
    with pytest.raises(SimulatorError) as info:
        other.start()
    assert str(sim.port) in str(info.value)
    assert not other.running
