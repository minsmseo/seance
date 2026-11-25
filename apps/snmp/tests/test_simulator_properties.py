"""Property tests for the SNMP simulator codec and drift.

No socket and no event loop: the Simulator is never started.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from apps.snmp import simulator as sim
from apps.snmp.simulator import (
    OID_MAP,
    PduType,
    Simulator,
    SnmpType,
    decode_response,
    decode_value,
    encode_value,
)

_NUMERIC_TYPES = (
    SnmpType.INTEGER,
    SnmpType.COUNTER32,
    SnmpType.GAUGE32,
    SnmpType.TIMETICKS,
    SnmpType.COUNTER64,
)
_EMPTY_TYPES = (
    SnmpType.NULL,
    SnmpType.NO_SUCH_OBJECT,
    SnmpType.NO_SUCH_INSTANCE,
    SnmpType.END_OF_MIB_VIEW,
)
_REQUEST_KINDS = (PduType.GET, PduType.GETNEXT, PduType.GETBULK, PduType.SET)
_MODULUS: dict[SnmpType, int] = {
    SnmpType.TIMETICKS: 2**32,
    SnmpType.COUNTER32: 2**32,
    SnmpType.COUNTER64: 2**64,
}


@st.composite
def _typed_values(draw: st.DrawFn) -> tuple[SnmpType, int | None]:
    """A value type with a value that fits it, or None for the empty types."""
    if draw(st.booleans()):
        return draw(st.sampled_from(_EMPTY_TYPES)), None
    value_type = draw(st.sampled_from(_NUMERIC_TYPES))
    low, high = sim._VALUE_RANGES[value_type]
    edge = st.sampled_from([low, high, 0 if low <= 0 <= high else low])
    return value_type, draw(st.one_of(st.integers(low, high), edge))


@st.composite
def _oids(draw: st.DrawFn) -> tuple[int, ...]:
    first = draw(st.integers(0, 2))
    second = draw(st.integers(0, 39 if first < 2 else 2**20))
    rest = draw(st.lists(st.integers(0, 2**32 - 1), max_size=12))
    return (first, second, *rest)


_COMMUNITIES = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=126), min_size=0, max_size=40
)


@settings(max_examples=200, deadline=None)
@given(_typed_values())
def test_value_round_trip(typed: tuple[SnmpType, int | None]) -> None:
    """Feature: app-snmp, Property 7: BER values round trip.

    **Validates: Requirements 1.9, 1.10**
    """
    value_type, value = typed
    raw = encode_value(value_type, value)
    tag, content, end = sim._read_tlv(raw, 0)
    assert end == len(raw)
    assert decode_value(tag, content) == (value_type, value)


@settings(max_examples=200, deadline=None)
@given(
    st.lists(_typed_values(), max_size=5),
    st.lists(_oids(), min_size=5, max_size=5),
    st.integers(-(2**31), 2**31 - 1),
    st.integers(0, 2**31 - 1),
)
def test_response_round_trip(
    typed: list[tuple[SnmpType, int | None]],
    oids: list[tuple[int, ...]],
    request_id: int,
    error_status: int,
) -> None:
    """Feature: app-snmp, Property 7: BER values round trip (response PDUs).

    **Validates: Requirements 1.9, 1.10**
    """
    binds = [(oids[i], encode_value(kind, value)) for i, (kind, value) in enumerate(typed)]
    body = sim._encode_response(request_id, error_status, 0, binds)
    data = sim._encode_message("core_switch", sim._TAG_RESPONSE, body)
    decoded = decode_response(data)
    assert decoded.request_id == request_id
    assert decoded.error_status == error_status
    assert [(b.oid, b.value_type, b.value) for b in decoded.varbinds] == [
        (sim._format_oid(oids[i]), kind, value) for i, (kind, value) in enumerate(typed)
    ]


@settings(max_examples=200, deadline=None)
@given(
    st.sampled_from(_REQUEST_KINDS),
    _COMMUNITIES,
    st.lists(_oids(), max_size=6),
    st.integers(0, 2**31 - 1),
)
def test_request_round_trip(
    kind: PduType, community: str, oids: list[tuple[int, ...]], request_id: int
) -> None:
    """Feature: app-snmp, Property 7: BER values round trip (request OIDs and community).

    **Validates: Requirements 1.9, 1.10**
    """
    texts = tuple(sim._format_oid(oid) for oid in oids)
    data = sim.encode_request(kind, community, texts, request_id=request_id)
    request = sim._decode_request(data)
    assert request.pdu_type == kind
    assert request.community == community
    assert request.request_id == request_id
    assert tuple(oid for oid, _ in request.varbinds) == tuple(oids)


def _run_drift(seed: int, steps: int) -> list[dict[tuple[str, str], int]]:
    simulator = Simulator("127.0.0.1", 0, seed, drift=False)
    states = [{(e.device, e.name): simulator.get_value(e.device, e.name) for e in OID_MAP}]
    for _ in range(steps):
        simulator.drift_step()
        states.append({(e.device, e.name): simulator.get_value(e.device, e.name) for e in OID_MAP})
    return states


@settings(max_examples=100, deadline=None)
@given(st.integers(0, 2**32 - 1), st.integers(0, 200))
def test_drift_deterministic_bounded_monotonic(seed: int, steps: int) -> None:
    """Feature: app-snmp, Property 8: Drift is deterministic, bounded and monotonic.

    **Validates: Requirements 1.3, 1.6, 1.7**
    """
    states = _run_drift(seed, steps)
    assert states == _run_drift(seed, steps)
    for entry in OID_MAP:
        key = (entry.device, entry.name)
        series = [state[key] for state in states]
        if entry.step == 0:
            assert set(series) == {entry.initial}
            continue
        if entry.snmp_type in _MODULUS:
            modulus = _MODULUS[entry.snmp_type]
            limit = 50 if entry.snmp_type == SnmpType.TIMETICKS else entry.step
            for before, after in zip(series, series[1:], strict=False):
                assert 0 <= (after - before) % modulus <= limit
                assert 0 <= after < modulus
        else:
            assert all(entry.minimum <= v <= entry.maximum for v in series)
