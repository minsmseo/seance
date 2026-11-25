"""Modbus address parsing and formatting.

An address is written as ``<unit>:<table>:<offset>``. This module has no I/O
and does not import any protocol library.
"""

from dataclasses import dataclass
from enum import StrEnum

UNIT_MIN = 1
UNIT_MAX = 247
OFFSET_MIN = 0
OFFSET_MAX = 65535

_FORM = "<unit>:<table>:<offset>"


class Table(StrEnum):
    """The four Modbus data tables."""

    COIL = "coil"
    DISCRETE = "discrete"
    INPUT = "input"
    HOLDING = "holding"


@dataclass(frozen=True)
class ModbusAddress:
    """A parsed Modbus address."""

    unit: int  # 1..247
    table: Table
    offset: int  # 0..65535


class AddressError(ValueError):
    """Raised with a short sentence naming the bad field and the allowed values."""


def _parse_number(text: str, field: str, low: int, high: int) -> int:
    """Parse a decimal number with no leading zeros inside low..high."""
    message = f"The {field} must be a whole number from {low} to {high} with no leading zeros."
    if not (text.isascii() and text.isdigit()):
        raise AddressError(message)
    if len(text) > 1 and text.startswith("0"):
        raise AddressError(message)
    value = int(text)
    if value < low or value > high:
        raise AddressError(message)
    return value


def parse_address(text: str) -> ModbusAddress:
    """Parse ``<unit>:<table>:<offset>`` or raise AddressError."""
    parts = text.split(":")
    if len(parts) != 3:
        raise AddressError(f"The address must have the form {_FORM}.")
    unit_text, table_text, offset_text = parts
    unit = _parse_number(unit_text, "unit", UNIT_MIN, UNIT_MAX)
    try:
        table = Table(table_text)
    except ValueError:
        allowed = ", ".join(t.value for t in Table)
        raise AddressError(f"The table must be one of: {allowed}.") from None
    offset = _parse_number(offset_text, "offset", OFFSET_MIN, OFFSET_MAX)
    return ModbusAddress(unit=unit, table=table, offset=offset)


def format_address(address: ModbusAddress) -> str:
    """Format an address as ``<unit>:<table>:<offset>``."""
    return f"{address.unit}:{address.table.value}:{address.offset}"
