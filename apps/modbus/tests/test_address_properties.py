"""Property-based tests for the Modbus address parser and formatter."""

from hypothesis import given, settings
from hypothesis import strategies as st

from apps.modbus.address import (
    OFFSET_MAX,
    OFFSET_MIN,
    UNIT_MAX,
    UNIT_MIN,
    AddressError,
    ModbusAddress,
    Table,
    format_address,
    parse_address,
)


def _valid_addresses() -> st.SearchStrategy[ModbusAddress]:
    """Every valid address: unit 1..247, any table, offset 0..65535."""
    return st.builds(
        ModbusAddress,
        unit=st.integers(min_value=UNIT_MIN, max_value=UNIT_MAX),
        table=st.sampled_from(list(Table)),
        offset=st.integers(min_value=OFFSET_MIN, max_value=OFFSET_MAX),
    )


# Feature: app-modbus, Property 1
# **Validates: Requirements 3.3**
@settings(max_examples=200)
@given(address=_valid_addresses())
def test_address_round_trip(address: ModbusAddress) -> None:
    text = format_address(address)
    parsed = parse_address(text)
    assert parsed == address
    assert format_address(parsed) == text


_FORM = "<unit>:<table>:<offset>"
_TABLE_NAMES = [t.value for t in Table]

_good_unit = st.integers(min_value=UNIT_MIN, max_value=UNIT_MAX).map(str)
_good_offset = st.integers(min_value=OFFSET_MIN, max_value=OFFSET_MAX).map(str)
_good_table = st.sampled_from(_TABLE_NAMES)
_no_colon = st.text(alphabet=st.characters(codec="ascii", exclude_characters=":"), max_size=8)


def _bad_part_count() -> st.SearchStrategy[tuple[str, str]]:
    """Text with 1, 2, 4 or 5 colon-separated parts."""
    return (
        st.integers(min_value=1, max_value=5)
        .filter(lambda n: n != 3)
        .flatmap(
            lambda n: st.lists(_no_colon, min_size=n, max_size=n).map(
                lambda parts: (":".join(parts), "form")
            )
        )
    )


def _bad_unit() -> st.SearchStrategy[tuple[str, str]]:
    bad = st.one_of(
        st.just(UNIT_MIN - 1),
        st.integers(min_value=UNIT_MAX + 1, max_value=10**6),
    ).map(str)
    return st.builds(lambda u, t, o: (f"{u}:{t}:{o}", "unit"), bad, _good_table, _good_offset)


def _bad_offset() -> st.SearchStrategy[tuple[str, str]]:
    bad = st.integers(min_value=OFFSET_MAX + 1, max_value=10**7).map(str)
    return st.builds(lambda u, t, o: (f"{u}:{t}:{o}", "offset"), _good_unit, _good_table, bad)


def _bad_table() -> st.SearchStrategy[tuple[str, str]]:
    bad = _no_colon.filter(lambda s: s not in _TABLE_NAMES)
    return st.builds(lambda u, t, o: (f"{u}:{t}:{o}", "table"), _good_unit, bad, _good_offset)


# Feature: app-modbus, Property 4
# **Validates: Requirements 3.4, 3.5, 3.6, 3.7**
@settings(max_examples=200)
@given(case=st.one_of(_bad_part_count(), _bad_unit(), _bad_offset(), _bad_table()))
def test_invalid_address_text_names_the_field(case: tuple[str, str]) -> None:
    text, field = case
    try:
        parse_address(text)
    except AddressError as error:
        message = str(error)
    else:
        raise AssertionError(f"parse_address accepted {text!r}")
    assert message.endswith(".")
    assert len(message) < 120
    if field == "form":
        assert _FORM in message
    elif field == "unit":
        assert "unit" in message
        assert f"{UNIT_MIN} to {UNIT_MAX}" in message
    elif field == "offset":
        assert "offset" in message
        assert f"{OFFSET_MIN} to {OFFSET_MAX}" in message
    else:
        assert "table" in message
        assert all(name in message for name in _TABLE_NAMES)
