"""SNMP address parsing and formatting.

An address is written as ``<community>:<oid>``. This module has no I/O and
does not import any protocol library.
"""

import re
from dataclasses import dataclass

OID_ARC_MAX = 4294967295

_FORM = "<community>:<oid>"
_COMMUNITY_PATTERN = re.compile(r"[a-z][a-z0-9_]*")
_OID_SHAPE_MESSAGE = (
    "The oid must be at least two numbers separated by dots, with no leading zeros, "
    "for example 1.3.6.1.2.1.1.3.0."
)


@dataclass(frozen=True)
class SnmpAddress:
    """A parsed SNMP address."""

    community: str
    oid: tuple[int, ...]


class AddressError(ValueError):
    """Raised with a short sentence naming the bad field and the allowed values."""


def parse_address(text: str) -> SnmpAddress:
    """Parse ``<community>:<oid>`` or raise AddressError."""
    parts = text.split(":")
    if len(parts) != 2:
        raise AddressError(f"The address must have the form {_FORM}.")
    community, oid_text = parts

    if _COMMUNITY_PATTERN.fullmatch(community) is None or not community.isascii():
        raise AddressError(
            "The community must start with a lowercase letter and contain only "
            "lowercase letters, digits and underscores."
        )

    arc_texts = oid_text.split(".")
    if len(arc_texts) < 2:
        raise AddressError(_OID_SHAPE_MESSAGE)
    for arc_text in arc_texts:
        if not (arc_text.isascii() and arc_text.isdigit()):
            raise AddressError(_OID_SHAPE_MESSAGE)
        if len(arc_text) > 1 and arc_text.startswith("0"):
            raise AddressError(_OID_SHAPE_MESSAGE)
    oid = tuple(int(arc_text) for arc_text in arc_texts)

    if any(arc > OID_ARC_MAX for arc in oid):
        raise AddressError(f"Each arc of the oid must be at most {OID_ARC_MAX}.")

    if oid[0] > 2 or (oid[0] < 2 and oid[1] > 39):
        raise AddressError(
            "The first arc of the oid must be 0, 1 or 2, and the second arc must be "
            "from 0 to 39 when the first arc is 0 or 1."
        )
    return SnmpAddress(community=community, oid=oid)


def format_oid(oid: tuple[int, ...]) -> str:
    """Format an OID as dotted decimal."""
    return ".".join(str(arc) for arc in oid)


def format_address(address: SnmpAddress) -> str:
    """Format an address as ``<community>:<oid>``."""
    return f"{address.community}:{format_oid(address.oid)}"
