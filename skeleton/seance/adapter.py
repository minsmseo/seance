"""ProtocolAdapter interface. This is the only thing a protocol author implements.

The interface has no write method on purpose.
"""

from enum import StrEnum
from typing import Protocol

from seance.points import DeviceConfig, PointConfig


class HealthStatus(StrEnum):
    """Device health as reported by an adapter."""

    OK = "ok"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"


class ProtocolAdapter(Protocol):
    """Fetches raw bytes from a device. The Codec interprets them."""

    def connect(self) -> None: ...

    def close(self) -> None: ...

    def read(self, device: DeviceConfig, point: PointConfig) -> bytes: ...

    def health(self, device: DeviceConfig) -> HealthStatus: ...


REQUIRED_METHODS: tuple[str, ...] = ("connect", "close", "read", "health")


class AdapterRegistrationError(Exception):
    """Raised when an adapter lacks a required method."""

    def __init__(self, adapter_class_name: str, missing_method: str) -> None:
        self.adapter_class_name = adapter_class_name
        self.missing_method = missing_method
        super().__init__(
            f"Adapter {adapter_class_name} is missing required method '{missing_method}'. "
            f"Add it to the class and start again."
        )


class AdapterReadError(Exception):
    """Raised by an adapter to give the agent its own short failure sentence.

    The Tool_Server returns the message with outcome adapter_error, clipped to one
    line and a maximum length. Any other exception gets a generic sentence.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def check_adapter(adapter: object) -> None:
    """Raise AdapterRegistrationError naming the class and the first missing method."""
    for method in REQUIRED_METHODS:
        if not callable(getattr(adapter, method, None)):
            raise AdapterRegistrationError(type(adapter).__name__, method)
