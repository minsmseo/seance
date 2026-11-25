"""Property-based tests for SNMP address parsing and formatting."""

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from apps.snmp.address import (
    OID_ARC_MAX,
    AddressError,
    format_address,
    parse_address,
)

communities = st.from_regex(r"[a-z][a-z0-9_]{0,20}", fullmatch=True)

_arcs = st.integers(min_value=0, max_value=OID_ARC_MAX)


@st.composite
def oids(draw: st.DrawFn) -> tuple[int, ...]:
    first = draw(st.integers(min_value=0, max_value=2))
    second = draw(st.integers(min_value=0, max_value=39 if first < 2 else OID_ARC_MAX))
    rest = draw(st.lists(_arcs, max_size=10))
    return (first, second, *rest)


@st.composite
def address_texts(draw: st.DrawFn) -> str:
    community = draw(communities)
    oid = draw(oids())
    return f"{community}:" + ".".join(str(arc) for arc in oid)


@settings(max_examples=200)
@given(text=address_texts())
def test_address_round_trip(text: str) -> None:
    """Feature: app-snmp, Property 3: Address round trip.

    **Validates: Requirements 3.1, 3.2, 3.3**
    """
    parsed = parse_address(text)
    formatted = format_address(parsed)
    assert formatted == text
    assert parse_address(formatted) == parsed


# ---------------------------------------------------------------------------
# Property 6: a malformed address is rejected with a sentence naming the bad field
# ---------------------------------------------------------------------------

_FORM = "<community>:<oid>"


def _dotted(arcs: list[int] | tuple[int, ...]) -> str:
    return ".".join(str(arc) for arc in arcs)


@st.composite
def wrong_part_count_texts(draw: st.DrawFn) -> str:
    piece = st.text(alphabet="abcxyz019._-", max_size=12)
    count = draw(st.integers(min_value=1, max_value=4))
    if count == 1:
        return draw(piece)
    return ":".join(draw(st.lists(piece, min_size=count, max_size=count)))


@st.composite
def bad_community_texts(draw: st.DrawFn) -> str:
    kind = draw(st.sampled_from(["empty", "upper", "digit", "underscore", "badchar"]))
    tail = draw(st.from_regex(r"[a-z0-9_]{0,8}", fullmatch=True))
    if kind == "empty":
        community = ""
    elif kind == "upper":
        letter = draw(st.sampled_from("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
        community = draw(st.sampled_from(["", "a"])) + letter + tail
    elif kind == "digit":
        community = draw(st.sampled_from("0123456789")) + tail
    elif kind == "underscore":
        community = "_" + tail
    else:
        bad = draw(st.sampled_from(list("-. !@#$%^&*()+=/\\,;")))
        community = "a" + tail + bad + tail
    return f"{community}:{_dotted(draw(oids()))}"


@st.composite
def bad_oid_shape_texts(draw: st.DrawFn) -> str:
    kind = draw(st.sampled_from(["one_arc", "empty_arc", "non_digit", "leading_zero", "name"]))
    community = draw(communities)
    base = [str(arc) for arc in draw(oids())]
    if kind == "one_arc":
        oid_text = str(draw(_arcs))
    elif kind == "empty_arc":
        index = draw(st.integers(min_value=0, max_value=len(base)))
        oid_text = ".".join([*base[:index], "", *base[index:]])
    elif kind == "non_digit":
        index = draw(st.integers(min_value=0, max_value=len(base) - 1))
        base[index] = draw(st.sampled_from(["x", "-1", "1a", "+1", " 1", "1 ", "0x1"]))
        oid_text = ".".join(base)
    elif kind == "leading_zero":
        index = draw(st.integers(min_value=0, max_value=len(base) - 1))
        base[index] = "0" + base[index]
        oid_text = ".".join(base)
    else:
        oid_text = draw(st.sampled_from(["sysUpTime", "sysUpTime.0", "iso.org", "1.3.sysDescr"]))
    return f"{community}:{oid_text}"


@st.composite
def arc_overflow_texts(draw: st.DrawFn) -> str:
    community = draw(communities)
    arcs = list(draw(oids()))
    index = draw(st.integers(min_value=0, max_value=len(arcs) - 1))
    arcs[index] = draw(st.integers(min_value=OID_ARC_MAX + 1, max_value=OID_ARC_MAX * 4))
    return f"{community}:{_dotted(arcs)}"


@st.composite
def bad_root_arc_texts(draw: st.DrawFn) -> str:
    community = draw(communities)
    rest = draw(st.lists(_arcs, max_size=6))
    if draw(st.booleans()):
        first = draw(st.integers(min_value=3, max_value=OID_ARC_MAX))
        second = draw(_arcs)
    else:
        first = draw(st.integers(min_value=0, max_value=1))
        second = draw(st.integers(min_value=40, max_value=OID_ARC_MAX))
    return f"{community}:{_dotted([first, second, *rest])}"


def _assert_rejected(text: str, expected: str) -> None:
    with pytest.raises(AddressError) as info:
        parse_address(text)
    assert expected in str(info.value)


@settings(max_examples=100)
@given(text=wrong_part_count_texts())
def test_wrong_part_count_names_form(text: str) -> None:
    """Feature: app-snmp, Property 6: Malformed address rejected.

    **Validates: Requirements 3.4, 3.5, 3.6, 3.7, 3.8, 3.9**
    """
    assume(text.count(":") != 1)
    _assert_rejected(text, _FORM)


@settings(max_examples=100)
@given(text=bad_community_texts())
def test_bad_community_names_community(text: str) -> None:
    """Feature: app-snmp, Property 6: Malformed address rejected.

    **Validates: Requirements 3.4, 3.5, 3.6, 3.7, 3.8, 3.9**
    """
    _assert_rejected(text, "community")


@settings(max_examples=100)
@given(text=bad_oid_shape_texts())
def test_bad_oid_shape_names_oid(text: str) -> None:
    """Feature: app-snmp, Property 6: Malformed address rejected.

    **Validates: Requirements 3.4, 3.5, 3.6, 3.7, 3.8, 3.9**
    """
    _assert_rejected(text, "oid")


@settings(max_examples=100)
@given(text=arc_overflow_texts())
def test_arc_over_maximum_names_oid(text: str) -> None:
    """Feature: app-snmp, Property 6: Malformed address rejected.

    **Validates: Requirements 3.4, 3.5, 3.6, 3.7, 3.8, 3.9**
    """
    _assert_rejected(text, "oid")


@settings(max_examples=100)
@given(text=bad_root_arc_texts())
def test_bad_root_arcs_name_oid(text: str) -> None:
    """Feature: app-snmp, Property 6: Malformed address rejected.

    **Validates: Requirements 3.4, 3.5, 3.6, 3.7, 3.8, 3.9**
    """
    _assert_rejected(text, "oid")
