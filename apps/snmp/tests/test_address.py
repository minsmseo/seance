"""Unit tests for apps/snmp/address.py."""

import pytest

from apps.snmp.address import (
    OID_ARC_MAX,
    AddressError,
    SnmpAddress,
    format_address,
    format_oid,
    parse_address,
)

OID_SHAPE = (
    "The oid must be at least two numbers separated by dots, with no leading zeros, "
    "for example 1.3.6.1.2.1.1.3.0."
)


def _message(text: str) -> str:
    with pytest.raises(AddressError) as info:
        parse_address(text)
    return str(info.value)


def test_valid_address() -> None:
    assert parse_address("public:1.3.6.1.2.1.1.3.0") == SnmpAddress(
        community="public", oid=(1, 3, 6, 1, 2, 1, 1, 3, 0)
    )


def test_valid_arc_at_zero_and_max() -> None:
    assert parse_address("c_1:0.0").oid == (0, 0)
    assert parse_address(f"c:2.{OID_ARC_MAX}").oid == (2, OID_ARC_MAX)
    assert OID_ARC_MAX == 4294967295


def test_wrong_part_count_shows_form() -> None:
    for text in ("public", "a:b:c", ""):
        message = _message(text)
        assert "<community>:<oid>" in message
        assert message == "The address must have the form <community>:<oid>."


@pytest.mark.parametrize("text", [":1.3", "Public:1.3", "1abc:1.3", "pu-b:1.3", "pub lic:1.3"])
def test_bad_community_message(text: str) -> None:
    message = _message(text)
    assert "community" in message
    assert message == (
        "The community must start with a lowercase letter and contain only "
        "lowercase letters, digits and underscores."
    )


@pytest.mark.parametrize(
    "text", ["public:", "public:1", "public:1..3", "public:1.x", "public:1.3."]
)
def test_bad_oid_message(text: str) -> None:
    message = _message(text)
    assert message == OID_SHAPE
    assert "oid" in message
    assert "1.3.6.1.2.1.1.3.0" in message


def test_arc_over_max() -> None:
    message = _message(f"public:1.3.{OID_ARC_MAX + 1}")
    assert message == "Each arc of the oid must be at most 4294967295."


def test_first_arc_three() -> None:
    message = _message("public:3.1")
    assert "0, 1 or 2" in message
    assert "0 to 39" in message


def test_second_arc_forty_under_first_arc_one() -> None:
    message = _message("public:1.40")
    assert "0, 1 or 2" in message
    assert "0 to 39" in message
    assert parse_address("public:1.39").oid == (1, 39)
    assert parse_address("public:2.40").oid == (2, 40)


def test_name_used_as_oid() -> None:
    assert _message("public:sysUpTime") == OID_SHAPE
    assert _message("public:sysUpTime.0") == OID_SHAPE


@pytest.mark.parametrize("text", ["public:1.03", "public:01.3", "public:1.3.00"])
def test_leading_zeros_rejected(text: str) -> None:
    assert _message(text) == OID_SHAPE


def test_format_oid() -> None:
    assert format_oid((1, 3, 6, 1)) == "1.3.6.1"
    assert format_oid((0, 0)) == "0.0"


def test_format_address_round_trip() -> None:
    address = SnmpAddress(community="public", oid=(1, 3, 6, 1, 2, 1, 1, 3, 0))
    assert format_address(address) == "public:1.3.6.1.2.1.1.3.0"
    assert parse_address(format_address(address)) == address
