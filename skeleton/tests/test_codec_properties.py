"""Property-based tests for the Codec."""

import math
import struct
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from seance.codec import CodecLengthError, apply_scale, decode, encode, required_length
from seance.points import DataType

_F32_NAN_EXP = 0x7F800000


def _nan_bits() -> st.SearchStrategy[bytes]:
    """4-byte float32 NaN patterns: any sign, any non-zero mantissa."""
    return st.builds(
        lambda sign, mantissa: struct.pack(">I", (sign << 31) | _F32_NAN_EXP | mantissa),
        st.integers(min_value=0, max_value=1),
        st.integers(min_value=1, max_value=0x7FFFFF),
    )


def _raw_bytes(data_type: DataType) -> st.SearchStrategy[bytes]:
    """Byte sequences of the required length that decode accepts."""
    if data_type is DataType.BOOL:
        return st.sampled_from([b"\x00", b"\x01"])
    size = required_length(data_type)
    plain = st.binary(min_size=size, max_size=size)
    if data_type is DataType.FLOAT32:
        return st.one_of(plain, _nan_bits())
    return plain


# Feature: skeleton-core, Property 2
# **Validates: Requirements 3.3**
@settings(max_examples=200)
@given(data=st.data())
def test_decode_then_encode_returns_original_bytes(data: st.DataObject) -> None:
    data_type = data.draw(st.sampled_from(list(DataType)))
    raw = data.draw(_raw_bytes(data_type))
    assert encode(data_type, decode(data_type, raw)) == raw


# Feature: skeleton-core, Property 3
# **Validates: Requirements 3.4**
@settings(max_examples=200)
@given(data=st.data())
def test_decode_rejects_wrong_length_input(data: st.DataObject) -> None:
    data_type = data.draw(st.sampled_from(list(DataType)))
    expected = required_length(data_type)
    raw = data.draw(st.binary(min_size=0, max_size=16).filter(lambda b: len(b) != expected))
    with pytest.raises(CodecLengthError) as info:
        decode(data_type, raw)
    message = str(info.value)
    assert data_type.value in message
    assert str(expected) in message
    assert str(len(raw)) in message
    assert info.value.data_type is data_type
    assert info.value.expected_length == expected
    assert info.value.received_length == len(raw)


# Bounds: integers within +/- 2**63 and floats that are zero or have magnitude in
# [1e-3, 1e6]; scale factors in [1e-3, 1e3]. A non-zero product is then at least
# 1e-6 and at most about 1e22, so it never underflows to zero or overflows to inf.
_SCALES = st.floats(min_value=1e-3, max_value=1e3, allow_nan=False, allow_infinity=False)
_SCALABLE_FLOATS = st.one_of(
    st.just(0.0),
    st.just(-0.0),
    st.floats(min_value=1e-3, max_value=1e6),
    st.floats(min_value=-1e6, max_value=-1e-3),
)
_SCALABLE_VALUES = st.one_of(st.integers(min_value=-(2**63), max_value=2**63), _SCALABLE_FLOATS)


# Feature: skeleton-core, Property 4
# **Validates: Requirements 3.5, 3.6**
@settings(max_examples=200)
@given(value=_SCALABLE_VALUES, scale=_SCALES)
def test_apply_scale_preserves_sign_and_multiplies(value: int | float, scale: float) -> None:
    scaled = apply_scale(value, scale)
    if isinstance(value, int):
        # Integer raw values are rounded to the scale's decimal places.
        assert math.isclose(scaled, value * scale, rel_tol=1e-9, abs_tol=1e-9)
    else:
        assert scaled == value * scale
    assert math.copysign(1.0, scaled) == math.copysign(1.0, value)
    assert (scaled > 0) == (value > 0)
    assert (scaled < 0) == (value < 0)


# Feature: skeleton-core, Property 4
# **Validates: Requirements 3.5**
@settings(max_examples=100)
@given(value=st.booleans(), scale=_SCALES)
def test_apply_scale_never_scales_bool(value: bool, scale: float) -> None:
    assert apply_scale(value, scale) is value


# Feature: skeleton-core, Property 12: Scaling with a 10^-n scale has at most n decimal places
# **Validates: Requirements 3.5**
@settings(max_examples=200, deadline=None)
@given(
    raw=st.integers(min_value=-(2**31), max_value=2**32 - 1),
    n=st.integers(min_value=0, max_value=6),
)
def test_apply_scale_power_of_ten_has_at_most_n_places(raw: int, n: int) -> None:
    scale = 10**-n
    result = apply_scale(raw, scale)
    exponent = Decimal(repr(result)).as_tuple().exponent
    assert isinstance(exponent, int)
    assert exponent >= -n
    assert math.isclose(result, raw * scale, rel_tol=1e-9, abs_tol=1e-12)


def test_apply_scale_removes_float_noise() -> None:
    assert apply_scale(394, 0.1) == 39.4
    assert repr(apply_scale(394, 0.1)) == "39.4"
    assert repr(apply_scale(3, 0.25)) == "0.75"
