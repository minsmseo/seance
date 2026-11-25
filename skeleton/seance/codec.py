"""Codec: decode raw bytes into typed values, encode them back, and apply scaling.

Byte order is fixed to big-endian for every multi-byte type.

Round-trip contract (decode then encode returns the original bytes):

- Integer types round-trip every byte sequence of the right length.
- FLOAT32 round-trips every 4-byte sequence, including NaN payloads. Python
  converts float32 to float64 through hardware, which can quiet a signaling
  NaN and change its bytes, so NaN values are converted by bit manipulation
  instead of `struct` float conversion.
- BOOL accepts only the single byte values 0x00 (False) and 0x01 (True).
  Any other byte is rejected with `CodecValueError`, because a bool cannot
  carry the difference between, say, 0x02 and 0x03. The round-trip property
  therefore covers BOOL over {0x00, 0x01} only.
"""

import math
import struct
from decimal import Decimal

from seance.points import DataType

RawValue = int | float | bool

_LENGTHS: dict[DataType, int] = {
    DataType.INT16: 2,
    DataType.UINT16: 2,
    DataType.INT32: 4,
    DataType.UINT32: 4,
    DataType.FLOAT32: 4,
    DataType.BOOL: 1,
}

_INT_FORMATS: dict[DataType, str] = {
    DataType.INT16: ">h",
    DataType.UINT16: ">H",
    DataType.INT32: ">i",
    DataType.UINT32: ">I",
}

_INT_RANGES: dict[DataType, tuple[int, int]] = {
    DataType.INT16: (-(2**15), 2**15 - 1),
    DataType.UINT16: (0, 2**16 - 1),
    DataType.INT32: (-(2**31), 2**31 - 1),
    DataType.UINT32: (0, 2**32 - 1),
}

_F32_EXP_MASK = 0x7F800000
_F32_MANT_MASK = 0x007FFFFF


class CodecLengthError(ValueError):
    """Raised when a byte sequence does not have the length its data type needs."""

    def __init__(self, data_type: DataType, expected_length: int, received_length: int) -> None:
        self.data_type = data_type
        self.expected_length = expected_length
        self.received_length = received_length
        super().__init__(
            f"Data type {data_type.value} needs {expected_length} bytes "
            f"but received {received_length} bytes."
        )


class CodecValueError(ValueError):
    """Raised when a byte sequence or value is invalid for its data type."""


def required_length(data_type: DataType) -> int:
    """Return the number of bytes a value of `data_type` occupies."""
    return _LENGTHS[data_type]


def decode(data_type: DataType, raw: bytes) -> RawValue:
    """Decode big-endian `raw` into a typed value.

    Raises `CodecLengthError` on a wrong length and `CodecValueError` for a
    BOOL byte other than 0x00 or 0x01.
    """
    expected = _LENGTHS[data_type]
    if len(raw) != expected:
        raise CodecLengthError(data_type, expected, len(raw))
    if data_type is DataType.BOOL:
        if raw[0] > 1:
            raise CodecValueError(f"Data type bool accepts byte 0 or 1 but received {raw[0]}.")
        return raw[0] == 1
    if data_type is DataType.FLOAT32:
        return _decode_float32(raw)
    result: int = struct.unpack(_INT_FORMATS[data_type], raw)[0]
    return result


def encode(data_type: DataType, value: RawValue) -> bytes:
    """Encode `value` into big-endian bytes for `data_type`.

    Raises `CodecValueError` if the value does not fit the data type.
    """
    if data_type is DataType.BOOL:
        if not isinstance(value, bool):
            raise CodecValueError("Data type bool needs a True or False value.")
        return b"\x01" if value else b"\x00"
    if data_type is DataType.FLOAT32:
        return _encode_float32(float(value))
    if isinstance(value, float):
        if not value.is_integer():
            raise CodecValueError(f"Data type {data_type.value} needs a whole number.")
        value = int(value)
    low, high = _INT_RANGES[data_type]
    if not low <= value <= high:
        raise CodecValueError(f"Value {value} is outside {data_type.value} range {low} to {high}.")
    return struct.pack(_INT_FORMATS[data_type], value)


def apply_scale(value: RawValue, scale: float | None) -> RawValue:
    """Multiply `value` by `scale`. Return `value` unchanged when `scale` is None.

    BOOL values are never scaled. `scale` must be greater than zero.

    An integer raw value is rounded to the decimal places of the scale's shortest
    decimal form (0.1 -> 1, 0.25 -> 2, 10 -> 0), which removes floating point
    noise such as 39.400000000000006. A scaled non-zero integer is a non-zero
    multiple of 10**-places, so rounding never turns it into zero or flips its
    sign. A float raw value (FLOAT32) is returned as `value * scale` unrounded,
    because the scale's places do not bound the precision of a float.
    """
    if scale is None or isinstance(value, bool):
        return value
    if not scale > 0:
        raise CodecValueError(f"Scale factor must be greater than zero but was {scale}.")
    result = value * scale
    if isinstance(value, int) and isinstance(result, float) and math.isfinite(result):
        return round(result, _decimal_places(scale))
    return result


def round_value(value: RawValue, data_type: DataType, decimals: int | None) -> RawValue:
    """Round a decoded, scaled value for presentation.

    BOOL values are returned unchanged. When `decimals` is set the value is
    rounded to that many places (an int stays an int). When `decimals` is None,
    FLOAT32 values are rounded to 7 significant digits, which hides the false
    precision of widening float32 to float64. NaN and infinities pass through.
    Any other value is returned unchanged.
    """
    if isinstance(value, bool):
        return value
    if decimals is not None:
        if isinstance(value, int):
            return value
        if not math.isfinite(value):
            return value
        return round(value, decimals)
    if data_type is DataType.FLOAT32 and isinstance(value, float) and math.isfinite(value):
        return float(f"{value:.7g}")
    return value


def _decimal_places(scale: float) -> int:
    """Return the decimal places in the shortest decimal form of `scale`."""
    if not math.isfinite(scale):
        return 0
    exponent = Decimal(repr(scale)).normalize().as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


def _decode_float32(raw: bytes) -> float:
    bits: int = struct.unpack(">I", raw)[0]
    if (bits & _F32_EXP_MASK) == _F32_EXP_MASK and (bits & _F32_MANT_MASK):
        # NaN: widen to float64 by hand so the payload and quiet bit survive.
        sign = bits >> 31
        mantissa = bits & _F32_MANT_MASK
        wide = (sign << 63) | (0x7FF << 52) | (mantissa << 29)
        nan: float = struct.unpack(">d", struct.pack(">Q", wide))[0]
        return nan
    result: float = struct.unpack(">f", raw)[0]
    return result


def _encode_float32(value: float) -> bytes:
    if math.isnan(value):
        wide: int = struct.unpack(">Q", struct.pack(">d", value))[0]
        sign = wide >> 63
        mantissa = (wide >> 29) & _F32_MANT_MASK
        return struct.pack(">I", (sign << 31) | _F32_EXP_MASK | mantissa)
    try:
        return struct.pack(">f", value)
    except OverflowError:
        raise CodecValueError(f"Value {value} is too large for float32.") from None
