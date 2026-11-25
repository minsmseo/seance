"""Config_Loader: load, validate and dump the YAML configuration."""

import math
from collections.abc import Mapping
from pathlib import Path

import yaml

from seance.points import Configuration, DataType, DeviceConfig, PointConfig

DEFAULT_TIMEOUT_SECONDS = 2.0


class ConfigError(Exception):
    """A configuration problem, naming the file, the device and the field."""

    def __init__(self, file: str, device: str, field: str, reason: str) -> None:
        self.file = file
        self.device = device
        self.field = field
        self.reason = reason
        super().__init__(f"{file}: device '{device}', field '{field}': {reason}")


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _positive_number(value: object) -> bool:
    return _is_number(value) and math.isfinite(float(value)) and float(value) > 0  # type: ignore[arg-type]


def _load_point(file: str, device: str, index: int, raw: object) -> PointConfig:
    if not isinstance(raw, Mapping):
        raise ConfigError(file, device, f"points[{index}]", "must be a mapping")
    label = raw.get("name") if isinstance(raw.get("name"), str) and raw.get("name") else None
    prefix = f"points[{label}]" if label else f"points[{index}]"

    def text(key: str) -> str:
        if key not in raw:
            raise ConfigError(file, device, f"{prefix}.{key}", "is required")
        value = raw[key]
        if key == "address" and _is_number(value) and isinstance(value, int):
            return str(value)
        if not isinstance(value, str) or not value:
            raise ConfigError(file, device, f"{prefix}.{key}", "must be a non-empty string")
        return value

    name = text("name")
    address = text("address")
    type_text = text("data_type")
    unit = text("unit")
    try:
        data_type = DataType(type_text)
    except ValueError:
        supported = ", ".join(t.value for t in DataType)
        raise ConfigError(
            file,
            device,
            f"{prefix}.data_type",
            f"unsupported data type '{type_text}'; use one of: {supported}",
        ) from None
    scale: float | None = None
    if raw.get("scale") is not None:
        if not _positive_number(raw["scale"]):
            raise ConfigError(file, device, f"{prefix}.scale", "must be a number greater than zero")
        scale = float(raw["scale"])
    decimals: int | None = None
    if raw.get("decimals") is not None:
        value = raw["decimals"]
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 6:
            raise ConfigError(
                file, device, f"{prefix}.decimals", "must be a whole number from 0 to 6"
            )
        if data_type is DataType.BOOL:
            raise ConfigError(file, device, f"{prefix}.decimals", "is not allowed on a bool point")
        decimals = value
    return PointConfig(
        name=name, address=address, data_type=data_type, unit=unit, scale=scale, decimals=decimals
    )


def _load_device(file: str, index: int, raw: object) -> DeviceConfig:
    if not isinstance(raw, Mapping):
        raise ConfigError(file, f"devices[{index}]", "devices", "each device must be a mapping")
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise ConfigError(file, f"devices[{index}]", "name", "is required and must be text")
    description = raw.get("description", "")
    if not isinstance(description, str):
        raise ConfigError(file, name, "description", "must be text")
    timeout = DEFAULT_TIMEOUT_SECONDS
    if raw.get("timeout_seconds") is not None:
        if not _positive_number(raw["timeout_seconds"]):
            raise ConfigError(file, name, "timeout_seconds", "must be a number greater than zero")
        timeout = float(raw["timeout_seconds"])
    raw_points = raw.get("points", [])
    if not isinstance(raw_points, list):
        raise ConfigError(file, name, "points", "must be a list")
    points: list[PointConfig] = []
    seen: set[str] = set()
    for i, raw_point in enumerate(raw_points):
        point = _load_point(file, name, i, raw_point)
        if point.name in seen:
            raise ConfigError(file, name, f"points[{point.name}].name", "duplicate point name")
        seen.add(point.name)
        points.append(point)
    return DeviceConfig(
        name=name, description=description, timeout_seconds=timeout, points=tuple(points)
    )


def load_config(path: Path) -> Configuration:
    """Load and validate a YAML file. Raises ConfigError on the first problem found."""
    file = str(path)
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(file, "", "file", f"cannot be read ({exc.strerror})") from None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        raise ConfigError(file, "", "file", "is not valid YAML") from None
    if not isinstance(data, Mapping):
        raise ConfigError(file, "", "devices", "top level must be a mapping with 'devices'")
    raw_devices = data.get("devices", [])
    if not isinstance(raw_devices, list):
        raise ConfigError(file, "", "devices", "must be a list")
    return Configuration(devices=tuple(_load_device(file, i, d) for i, d in enumerate(raw_devices)))


def dump_config(config: Configuration) -> str:
    """Render a Configuration as YAML text that load_config reads back unchanged."""
    devices: list[dict[str, object]] = []
    for device in config.devices:
        points: list[dict[str, object]] = []
        for point in device.points:
            entry: dict[str, object] = {
                "name": point.name,
                "address": point.address,
                "data_type": point.data_type.value,
                "unit": point.unit,
            }
            if point.scale is not None:
                entry["scale"] = point.scale
            if point.decimals is not None:
                entry["decimals"] = point.decimals
            points.append(entry)
        devices.append(
            {
                "name": device.name,
                "description": device.description,
                "timeout_seconds": device.timeout_seconds,
                "points": points,
            }
        )
    return yaml.safe_dump({"devices": devices}, sort_keys=False, allow_unicode=False)
