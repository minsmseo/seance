"""Unit tests for the Modbus address parser and formatter."""

from __future__ import annotations

import pytest

from apps.modbus.address import (
    AddressError,
    ModbusAddress,
    Table,
    format_address,
    parse_address,
)

FORM_MESSAGE = "The address must have the form <unit>:<table>:<offset>."
UNIT_MESSAGE = "The unit must be a whole number from 1 to 247 with no leading zeros."
OFFSET_MESSAGE = "The offset must be a whole number from 0 to 65535 with no leading zeros."
TABLE_MESSAGE = "The table must be one of: coil, discrete, input, holding."


@pytest.mark.parametrize(
    ("text", "unit", "table", "offset"),
    [
        ("1:coil:0", 1, Table.COIL, 0),
        ("2:discrete:7", 2, Table.DISCRETE, 7),
        ("3:input:100", 3, Table.INPUT, 100),
        ("4:holding:200", 4, Table.HOLDING, 200),
        ("247:holding:65535", 247, Table.HOLDING, 65535),
        ("1:input:65535", 1, Table.INPUT, 65535),
        ("247:coil:0", 247, Table.COIL, 0),
    ],
)
def test_valid_addresses_parse(text: str, unit: int, table: Table, offset: int) -> None:
    assert parse_address(text) == ModbusAddress(unit=unit, table=table, offset=offset)


def test_format_address() -> None:
    address = ModbusAddress(unit=12, table=Table.DISCRETE, offset=0)
    assert format_address(address) == "12:discrete:0"


@pytest.mark.parametrize("text", ["", "1:coil", "1:coil:0:0", "holding", "1::2:3:"])
def test_wrong_part_count_shows_form(text: str) -> None:
    with pytest.raises(AddressError) as info:
        parse_address(text)
    assert str(info.value) == FORM_MESSAGE


@pytest.mark.parametrize("text", ["0:coil:0", "248:coil:0", "1000:holding:5"])
def test_unit_out_of_range(text: str) -> None:
    with pytest.raises(AddressError) as info:
        parse_address(text)
    assert str(info.value) == UNIT_MESSAGE


@pytest.mark.parametrize("text", ["1:coil:65536", "1:holding:70000"])
def test_offset_out_of_range(text: str) -> None:
    with pytest.raises(AddressError) as info:
        parse_address(text)
    assert str(info.value) == OFFSET_MESSAGE


@pytest.mark.parametrize("text", ["1:relay:0", "1:Coil:0", "1::0", "1:holding :0"])
def test_unknown_table_lists_four_tables(text: str) -> None:
    with pytest.raises(AddressError) as info:
        parse_address(text)
    assert str(info.value) == TABLE_MESSAGE


@pytest.mark.parametrize("text", ["01:coil:0", "001:coil:5", "00:coil:0"])
def test_unit_leading_zeros_rejected(text: str) -> None:
    with pytest.raises(AddressError) as info:
        parse_address(text)
    assert str(info.value) == UNIT_MESSAGE


@pytest.mark.parametrize("text", ["1:coil:00", "1:coil:01", "1:holding:0100"])
def test_offset_leading_zeros_rejected(text: str) -> None:
    with pytest.raises(AddressError) as info:
        parse_address(text)
    assert str(info.value) == OFFSET_MESSAGE


@pytest.mark.parametrize("text", ["a:coil:0", "-1:coil:0", "+1:coil:0", "1.5:coil:0", ":coil:0"])
def test_non_numeric_unit_rejected(text: str) -> None:
    with pytest.raises(AddressError) as info:
        parse_address(text)
    assert str(info.value) == UNIT_MESSAGE


@pytest.mark.parametrize("text", ["1:coil:x", "1:coil:-1", "1:coil:1e3", "1:coil:", "1:coil: 1"])
def test_non_numeric_offset_rejected(text: str) -> None:
    with pytest.raises(AddressError) as info:
        parse_address(text)
    assert str(info.value) == OFFSET_MESSAGE
