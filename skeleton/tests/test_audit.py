"""Unit tests for the audit log (Requirements 6.4, 6.5, 7.4)."""

from __future__ import annotations

import pytest

from seance.audit import Audit_Log, AuditEntry


def _entry(i: int) -> AuditEntry:
    return AuditEntry(
        f"2024-01-01T00:00:{i:02d}Z",
        f"tool_{i}",
        f"dev_{i}",
        f"pt_{i}",
        outcome="ok",
        duration_ms=float(i),
    )


def _filled(count: int) -> Audit_Log:
    log = Audit_Log()
    for i in range(count):
        log.record(_entry(i))
    return log


def test_recent_returns_newest_first() -> None:
    log = _filled(3)
    assert [e.tool for e in log.recent(3)] == ["tool_2", "tool_1", "tool_0"]


def test_recent_truncates_to_n_most_recent() -> None:
    log = _filled(5)
    assert [e.tool for e in log.recent(2)] == ["tool_4", "tool_3"]


def test_recent_zero_and_negative_return_empty() -> None:
    log = _filled(3)
    assert log.recent(0) == []
    assert log.recent(-1) == []


def test_recent_n_larger_than_stored_returns_all() -> None:
    log = _filled(2)
    assert [e.tool for e in log.recent(100)] == ["tool_1", "tool_0"]


def test_recent_on_empty_log_is_empty() -> None:
    assert Audit_Log().recent(5) == []


def test_device_and_point_default_to_empty_strings() -> None:
    log = Audit_Log()
    log.record(AuditEntry("2024-01-01T00:00:00Z", "list_devices", outcome="ok", duration_ms=1.5))
    (stored,) = log.recent(1)
    assert stored.device == ""
    assert stored.point == ""


def test_device_supplied_point_empty() -> None:
    entry = AuditEntry("t", "list_points", "dev_a", outcome="ok")
    assert (entry.device, entry.point) == ("dev_a", "")


def test_stored_fields_are_preserved() -> None:
    log = Audit_Log()
    entry = AuditEntry(
        "2024-01-01T12:34:56Z",
        "read_point",
        "press_1",
        "temp",
        outcome="timeout",
        duration_ms=2000.25,
    )
    log.record(entry)
    (stored,) = log.recent(1)
    assert stored == entry
    assert stored.timestamp == "2024-01-01T12:34:56Z"
    assert stored.tool == "read_point"
    assert stored.device == "press_1"
    assert stored.point == "temp"
    assert stored.outcome == "timeout"
    assert stored.duration_ms == 2000.25


def test_source_defaults_to_agent_and_is_stored() -> None:
    assert AuditEntry("t", "list_devices").source == "agent"
    log = Audit_Log()
    log.record(AuditEntry("t", "list_devices", source="console"))
    (stored,) = log.recent(1)
    assert stored.source == "console"


def test_source_must_be_agent_or_console() -> None:
    with pytest.raises(ValueError, match="Unknown call source"):
        AuditEntry("t", "list_devices", source="cli")


def test_recent_returns_a_copy() -> None:
    log = _filled(2)
    log.recent(2).clear()
    assert len(log.recent(2)) == 2
