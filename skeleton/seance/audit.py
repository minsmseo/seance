"""Audit log: one entry per tool call, newest first on read."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AuditEntry:
    """One recorded tool call.

    device and point are empty strings when the call did not name one.
    outcome and duration_ms are keyword-only so device and point can default.
    """

    timestamp: str  # ISO 8601
    tool: str
    device: str = ""
    point: str = ""
    outcome: str = field(default="", kw_only=True)
    duration_ms: float = field(default=0.0, kw_only=True)


class Audit_Log:  # noqa: N801 - name fixed by the spec glossary
    """In-memory, thread-safe audit store."""

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []
        self._lock = threading.Lock()

    def record(self, entry: AuditEntry) -> None:
        """Append one entry."""
        with self._lock:
            self._entries.append(entry)

    def recent(self, n: int) -> list[AuditEntry]:
        """Return up to n most recent entries, newest first."""
        if n <= 0:
            return []
        with self._lock:
            return list(reversed(self._entries[-n:]))
