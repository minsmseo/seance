"""Property tests for the Config_Loader."""

from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from seance.config import dump_config, load_config
from seance.points import Configuration, DataType, DeviceConfig, PointConfig

_text = st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126), max_size=20)
_nonempty = _text.filter(bool)
_title = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=126), min_size=1, max_size=40
)
_positive = st.floats(min_value=1e-6, max_value=1e6, allow_nan=False, allow_infinity=False)

_NO_LABEL_TYPES = (DataType.BOOL, DataType.FLOAT32)
_label_maps = st.dictionaries(
    st.integers(min_value=-(2**15), max_value=2**16 - 1),
    _nonempty,
    min_size=1,
    max_size=5,
).map(lambda mapping: tuple(mapping.items()))


@st.composite
def _points(draw: st.DrawFn) -> PointConfig:
    data_type = draw(st.sampled_from(DataType))
    labels = None
    healthy = None
    if data_type not in _NO_LABEL_TYPES:
        labels = draw(st.none() | _label_maps)
        if labels is not None:
            healthy = draw(st.none() | st.sampled_from([text for _, text in labels]))
    return PointConfig(
        name=draw(_nonempty),
        address=draw(_nonempty),
        data_type=data_type,
        unit=draw(_nonempty),
        scale=draw(st.none() | _positive),
        labels=labels,
        healthy=healthy,
    )


@st.composite
def _devices(draw: st.DrawFn) -> DeviceConfig:
    points = draw(st.lists(_points(), max_size=5, unique_by=lambda p: p.name))
    return DeviceConfig(
        name=draw(_nonempty),
        description=draw(_text),
        timeout_seconds=draw(_positive),
        points=tuple(points),
    )


_configurations = st.builds(
    Configuration,
    devices=st.lists(_devices(), max_size=4).map(tuple),
    title=st.none() | _title,
)


# Feature: skeleton-core, Property 1: For any valid Configuration, loading, dumping and
# loading again produces a Configuration equal to the first.
# **Validates: Requirements 2.9**
@settings(max_examples=100)
@given(config=_configurations)
def test_config_round_trip(config: Configuration, tmp_path_factory) -> None:  # noqa: ANN001
    directory = tmp_path_factory.mktemp("cfg")
    first_file = Path(directory) / "first.yaml"
    first_file.write_text(dump_config(config), encoding="utf-8")
    first = load_config(first_file)
    second_file = Path(directory) / "second.yaml"
    second_file.write_text(dump_config(first), encoding="utf-8")
    second = load_config(second_file)
    assert second == first
    assert first == config


# Feature: console-redesign, Property 4: For any valid Configuration whose points may carry a
# healthy text, loading, dumping and loading again produces an equal Configuration.
# **Validates: Requirements 1.7, 1.8**
@settings(max_examples=100)
@given(config=_configurations)
def test_config_round_trip_with_healthy(config: Configuration, tmp_path_factory) -> None:  # noqa: ANN001
    directory = tmp_path_factory.mktemp("cfg_healthy")
    first_file = Path(directory) / "first.yaml"
    first_file.write_text(dump_config(config), encoding="utf-8")
    first = load_config(first_file)
    second_file = Path(directory) / "second.yaml"
    second_file.write_text(dump_config(first), encoding="utf-8")
    second = load_config(second_file)
    assert second == first
    assert first == config
