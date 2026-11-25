"""Unit tests for the Config_Loader."""

from pathlib import Path

import pytest

from seance.config import ConfigError, dump_config, load_config
from seance.points import DataType

VALID = """
devices:
  - name: press
    description: Hydraulic press
    points:
      - {name: temp, address: "40001", data_type: int16, unit: C, scale: 0.1}
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "devices.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_valid_file_loads_with_default_timeout(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, VALID))
    device = config.devices[0]
    assert device.timeout_seconds == 2.0
    assert device.points[0].scale == 0.1


def test_explicit_timeout_is_kept(tmp_path: Path) -> None:
    text = VALID.replace("description: Hydraulic press", "timeout_seconds: 5")
    assert load_config(write(tmp_path, text)).devices[0].timeout_seconds == 5.0


@pytest.mark.parametrize("missing", ["name", "address", "data_type", "unit"])
def test_missing_required_point_field(tmp_path: Path, missing: str) -> None:
    point = {"name": "t", "address": "1", "data_type": "int16", "unit": "C"}
    del point[missing]
    body = ", ".join(f"{k}: {v}" for k, v in point.items())
    text = f"devices:\n  - name: press\n    points:\n      - {{{body}}}\n"
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as info:
        load_config(path)
    assert missing in info.value.field
    assert info.value.device == "press"
    assert str(path) in str(info.value)
    assert missing in str(info.value)


def test_duplicate_point_name(tmp_path: Path) -> None:
    text = VALID + '      - {name: temp, address: "2", data_type: int16, unit: C}\n'
    with pytest.raises(ConfigError) as info:
        load_config(write(tmp_path, text))
    assert info.value.device == "press"
    assert "temp" in info.value.field
    assert "duplicate" in info.value.reason


def test_unsupported_data_type(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as info:
        load_config(write(tmp_path, VALID.replace("int16", "complex128")))
    assert info.value.device == "press"
    assert "temp" in info.value.field
    assert "data_type" in info.value.field
    assert "complex128" in info.value.reason
    assert "uint64" in info.value.reason


def test_uint64_data_type_loads(tmp_path: Path) -> None:
    text = VALID.replace("int16", "uint64").replace(", scale: 0.1", "")
    point = load_config(write(tmp_path, text)).devices[0].points[0]
    assert point.data_type is DataType.UINT64


@pytest.mark.parametrize("scale", ["0", "-1.5", "abc", "true"])
def test_invalid_scale(tmp_path: Path, scale: str) -> None:
    path = write(tmp_path, VALID.replace("scale: 0.1", f"scale: {scale}"))
    with pytest.raises(ConfigError) as info:
        load_config(path)
    assert info.value.field.endswith("scale")
    assert info.value.device == "press"
    assert str(path) in str(info.value)


def test_invalid_timeout(tmp_path: Path) -> None:
    text = VALID.replace("description: Hydraulic press", "timeout_seconds: 0")
    with pytest.raises(ConfigError) as info:
        load_config(write(tmp_path, text))
    assert info.value.field == "timeout_seconds"


def test_unreadable_and_malformed_files(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(tmp_path / "missing.yaml")
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, "devices: [unclosed"))


def decimals_text(value: str, data_type: str = "float32") -> str:
    return (
        "devices:\n  - name: press\n    points:\n"
        f'      - {{name: temp, address: "1", data_type: {data_type}, unit: C, '
        f"decimals: {value}}}\n"
    )


@pytest.mark.parametrize("value", [0, 1, 6])
def test_valid_decimals_loads(tmp_path: Path, value: int) -> None:
    config = load_config(write(tmp_path, decimals_text(str(value))))
    assert config.devices[0].points[0].decimals == value


def test_missing_decimals_is_none(tmp_path: Path) -> None:
    assert load_config(write(tmp_path, VALID)).devices[0].points[0].decimals is None


@pytest.mark.parametrize("value", ["-1", "7", "1.5", "1.0", '"2"', "true", "false"])
def test_invalid_decimals(tmp_path: Path, value: str) -> None:
    path = write(tmp_path, decimals_text(value))
    with pytest.raises(ConfigError) as info:
        load_config(path)
    assert info.value.field.endswith("decimals")
    assert info.value.device == "press"
    assert str(path) in str(info.value)


def test_decimals_rejected_on_bool_point(tmp_path: Path) -> None:
    path = write(tmp_path, decimals_text("1", "bool"))
    with pytest.raises(ConfigError) as info:
        load_config(path)
    assert info.value.field.endswith("decimals")
    assert info.value.device == "press"
    assert str(path) in str(info.value)


def labels_text(labels: str, data_type: str = "int16") -> str:
    return (
        "devices:\n  - name: press\n    points:\n"
        f'      - {{name: state, address: "1", data_type: {data_type}, unit: state, '
        f"labels: {labels}}}\n"
    )


@pytest.mark.parametrize(
    ("labels", "data_type"),
    [
        ("{0: off, 1: on}", "bool"),
        ("{0: off, 1: on}", "float32"),
        ("{up: on}", "int16"),
        ("{1.5: on}", "int16"),
        ("{true: on}", "int16"),
        ('{1: ""}', "int16"),
        ("{1: 5}", "int16"),
        ("{}", "int16"),
    ],
)
def test_invalid_labels_name_file_device_and_field(
    tmp_path: Path, labels: str, data_type: str
) -> None:
    path = write(tmp_path, labels_text(labels, data_type))
    with pytest.raises(ConfigError) as info:
        load_config(path)
    assert info.value.field == "points[state].labels"
    assert info.value.device == "press"
    assert str(path) in str(info.value)
    assert "points[state].labels" in str(info.value)


def test_labels_load_in_order_and_are_optional(tmp_path: Path) -> None:
    point = load_config(write(tmp_path, labels_text("{3: c, 1: a, 2: b}"))).devices[0].points[0]
    assert point.labels == ((3, "c"), (1, "a"), (2, "b"))
    assert load_config(write(tmp_path, VALID)).devices[0].points[0].labels is None


def test_labels_round_trip_through_dump_keeps_order(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, labels_text("{3: c, 1: a, 2: b}")))
    again = load_config(write(tmp_path, dump_config(config)))
    assert again == config
    labels = again.devices[0].points[0].labels
    assert labels is not None
    assert [key for key, _ in labels] == [3, 1, 2]


def test_decimals_round_trips_through_dump(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, decimals_text("3")))
    assert load_config(write(tmp_path, dump_config(config))) == config
