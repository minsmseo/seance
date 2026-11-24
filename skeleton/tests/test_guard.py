"""Unit tests for the read-only guard."""

from __future__ import annotations

import pytest

from seance.guard import READ_TOOLS, Allowed, Read_Only_Guard, Rejected

READ_TOOL_NAMES = [
    "list_devices",
    "list_points",
    "read_point",
    "read_points",
    "device_health",
]


def test_read_tool_set_is_the_five_tools() -> None:
    assert READ_TOOLS == frozenset(READ_TOOL_NAMES)


@pytest.mark.parametrize("name", READ_TOOL_NAMES)
def test_read_tools_are_allowed(name: str) -> None:
    assert Read_Only_Guard().check(name, {"device": "press1"}) == Allowed()


@pytest.mark.parametrize("name", ["write_point", "set_register", "reset", "", "READ_POINT"])
def test_other_tool_names_are_rejected(name: str) -> None:
    result = Read_Only_Guard().check(name, {})
    assert isinstance(result, Rejected)
    assert "read-only" in result.message
    assert "No change was made" in result.message


def test_message_names_device_and_point() -> None:
    result = Read_Only_Guard().check("write_point", {"device": "press1", "point": "speed"})
    assert isinstance(result, Rejected)
    assert "press1 (speed)" in result.message


def test_message_names_device_only() -> None:
    result = Read_Only_Guard().check("write_point", {"device": "press1"})
    assert isinstance(result, Rejected)
    assert "press1" in result.message
    assert "(" not in result.message


def test_message_without_target_uses_generic_phrase() -> None:
    result = Read_Only_Guard().check("write_point", {})
    assert isinstance(result, Rejected)
    assert "any device" in result.message


def test_opt_in_permits_only_the_named_tool() -> None:
    guard = Read_Only_Guard(frozenset({"set_speed"}))
    assert guard.check("set_speed", {"device": "press1"}) == Allowed()
    assert isinstance(guard.check("set_mode", {"device": "press1"}), Rejected)
    assert isinstance(guard.check("set_speed2", {}), Rejected)


def test_opt_in_does_not_remove_read_tools() -> None:
    guard = Read_Only_Guard(frozenset({"set_speed"}))
    assert guard.check("read_point", {}) == Allowed()


def test_arguments_cannot_bypass_the_guard() -> None:
    result = Read_Only_Guard().check("write_point", {"tool": "read_point", "write": False})
    assert isinstance(result, Rejected)
