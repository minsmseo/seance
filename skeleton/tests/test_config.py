"""Unit tests for the Config_Loader."""

from pathlib import Path

import pytest

from seance.config import ConfigError, load_config

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
