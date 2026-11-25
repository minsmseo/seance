"""Property tests for value labels (app-snmp Property 5). Fake_Adapter only; no network."""

from dataclasses import replace

from hypothesis import given, settings
from hypothesis import strategies as st

from seance.codec import encode
from seance.points import Configuration, DataType, DeviceConfig, PointConfig
from seance.server import ToolServer
from tests.fakes import Fake_Adapter

SETTINGS = settings(max_examples=100, deadline=None)

INT_RANGES = {
    DataType.INT16: (-(2**15), 2**15 - 1),
    DataType.UINT16: (0, 2**16 - 1),
    DataType.INT32: (-(2**31), 2**31 - 1),
    DataType.UINT32: (0, 2**32 - 1),
    DataType.UINT64: (0, 2**64 - 1),
}

LABEL_TEXT = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-",
    min_size=1,
    max_size=20,
)


def _read(point: PointConfig, value: int) -> dict[str, object]:
    device = DeviceConfig("dev", "A device", 2.0, (point,))
    raw = encode(point.data_type, value)
    server = ToolServer(Configuration((device,)), Fake_Adapter(data=raw))
    try:
        result = server.call("read_point", {"device": "dev", "point": point.name})
    finally:
        server.close()
    assert result.ok
    assert isinstance(result.payload, dict)
    return dict(result.payload)


# Feature: app-snmp, Property 5: Labels map known integers and leave unknown ones alone.
@SETTINGS
@given(data=st.data())
def test_property_5_labels_map_known_integers_and_leave_unknown_alone(
    data: st.DataObject,
) -> None:
    """**Validates: Requirements 5.1, 5.2**"""
    data_type = data.draw(st.sampled_from(list(INT_RANGES)))
    low, high = INT_RANGES[data_type]
    mapping = data.draw(st.dictionaries(st.integers(low, high), LABEL_TEXT, min_size=1, max_size=6))
    scale = data.draw(st.one_of(st.none(), st.sampled_from([0.01, 0.5, 2.0, 10.0])))
    known = data.draw(st.booleans())
    if known:
        value = data.draw(st.sampled_from(sorted(mapping)))
    else:
        value = data.draw(st.integers(low, high).filter(lambda n: n not in mapping))

    plain = PointConfig("p", "1", data_type, "state", scale)
    labeled = replace(plain, labels=tuple(mapping.items()))
    result = _read(labeled, value)
    baseline = _read(plain, value)

    assert result["unit"] == "state"
    if known:
        assert result["value"] == mapping[value]
        assert result["raw"] == value
    else:
        assert "raw" not in result
        assert result["value"] == baseline["value"]
