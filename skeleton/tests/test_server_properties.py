"""Property tests for the Tool_Server (Properties 7, 8 and 9). Fake_Adapter only; no network."""

from datetime import datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from seance.codec import required_length
from seance.points import Configuration, DataType, DeviceConfig, PointConfig
from seance.server import ToolServer
from tests.fakes import Fake_Adapter

SETTINGS = settings(max_examples=100, deadline=None)

NAME = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789 _-", min_size=1, max_size=30).filter(
    lambda s: s.strip() != ""
)


def raw_bytes(data_type: DataType) -> st.SearchStrategy[bytes]:
    if data_type is DataType.BOOL:
        return st.sampled_from([b"\x00", b"\x01"])
    size = required_length(data_type)
    return st.binary(min_size=size, max_size=size)


@st.composite
def devices_with_points(draw: st.DrawFn) -> DeviceConfig:
    names = draw(st.lists(NAME, min_size=1, max_size=8, unique=True))
    points = tuple(
        PointConfig(
            name=n,
            address=str(i),
            data_type=DataType.UINT16,
            unit=draw(st.sampled_from(["C", "rpm", "bar", "%"])),
        )
        for i, n in enumerate(names)
    )
    return DeviceConfig("dev", "A device", 2.0, points)


# Feature: skeleton-core, Property 7: For any device and list of point names, read_points
# returns results in the same order as requested.
@SETTINGS
@given(data=st.data())
def test_property_7_read_points_preserves_request_order(data: st.DataObject) -> None:
    """**Validates: Requirements 5.5**"""
    device = data.draw(devices_with_points())
    known = [p.name for p in device.points]
    # Repeats and unknown names are allowed; every request still gets one result, in order.
    requested = data.draw(
        st.lists(st.one_of(st.sampled_from(known), NAME), min_size=1, max_size=12)
    )
    server = ToolServer(Configuration((device,)), Fake_Adapter(data=b"\x00\x07"))
    try:
        result = server.call("read_points", {"device": "dev", "points": requested})
    finally:
        server.close()
    assert isinstance(result.payload, dict)
    results = result.payload["results"]
    assert isinstance(results, list)
    returned = [r["point"] for r in results if isinstance(r, dict)]
    assert returned == requested


# Feature: skeleton-core, Property 8: For any successful point read, the result contains a
# value, the configured unit, and an ISO 8601 timestamp.
@SETTINGS
@given(data=st.data())
def test_property_8_successful_reads_carry_value_unit_timestamp(data: st.DataObject) -> None:
    """**Validates: Requirements 5.4, 5.6**"""
    data_type = data.draw(st.sampled_from(list(DataType)))
    unit = data.draw(st.sampled_from(["C", "rpm", "bar", "%", ""]))
    scale = data.draw(st.one_of(st.none(), st.floats(min_value=0.001, max_value=1000)))
    raw = data.draw(raw_bytes(data_type))
    point = PointConfig("p", "1", data_type, unit, scale)
    device = DeviceConfig("dev", "A device", 2.0, (point,))
    server = ToolServer(Configuration((device,)), Fake_Adapter(data=raw))
    try:
        read = server.call("read_point", {"device": "dev", "point": "p"})
        health = server.call("device_health", {"device": "dev"})
    finally:
        server.close()
    assert read.ok
    assert isinstance(read.payload, dict)
    assert "value" in read.payload
    assert read.payload["unit"] == unit
    datetime.fromisoformat(str(read.payload["timestamp"]))
    assert health.ok
    assert isinstance(health.payload, dict)
    assert health.payload["status"] == "ok"
    datetime.fromisoformat(str(health.payload["timestamp"]))


CONFIG = Configuration(
    (
        DeviceConfig(
            "press",
            "Hydraulic press",
            0.02,
            (PointConfig("temperature", "1", DataType.INT16, "C"),),
        ),
    )
)

FAILURES = ("unknown_device", "unknown_point", "adapter_error", "timeout", "invalid_argument")


# Feature: skeleton-core, Property 9: For any failing tool call, the returned text has no
# stack trace and is a short sentence.
@SETTINGS
@given(
    kind=st.sampled_from(FAILURES),
    name=NAME.filter(lambda s: "traceback" not in s.lower() and s not in ("press", "temperature")),
    tool=st.sampled_from(["list_points", "read_point", "device_health"]),
)
def test_property_9_error_responses_are_short_plain_sentences(
    kind: str, name: str, tool: str
) -> None:
    """**Validates: Requirements 5.7, 5.8, 5.9, 5.10**"""
    if kind == "timeout":
        adapter = Fake_Adapter(data=b"\x00\x01", delay=0.1)
    elif kind == "adapter_error":
        adapter = Fake_Adapter(error=RuntimeError("secret Traceback (most recent call last)"))
    else:
        adapter = Fake_Adapter(data=b"\x00\x01")
    args: dict[str, object]
    if kind == "unknown_device":
        args = {"device": name, "point": "temperature"}
    elif kind == "unknown_point":
        args = {"device": "press", "point": name}
        tool = "read_point"
    elif kind == "invalid_argument":
        args = {"device": 12}
    else:
        args = {"device": "press", "point": "temperature"}
        tool = "read_point" if tool == "list_points" else tool
    server = ToolServer(CONFIG, adapter)
    try:
        result = server.call(tool, args)
    finally:
        server.close()
    assert not result.ok
    text = result.text
    assert isinstance(result.payload, str)
    assert text.endswith(".")
    assert len(text) <= 300
    assert "\n" not in text
    assert "Traceback" not in text
    assert 'File "' not in text
    assert "secret" not in text
