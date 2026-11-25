"""Point model: the immutable description of devices and the points they expose."""

from dataclasses import dataclass
from enum import StrEnum


class DataType(StrEnum):
    """Data types the Codec can decode and encode."""

    INT16 = "int16"
    UINT16 = "uint16"
    INT32 = "int32"
    UINT32 = "uint32"
    UINT64 = "uint64"
    FLOAT32 = "float32"
    BOOL = "bool"


@dataclass(frozen=True)
class PointConfig:
    """One readable value on a device.

    `scale`, when present, must be greater than zero. `decimals`, when present,
    is an integer from 0 to 6 and is not allowed on bool points. `labels`, when
    present, maps integer values to text, in file order. It is not allowed on bool
    or float32 points.
    """

    name: str
    address: str
    data_type: DataType
    unit: str
    scale: float | None = None
    decimals: int | None = None
    labels: tuple[tuple[int, str], ...] | None = None


@dataclass(frozen=True)
class DeviceConfig:
    """One device and the points it exposes."""

    name: str
    description: str
    timeout_seconds: float = 2.0
    points: tuple[PointConfig, ...] = ()


@dataclass(frozen=True)
class Configuration:
    """The full set of devices served by one app."""

    devices: tuple[DeviceConfig, ...] = ()
