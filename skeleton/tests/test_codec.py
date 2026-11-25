"""Unit tests for the Codec: scaling and presentation rounding."""

import math

import pytest

from seance.codec import apply_scale, round_value
from seance.points import DataType

F32 = DataType.FLOAT32


def test_apply_scale_removes_float_noise() -> None:
    assert apply_scale(394, 0.1) == 39.4
    assert repr(apply_scale(394, 0.1)) == "39.4"
    assert repr(apply_scale(3, 0.25)) == "0.75"


@pytest.mark.parametrize(
    ("decimals", "expected"),
    [(0, 44.0), (1, 44.4), (6, 44.394463)],
)
def test_decimals_rounds_float(decimals: int, expected: float) -> None:
    assert round_value(44.39446258544922, F32, decimals) == expected


def test_decimals_keeps_int_as_int() -> None:
    result = round_value(394, DataType.INT16, 2)
    assert result == 394
    assert isinstance(result, int)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (44.39446258544922, 44.39446),
        (5.245955944061279, 5.245956),
        (123456789.0, 123456800.0),
        (1.2345678901e-07, 1.234568e-07),
    ],
)
def test_float32_without_decimals_uses_seven_significant_digits(
    value: float, expected: float
) -> None:
    assert round_value(value, F32, None) == expected


def test_float32_zero_stays_zero() -> None:
    assert round_value(0.0, F32, None) == 0.0


@pytest.mark.parametrize("decimals", [None, 2])
def test_non_finite_values_unchanged(decimals: int | None) -> None:
    assert math.isnan(round_value(math.nan, F32, decimals))
    assert round_value(math.inf, F32, decimals) == math.inf
    assert round_value(-math.inf, F32, decimals) == -math.inf


@pytest.mark.parametrize("decimals", [None, 3])
def test_bool_unchanged(decimals: int | None) -> None:
    assert round_value(True, DataType.BOOL, decimals) is True
    assert round_value(False, DataType.BOOL, decimals) is False


@pytest.mark.parametrize("data_type", [DataType.INT16, DataType.UINT32])
def test_non_float32_without_decimals_unchanged(data_type: DataType) -> None:
    assert round_value(39.4000001234, data_type, None) == 39.4000001234
    assert round_value(123456789, data_type, None) == 123456789
