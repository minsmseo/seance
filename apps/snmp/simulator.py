"""SNMP v2c simulator for a small network: a core switch, an edge router and a UPS.

The simulator does not import pysnmp. It speaks a small, bounded part of SNMP v2c
with its own BER codec, so every adapter test is also an interoperability test.
Only ``adapter.py`` imports pysnmp. No other file builds a SET PDU: the request
encoder used by tests lives here.

Supported on the wire:

- Version v2c only (version field 1). Other versions are dropped.
- Request PDUs GET (A0), GETNEXT (A1), SET (A3) and GETBULK (A5). The answer is
  the response PDU (A2).
- Value types Integer32 (02), Counter32 (41), Gauge32 (42), TimeTicks (43),
  Counter64 (46), NULL (05) and the exception values noSuchObject (80),
  noSuchInstance (81) and endOfMibView (82).

Each device is selected by the community string of the request. ``OID_MAP`` is the
single source of truth for the OIDs, types, start values, ranges and drift steps;
``devices.yaml`` must match it. ``memory_used`` counts MiB (one allocation unit is
1 MiB) and ``on_battery`` is upsOutputSource (3 normal, 5 battery).

This module holds the codec and the request handling (``SnmpResponder``). The UDP
server, drift task and lifecycle are added on top of it.
"""

from __future__ import annotations

import asyncio
import random
import threading
from dataclasses import dataclass
from enum import StrEnum

SNMP_V2C_VERSION = 1
DRIFT_INTERVAL_SECONDS = 0.5
TIMETICKS_PER_TICK = 50
_START_TIMEOUT_SECONDS = 5.0
_STOP_TIMEOUT_SECONDS = 2.0
MAX_BULK_VARBINDS = 20
NOT_WRITABLE = 17
_UINT32_MAX = 2**32 - 1
_UINT64_MAX = 2**64 - 1
_INT32_MIN = -(2**31)
_INT32_MAX = 2**31 - 1

_TAG_INTEGER = 0x02
_TAG_OCTET_STRING = 0x04
_TAG_NULL = 0x05
_TAG_OID = 0x06
_TAG_SEQUENCE = 0x30
_TAG_COUNTER32 = 0x41
_TAG_GAUGE32 = 0x42
_TAG_TIMETICKS = 0x43
_TAG_COUNTER64 = 0x46
_TAG_NO_SUCH_OBJECT = 0x80
_TAG_NO_SUCH_INSTANCE = 0x81
_TAG_END_OF_MIB_VIEW = 0x82
_TAG_GET = 0xA0
_TAG_GETNEXT = 0xA1
_TAG_RESPONSE = 0xA2
_TAG_SET = 0xA3
_TAG_GETBULK = 0xA5

Oid = tuple[int, ...]


class SimulatorError(RuntimeError):
    """Raised with a short sentence when the simulator cannot encode, decode, start or stop."""


class BerError(ValueError):
    """Raised when bytes are not valid BER for the small subset this simulator speaks."""


class PduType(StrEnum):
    """The SNMP request kinds the simulator records."""

    GET = "GET"
    GETNEXT = "GETNEXT"
    GETBULK = "GETBULK"
    SET = "SET"


@dataclass(frozen=True)
class PduRecord:
    """One request the simulator decoded: its kind, community and requested OIDs."""

    pdu_type: PduType
    community: str
    oids: tuple[str, ...]


class SnmpType(StrEnum):
    """Value types that can appear in a varbind."""

    INTEGER = "INTEGER"
    COUNTER32 = "Counter32"
    GAUGE32 = "Gauge32"
    TIMETICKS = "TimeTicks"
    COUNTER64 = "Counter64"
    NULL = "NULL"
    NO_SUCH_OBJECT = "noSuchObject"
    NO_SUCH_INSTANCE = "noSuchInstance"
    END_OF_MIB_VIEW = "endOfMibView"


@dataclass(frozen=True)
class VarBind:
    """One decoded variable binding. ``value`` is None for NULL and the exception types."""

    oid: str
    value_type: SnmpType
    value: int | None


@dataclass(frozen=True)
class Response:
    """A decoded response PDU."""

    request_id: int
    error_status: int
    error_index: int
    varbinds: tuple[VarBind, ...]


@dataclass(frozen=True)
class OidEntry:
    """One simulated value: which device holds it, its OID, type, start value and drift."""

    device: str
    name: str
    oid: Oid
    snmp_type: SnmpType
    initial: int
    minimum: int
    maximum: int
    step: int


_STATUS_MAX = 7
_IF_OPER_STATUS = (1, 3, 6, 1, 2, 1, 2, 2, 1, 8)
_SYS_UPTIME = (1, 3, 6, 1, 2, 1, 1, 3, 0)
_HC_IN = (1, 3, 6, 1, 2, 1, 31, 1, 1, 1, 6)
_HC_OUT = (1, 3, 6, 1, 2, 1, 31, 1, 1, 1, 10)

OID_MAP: tuple[OidEntry, ...] = (
    OidEntry("core_switch", "uptime", _SYS_UPTIME, SnmpType.TIMETICKS, 8640000, 0, _UINT32_MAX, 50),
    OidEntry("core_switch", "port1_status", (*_IF_OPER_STATUS, 1), SnmpType.INTEGER, 1, 1, 7, 0),
    OidEntry("core_switch", "port2_status", (*_IF_OPER_STATUS, 2), SnmpType.INTEGER, 1, 1, 7, 0),
    OidEntry("core_switch", "port3_status", (*_IF_OPER_STATUS, 3), SnmpType.INTEGER, 2, 1, 7, 0),
    OidEntry("core_switch", "port4_status", (*_IF_OPER_STATUS, 4), SnmpType.INTEGER, 1, 1, 7, 0),
    OidEntry(
        "core_switch",
        "uplink_in_octets",
        (*_HC_IN, 5),
        SnmpType.COUNTER64,
        5000000000,
        0,
        _UINT64_MAX,
        400000,
    ),
    OidEntry(
        "core_switch",
        "uplink_out_octets",
        (*_HC_OUT, 5),
        SnmpType.COUNTER64,
        3200000000,
        0,
        _UINT64_MAX,
        300000,
    ),
    OidEntry(
        "core_switch",
        "uplink_in_errors",
        (1, 3, 6, 1, 2, 1, 2, 2, 1, 14, 5),
        SnmpType.COUNTER32,
        12,
        0,
        _UINT32_MAX,
        1,
    ),
    OidEntry("edge_router", "uptime", _SYS_UPTIME, SnmpType.TIMETICKS, 4320000, 0, _UINT32_MAX, 50),
    OidEntry(
        "edge_router",
        "cpu_load",
        (1, 3, 6, 1, 2, 1, 25, 3, 3, 1, 2, 1),
        SnmpType.INTEGER,
        23,
        0,
        100,
        3,
    ),
    OidEntry(
        "edge_router",
        "memory_used",
        (1, 3, 6, 1, 2, 1, 25, 2, 3, 1, 6, 1),
        SnmpType.INTEGER,
        412,
        0,
        1024,
        8,
    ),
    OidEntry("edge_router", "wan_link_status", (*_IF_OPER_STATUS, 1), SnmpType.INTEGER, 1, 1, 7, 0),
    OidEntry(
        "edge_router",
        "wan_in_octets",
        (*_HC_IN, 1),
        SnmpType.COUNTER64,
        7000000000,
        0,
        _UINT64_MAX,
        250000,
    ),
    OidEntry(
        "edge_router",
        "wan_out_octets",
        (*_HC_OUT, 1),
        SnmpType.COUNTER64,
        2100000000,
        0,
        _UINT64_MAX,
        120000,
    ),
    OidEntry(
        "ups",
        "battery_charge",
        (1, 3, 6, 1, 2, 1, 33, 1, 2, 4, 0),
        SnmpType.INTEGER,
        98,
        0,
        100,
        1,
    ),
    OidEntry(
        "ups",
        "runtime_remaining",
        (1, 3, 6, 1, 2, 1, 33, 1, 2, 3, 0),
        SnmpType.INTEGER,
        42,
        0,
        120,
        1,
    ),
    OidEntry(
        "ups",
        "on_battery",
        (1, 3, 6, 1, 2, 1, 33, 1, 4, 1, 0),
        SnmpType.INTEGER,
        3,
        1,
        _STATUS_MAX,
        0,
    ),
    OidEntry(
        "ups",
        "output_load",
        (1, 3, 6, 1, 2, 1, 33, 1, 4, 4, 1, 5, 1),
        SnmpType.INTEGER,
        37,
        0,
        100,
        2,
    ),
    OidEntry(
        "ups",
        "temperature",
        (1, 3, 6, 1, 2, 1, 33, 1, 2, 7, 0),
        SnmpType.INTEGER,
        27,
        15,
        45,
        1,
    ),
)

_DEVICES: frozenset[str] = frozenset(entry.device for entry in OID_MAP)
_BY_DEVICE: dict[str, tuple[OidEntry, ...]] = {
    device: tuple(sorted((e for e in OID_MAP if e.device == device), key=lambda e: e.oid))
    for device in sorted(_DEVICES)
}
_MAP_BY_KEY: dict[tuple[str, str], OidEntry] = {(e.device, e.name): e for e in OID_MAP}

_VALUE_TAGS: dict[SnmpType, int] = {
    SnmpType.INTEGER: _TAG_INTEGER,
    SnmpType.COUNTER32: _TAG_COUNTER32,
    SnmpType.GAUGE32: _TAG_GAUGE32,
    SnmpType.TIMETICKS: _TAG_TIMETICKS,
    SnmpType.COUNTER64: _TAG_COUNTER64,
    SnmpType.NULL: _TAG_NULL,
    SnmpType.NO_SUCH_OBJECT: _TAG_NO_SUCH_OBJECT,
    SnmpType.NO_SUCH_INSTANCE: _TAG_NO_SUCH_INSTANCE,
    SnmpType.END_OF_MIB_VIEW: _TAG_END_OF_MIB_VIEW,
}
_TAG_TO_TYPE: dict[int, SnmpType] = {tag: kind for kind, tag in _VALUE_TAGS.items()}
_VALUE_RANGES: dict[SnmpType, tuple[int, int]] = {
    SnmpType.INTEGER: (_INT32_MIN, _INT32_MAX),
    SnmpType.COUNTER32: (0, _UINT32_MAX),
    SnmpType.GAUGE32: (0, _UINT32_MAX),
    SnmpType.TIMETICKS: (0, _UINT32_MAX),
    SnmpType.COUNTER64: (0, _UINT64_MAX),
}
_PDU_TAGS: dict[PduType, int] = {
    PduType.GET: _TAG_GET,
    PduType.GETNEXT: _TAG_GETNEXT,
    PduType.SET: _TAG_SET,
    PduType.GETBULK: _TAG_GETBULK,
}
_TAG_TO_PDU: dict[int, PduType] = {tag: kind for kind, tag in _PDU_TAGS.items()}
_EXCEPTION_TYPES: frozenset[SnmpType] = frozenset(
    {SnmpType.NO_SUCH_OBJECT, SnmpType.NO_SUCH_INSTANCE, SnmpType.END_OF_MIB_VIEW}
)


# ---------------------------------------------------------------------------
# BER codec
# ---------------------------------------------------------------------------


def _encode_length(length: int) -> bytes:
    if length < 0x80:
        return bytes([length])
    body = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(body)]) + body


def _tlv(tag: int, content: bytes) -> bytes:
    return bytes([tag]) + _encode_length(len(content)) + content


def _encode_int_content(value: int) -> bytes:
    """Minimal two's complement bytes, with a leading zero when a positive value needs it."""
    magnitude = value if value >= 0 else ~value
    length = (magnitude.bit_length() + 8) // 8
    return value.to_bytes(length, "big", signed=True)


def _encode_base128(number: int) -> bytes:
    out = [number & 0x7F]
    number >>= 7
    while number:
        out.append(0x80 | (number & 0x7F))
        number >>= 7
    return bytes(reversed(out))


def encode_oid_content(oid: Oid) -> bytes:
    """Encode the content bytes of an OID. Needs two arcs, first at most 2."""
    if len(oid) < 2 or oid[0] > 2 or (oid[0] < 2 and oid[1] > 39) or min(oid) < 0:
        raise BerError("The OID is not valid.")
    out = _encode_base128(oid[0] * 40 + oid[1])
    for arc in oid[2:]:
        out += _encode_base128(arc)
    return out


def decode_oid_content(content: bytes) -> Oid:
    """Decode the content bytes of an OID."""
    if not content or content[-1] & 0x80:
        raise BerError("The OID is not valid.")
    numbers: list[int] = []
    current = 0
    for byte in content:
        current = (current << 7) | (byte & 0x7F)
        if not byte & 0x80:
            numbers.append(current)
            current = 0
    first = numbers[0]
    head = (0, first) if first < 40 else (1, first - 40) if first < 80 else (2, first - 80)
    return (*head, *numbers[1:])


def encode_value(value_type: SnmpType, value: int | None) -> bytes:
    """Encode one value as a full TLV. NULL and the exception types carry no value."""
    tag = _VALUE_TAGS[value_type]
    if value_type == SnmpType.NULL or value_type in _EXCEPTION_TYPES:
        return _tlv(tag, b"")
    if value is None:
        raise BerError(f"A {value_type} value needs a number.")
    low, high = _VALUE_RANGES[value_type]
    if not low <= value <= high:
        raise BerError(f"The value {value} does not fit {value_type}.")
    return _tlv(tag, _encode_int_content(value))


def decode_value(tag: int, content: bytes) -> tuple[SnmpType, int | None]:
    """Decode the tag and content of one value."""
    value_type = _TAG_TO_TYPE.get(tag)
    if value_type is None:
        raise BerError("The value type is not supported.")
    if value_type == SnmpType.NULL or value_type in _EXCEPTION_TYPES:
        if content:
            raise BerError("The value must be empty.")
        return value_type, None
    if not content or len(content) > 9:
        raise BerError("The integer length is not valid.")
    low, high = _VALUE_RANGES[value_type]
    number = int.from_bytes(content, "big", signed=value_type == SnmpType.INTEGER)
    if not low <= number <= high:
        raise BerError("The integer is out of range.")
    return value_type, number


def _read_tlv(data: bytes, position: int) -> tuple[int, bytes, int]:
    """Read one TLV at ``position``. Returns tag, content and the position after it."""
    if position + 2 > len(data):
        raise BerError("The data ends too early.")
    tag = data[position]
    first = data[position + 1]
    position += 2
    if tag & 0x1F == 0x1F:
        raise BerError("Multi-byte tags are not supported.")
    if first < 0x80:
        length = first
    else:
        count = first & 0x7F
        if count == 0 or count > 4 or position + count > len(data):
            raise BerError("The length is not valid.")
        length = int.from_bytes(data[position : position + count], "big")
        position += count
    end = position + length
    if end > len(data):
        raise BerError("The data ends too early.")
    return tag, data[position:end], end


def _read_items(content: bytes) -> list[tuple[int, bytes]]:
    """Split content into its TLVs, consuming all of it."""
    items: list[tuple[int, bytes]] = []
    position = 0
    while position < len(content):
        tag, body, position = _read_tlv(content, position)
        items.append((tag, body))
    return items


def _int_item(item: tuple[int, bytes]) -> int:
    tag, content = item
    if tag != _TAG_INTEGER or not content or len(content) > 9:
        raise BerError("An integer was expected.")
    return int.from_bytes(content, "big", signed=True)


def _format_oid(oid: Oid) -> str:
    return ".".join(str(arc) for arc in oid)


def _parse_oid_text(text: str) -> Oid:
    try:
        oid = tuple(int(part) for part in text.split("."))
        encode_oid_content(oid)
    except (ValueError, BerError) as exc:
        raise SimulatorError(f"The OID {text!r} is not valid. Use dotted numbers.") from exc
    return oid


def _encode_message(community: str, pdu_tag: int, pdu_body: bytes) -> bytes:
    version = _tlv(_TAG_INTEGER, _encode_int_content(SNMP_V2C_VERSION))
    name = _tlv(_TAG_OCTET_STRING, community.encode("utf-8"))
    return _tlv(_TAG_SEQUENCE, version + name + _tlv(pdu_tag, pdu_body))


def _encode_varbinds(items: list[tuple[Oid, bytes]]) -> bytes:
    binds = b"".join(
        _tlv(_TAG_SEQUENCE, _tlv(_TAG_OID, encode_oid_content(oid)) + value) for oid, value in items
    )
    return _tlv(_TAG_SEQUENCE, binds)


def encode_request(
    pdu_type: PduType,
    community: str,
    oids: tuple[str, ...],
    request_id: int = 1,
    non_repeaters: int = 0,
    max_repetitions: int = 10,
) -> bytes:
    """Build a v2c request datagram. This is the only place a SET PDU is built.

    GET, GETNEXT and GETBULK carry NULL values. SET carries the integer 0 for each
    OID. For GETBULK, ``non_repeaters`` and ``max_repetitions`` fill the two fields
    that are the error status and index in the other PDUs.
    """
    value = (
        encode_value(SnmpType.INTEGER, 0)
        if pdu_type == PduType.SET
        else encode_value(SnmpType.NULL, None)
    )
    try:
        varbinds = _encode_varbinds([(_parse_oid_text(text), value) for text in oids])
        field_a, field_b = (
            (non_repeaters, max_repetitions) if pdu_type == PduType.GETBULK else (0, 0)
        )
        body = (
            _tlv(_TAG_INTEGER, _encode_int_content(request_id))
            + _tlv(_TAG_INTEGER, _encode_int_content(field_a))
            + _tlv(_TAG_INTEGER, _encode_int_content(field_b))
            + varbinds
        )
        return _encode_message(community, _PDU_TAGS[pdu_type], body)
    except BerError as exc:
        raise SimulatorError(f"The request could not be encoded ({exc}).") from exc


def decode_response(data: bytes) -> Response:
    """Decode a v2c response datagram. Raises SimulatorError when it is not one."""
    try:
        return _decode_response(data)
    except BerError as exc:
        raise SimulatorError(f"The response could not be decoded ({exc}).") from exc


def _decode_response(data: bytes) -> Response:
    tag, content, end = _read_tlv(data, 0)
    if tag != _TAG_SEQUENCE or end != len(data):
        raise BerError("A message sequence was expected.")
    items = _read_items(content)
    if len(items) != 3 or _int_item(items[0]) != SNMP_V2C_VERSION:
        raise BerError("The message is not SNMP v2c.")
    if items[2][0] != _TAG_RESPONSE:
        raise BerError("A response PDU was expected.")
    fields = _read_items(items[2][1])
    if len(fields) != 4 or fields[3][0] != _TAG_SEQUENCE:
        raise BerError("The PDU is not valid.")
    varbinds: list[VarBind] = []
    for bind_tag, bind_content in _read_items(fields[3][1]):
        parts = _read_items(bind_content)
        if bind_tag != _TAG_SEQUENCE or len(parts) != 2 or parts[0][0] != _TAG_OID:
            raise BerError("A varbind is not valid.")
        value_type, value = decode_value(*parts[1])
        varbinds.append(VarBind(_format_oid(decode_oid_content(parts[0][1])), value_type, value))
    return Response(
        request_id=_int_item(fields[0]),
        error_status=_int_item(fields[1]),
        error_index=_int_item(fields[2]),
        varbinds=tuple(varbinds),
    )


@dataclass(frozen=True)
class _Request:
    pdu_type: PduType
    community: str
    request_id: int
    field_a: int
    field_b: int
    varbinds: tuple[tuple[Oid, bytes], ...]


def _decode_request(data: bytes) -> _Request:
    """Decode a v2c request. Raises BerError for anything else."""
    tag, content, end = _read_tlv(data, 0)
    if tag != _TAG_SEQUENCE or end != len(data):
        raise BerError("A message sequence was expected.")
    items = _read_items(content)
    if len(items) != 3:
        raise BerError("The message is not valid.")
    if _int_item(items[0]) != SNMP_V2C_VERSION:
        raise BerError("The version is not v2c.")
    if items[1][0] != _TAG_OCTET_STRING:
        raise BerError("A community was expected.")
    try:
        community = items[1][1].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BerError("The community is not text.") from exc
    pdu_type = _TAG_TO_PDU.get(items[2][0])
    if pdu_type is None:
        raise BerError("The PDU is not a request.")
    fields = _read_items(items[2][1])
    if len(fields) != 4 or fields[3][0] != _TAG_SEQUENCE:
        raise BerError("The PDU is not valid.")
    varbinds: list[tuple[Oid, bytes]] = []
    for bind_tag, bind_content in _read_items(fields[3][1]):
        parts = _read_items(bind_content)
        if bind_tag != _TAG_SEQUENCE or len(parts) != 2 or parts[0][0] != _TAG_OID:
            raise BerError("A varbind is not valid.")
        varbinds.append((decode_oid_content(parts[0][1]), _tlv(*parts[1])))
    return _Request(
        pdu_type=pdu_type,
        community=community,
        request_id=_int_item(fields[0]),
        field_a=_int_item(fields[1]),
        field_b=_int_item(fields[2]),
        varbinds=tuple(varbinds),
    )


def _encode_response(
    request_id: int,
    error_status: int,
    error_index: int,
    varbinds: list[tuple[Oid, bytes]],
) -> bytes:
    body = (
        _tlv(_TAG_INTEGER, _encode_int_content(request_id))
        + _tlv(_TAG_INTEGER, _encode_int_content(error_status))
        + _tlv(_TAG_INTEGER, _encode_int_content(error_index))
        + _encode_varbinds(varbinds)
    )
    return body


# ---------------------------------------------------------------------------
# Request handling
# ---------------------------------------------------------------------------


class SnmpResponder:
    """Simulated state of the three devices and the answers to v2c requests.

    ``handle_datagram`` takes one received datagram and returns the response bytes,
    or None when the simulator must stay silent. It never raises for bad input. It
    holds no socket and no event loop, so tests can call it directly.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[tuple[str, str], int] = {
            (entry.device, entry.name): entry.initial for entry in OID_MAP
        }
        self._records: list[PduRecord] = []

    @property
    def pdus_seen(self) -> tuple[PduRecord, ...]:
        """Every decoded request so far, in arrival order (a snapshot)."""
        with self._lock:
            return tuple(self._records)

    def get_value(self, device: str, name: str) -> int:
        """Return the current raw value of a point. Raises SimulatorError if unknown."""
        key = self._key(device, name)
        with self._lock:
            return self._values[key]

    def set_value(self, device: str, name: str, value: int) -> None:
        """Set the raw value of a point, clamped to its range (for tests)."""
        key = self._key(device, name)
        entry = _MAP_BY_KEY[key]
        with self._lock:
            self._values[key] = min(max(value, entry.minimum), entry.maximum)

    def apply_drift(self, rng: random.Random) -> None:
        """Apply one drift tick under the state lock, drawing from ``rng`` in map order.

        One draw is taken per gauge, integer or counter entry with ``step > 0``.
        TimeTicks add a fixed 50 and take no draw. Status values stay unchanged.
        """
        with self._lock:
            for entry in OID_MAP:
                if entry.step <= 0:
                    continue
                key = (entry.device, entry.name)
                value = self._values[key]
                if entry.snmp_type == SnmpType.TIMETICKS:
                    value = (value + TIMETICKS_PER_TICK) % (_UINT32_MAX + 1)
                elif entry.snmp_type == SnmpType.COUNTER32:
                    value = (value + rng.randint(0, entry.step)) % (_UINT32_MAX + 1)
                elif entry.snmp_type == SnmpType.COUNTER64:
                    value = (value + rng.randint(0, entry.step)) % (_UINT64_MAX + 1)
                else:
                    value += rng.randint(-entry.step, entry.step)
                    value = min(max(value, entry.minimum), entry.maximum)
                self._values[key] = value

    @staticmethod
    def _key(device: str, name: str) -> tuple[str, str]:
        if (device, name) not in _MAP_BY_KEY:
            raise SimulatorError(f"Unknown point {name} on device {device}. Check the name.")
        return device, name

    def handle_datagram(self, data: bytes) -> bytes | None:
        """Answer one datagram, or return None to send nothing.

        Malformed datagrams and wrong versions are dropped and not recorded. Every
        decoded request is recorded. An unknown community gets no answer.
        """
        try:
            request = _decode_request(data)
        except BerError:
            return None
        with self._lock:
            self._records.append(
                PduRecord(
                    request.pdu_type,
                    request.community,
                    tuple(_format_oid(oid) for oid, _ in request.varbinds),
                )
            )
        if request.community not in _DEVICES:
            return None
        try:
            body = self._answer(request)
            return _encode_message(request.community, _TAG_RESPONSE, body)
        except BerError:
            return None

    def _answer(self, request: _Request) -> bytes:
        device = request.community
        oids = [oid for oid, _ in request.varbinds]
        if request.pdu_type == PduType.SET:
            echoed = [(oid, raw) for oid, raw in request.varbinds]
            index = 1 if echoed else 0
            return _encode_response(request.request_id, NOT_WRITABLE, index, echoed)
        if request.pdu_type == PduType.GET:
            binds = [self._get(device, oid) for oid in oids]
        elif request.pdu_type == PduType.GETNEXT:
            binds = [self._next(device, oid) for oid in oids]
        else:
            binds = self._bulk(device, oids, request.field_a, request.field_b)
        return _encode_response(request.request_id, 0, 0, binds)

    def _value_bind(self, entry: OidEntry) -> tuple[Oid, bytes]:
        with self._lock:
            value = self._values[(entry.device, entry.name)]
        return entry.oid, encode_value(entry.snmp_type, value)

    def _get(self, device: str, oid: Oid) -> tuple[Oid, bytes]:
        for entry in _BY_DEVICE[device]:
            if entry.oid == oid:
                return self._value_bind(entry)
        return oid, encode_value(SnmpType.NO_SUCH_OBJECT, None)

    def _next(self, device: str, oid: Oid) -> tuple[Oid, bytes]:
        for entry in _BY_DEVICE[device]:
            if entry.oid > oid:
                return self._value_bind(entry)
        return oid, encode_value(SnmpType.END_OF_MIB_VIEW, None)

    def _bulk(
        self, device: str, oids: list[Oid], non_repeaters: int, max_repetitions: int
    ) -> list[tuple[Oid, bytes]]:
        """GETBULK: GETNEXT for the first N OIDs, then rounds over the rest, 20 varbinds at most."""
        plain = min(max(non_repeaters, 0), len(oids))
        binds = [self._next(device, oid) for oid in oids[:plain]]
        current = oids[plain:]
        end_marker = encode_value(SnmpType.END_OF_MIB_VIEW, None)
        for _ in range(max(max_repetitions, 0)):
            if not current or len(binds) >= MAX_BULK_VARBINDS:
                break
            round_binds = [self._next(device, oid) for oid in current]
            for bind in round_binds:
                if len(binds) < MAX_BULK_VARBINDS:
                    binds.append(bind)
            current = [oid for oid, _ in round_binds]
            if all(raw == end_marker for _, raw in round_binds):
                break
        return binds[:MAX_BULK_VARBINDS]


# ---------------------------------------------------------------------------
# UDP server, drift task and lifecycle
# ---------------------------------------------------------------------------


class _UdpProtocol(asyncio.DatagramProtocol):
    """Hands each datagram to the responder and sends back its answer, if any."""

    def __init__(self, responder: SnmpResponder) -> None:
        self._responder = responder
        self._transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        if isinstance(transport, asyncio.DatagramTransport):
            self._transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str | int, ...]) -> None:
        answer = self._responder.handle_datagram(data)
        if answer is not None and self._transport is not None:
            self._transport.sendto(answer, addr)


class Simulator:
    """The simulated network gear behind one UDP port.

    One asyncio loop runs on one daemon thread per Simulator. ``drift_step`` works
    on an unstarted Simulator, so tests can drive it with no socket and no loop.
    ``drift=False`` turns off only the periodic task, not what ``drift_step`` does.
    """

    def __init__(self, host: str, port: int, seed: int, drift: bool = True) -> None:
        self._host = host
        self._port = port
        self._seed = seed
        self._drift = drift
        self._responder = SnmpResponder()
        self._rng = random.Random(seed)
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._transport: asyncio.DatagramTransport | None = None
        self._drift_task: asyncio.Task[None] | None = None
        self._ready = threading.Event()
        self._start_error: str | None = None
        self._running = False

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        """The requested port, or the real port after ``start`` when 0 was requested."""
        return self._port

    @property
    def seed(self) -> int:
        return self._seed

    @property
    def running(self) -> bool:
        return self._running

    @property
    def pdus_seen(self) -> tuple[PduRecord, ...]:
        """Every decoded request so far, in arrival order (a snapshot)."""
        return self._responder.pdus_seen

    def get_value(self, device: str, name: str) -> int:
        """Return the current raw value of a point (for tests)."""
        return self._responder.get_value(device, name)

    def set_value(self, device: str, name: str, value: int) -> None:
        """Set the raw value of a point, clamped to its range (for tests)."""
        self._responder.set_value(device, name, value)

    def drift_step(self) -> None:
        """Apply one drift tick. Safe to call from any thread, started or not."""
        self._responder.apply_drift(self._rng)

    def start(self) -> None:
        """Open the UDP port and begin answering. Port 0 picks a free port."""
        if self._thread is not None:
            raise SimulatorError("The simulator is already running. Stop it before starting again.")
        self._ready.clear()
        self._start_error = None
        thread = threading.Thread(target=self._run, name="snmp-simulator", daemon=True)
        self._thread = thread
        thread.start()
        if not self._ready.wait(_START_TIMEOUT_SECONDS):
            self._thread = None
            raise SimulatorError("The simulator did not start in time. Try again.")
        if self._start_error is not None:
            thread.join(_STOP_TIMEOUT_SECONDS)
            self._thread = None
            raise SimulatorError(self._start_error)
        self._running = True

    def stop(self) -> None:
        """Cancel the drift task, close the port, stop the loop and join the thread."""
        thread = self._thread
        if thread is None:
            return
        loop = self._loop
        if loop is not None and thread.is_alive():
            try:
                loop.call_soon_threadsafe(self._shutdown)
            except RuntimeError:
                pass
        thread.join(_STOP_TIMEOUT_SECONDS)
        self._running = False
        self._thread = None

    def _shutdown(self) -> None:
        """Runs on the loop thread."""
        if self._drift_task is not None:
            self._drift_task.cancel()
        if self._transport is not None:
            self._transport.close()
        if self._loop is not None:
            self._loop.stop()

    async def _drift_forever(self) -> None:
        while True:
            await asyncio.sleep(DRIFT_INTERVAL_SECONDS)
            self.drift_step()

    async def _open(self, loop: asyncio.AbstractEventLoop) -> None:
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _UdpProtocol(self._responder),
            local_addr=(self._host, self._port),
            reuse_port=False,
        )
        if not isinstance(transport, asyncio.DatagramTransport):
            transport.close()
            raise OSError("The UDP endpoint is not a datagram transport.")
        self._transport = transport
        sockname = transport.get_extra_info("sockname")
        if isinstance(sockname, tuple) and len(sockname) >= 2 and isinstance(sockname[1], int):
            self._port = sockname[1]
        if self._drift:
            self._drift_task = loop.create_task(self._drift_forever())

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        try:
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._open(loop))
            except OSError as exc:
                self._start_error = self._describe_open_error(exc)
                return
            finally:
                self._ready.set()
            loop.run_forever()
        finally:
            try:
                if self._drift_task is not None:
                    self._drift_task.cancel()
                    loop.run_until_complete(
                        asyncio.gather(self._drift_task, return_exceptions=True)
                    )
                if self._transport is not None:
                    self._transport.close()
                loop.run_until_complete(asyncio.sleep(0))
            finally:
                self._drift_task = None
                self._transport = None
                loop.close()
                self._loop = None

    def _describe_open_error(self, exc: OSError) -> str:
        busy = getattr(exc, "winerror", None) == 10048 or exc.errno in (98, 48, 10048)
        if busy:
            return f"Port {self._port} is already in use. Try another port."
        reason = exc.strerror or "the address could not be used"
        where = f"UDP port {self._port} on {self._host}"
        return f"Could not open {where} ({reason}). Try another host or port."
