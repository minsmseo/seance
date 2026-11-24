"""In-memory test doubles. No network calls."""

import time
from collections import Counter

from seance.adapter import HealthStatus
from seance.points import DeviceConfig, PointConfig


class Fake_Adapter:
    """ProtocolAdapter that returns configured bytes, raises a configured error, or delays."""

    def __init__(
        self,
        data: bytes = b"\x00\x00",
        error: Exception | None = None,
        delay: float = 0.0,
        health_status: HealthStatus = HealthStatus.OK,
    ) -> None:
        self.data = data
        self.error = error
        self.delay = delay
        self.health_status = health_status
        self.calls: Counter[str] = Counter()

    @property
    def call_count(self) -> int:
        """Total calls across all methods."""
        return sum(self.calls.values())

    def _enter(self, method: str) -> None:
        self.calls[method] += 1
        if self.delay > 0:
            time.sleep(self.delay)
        if self.error is not None:
            raise self.error

    def connect(self) -> None:
        self._enter("connect")

    def close(self) -> None:
        self._enter("close")

    def read(self, device: DeviceConfig, point: PointConfig) -> bytes:
        self._enter("read")
        return self.data

    def health(self, device: DeviceConfig) -> HealthStatus:
        self._enter("health")
        return self.health_status
