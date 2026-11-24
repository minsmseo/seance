"""Read-only guard: rejects every write request unless a tool is opted in."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

READ_TOOLS: frozenset[str] = frozenset(
    {
        "list_devices",
        "list_points",
        "read_point",
        "read_points",
        "device_health",
    }
)


@dataclass(frozen=True)
class Allowed:
    """The request may proceed to the adapter."""


@dataclass(frozen=True)
class Rejected:
    """The request was refused; message is a plain sentence for the agent."""

    message: str


GuardResult = Allowed | Rejected


def _target(args: Mapping[str, object]) -> str:
    """Describe the device and point named in args, or a generic phrase."""
    device = args.get("device")
    point = args.get("point")
    if isinstance(device, str) and device:
        if isinstance(point, str) and point:
            return f"{device} ({point})"
        return device
    return "any device"


class Read_Only_Guard:  # noqa: N801 - name fixed by the spec
    """Rejects any call that is not one of the five read tools.

    A tool name outside the read set is a Write_Request. It is permitted
    only when the adapter author listed that exact name in
    ``allowed_write_tools`` at construction time.
    """

    def __init__(self, allowed_write_tools: frozenset[str] = frozenset()) -> None:
        self._allowed_write_tools = frozenset(allowed_write_tools)

    def check(self, tool_name: str, args: Mapping[str, object]) -> GuardResult:
        if tool_name in READ_TOOLS or tool_name in self._allowed_write_tools:
            return Allowed()
        return Rejected(f"This server is read-only. No change was made to {_target(args)}.")
