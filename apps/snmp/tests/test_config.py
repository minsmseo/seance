"""Tests for the shipped apps/snmp/devices.yaml.

Facts about one file, so these are examples, not properties. No network and no
event loop: the Simulator is never started, only its OID map is read.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.snmp.address import parse_address
from apps.snmp.simulator import OID_MAP, OidEntry, SnmpType
from seance.config import ConfigError, load_config
from seance.points import Configuration, DataType, DeviceConfig, PointConfig

CONFIG_PATH = Path(__file__).resolve().parent.parent / "devices.yaml"

REQUIRED_POINTS: dict[str, set[str]] = {
    "core_switch": {
        "uptime",
        "port1_status",
        "port2_status",
        "port3_status",
        "port4_status",
        "uplink_in_octets",
        "uplink_out_octets",
        "uplink_in_errors",
    },
    "edge_router": {
        "uptime",
        "cpu_load",
        "memory_used",
        "wan_link_status",
        "wan_in_octets",
        "wan_out_octets",
    },
    "ups": {"battery_charge", "runtime_remaining", "power_source", "output_load", "temperature"},
}

COMPATIBLE_TYPES: dict[SnmpType, DataType] = {
    SnmpType.INTEGER: DataType.INT32,
    SnmpType.COUNTER32: DataType.UINT32,
    SnmpType.GAUGE32: DataType.UINT32,
    SnmpType.TIMETICKS: DataType.UINT32,
    SnmpType.COUNTER64: DataType.UINT64,
}

STATUS_POINTS = {
    "port1_status",
    "port2_status",
    "port3_status",
    "port4_status",
    "wan_link_status",
    "power_source",
}


@pytest.fixture(scope="module")
def config() -> Configuration:
    return load_config(CONFIG_PATH)


def _points(config: Configuration) -> list[tuple[DeviceConfig, PointConfig]]:
    return [(d, p) for d in config.devices for p in d.points]


def test_three_devices(config: Configuration) -> None:
    assert [d.name for d in config.devices] == ["core_switch", "edge_router", "ups"]


def test_nineteen_points(config: Configuration) -> None:
    assert len(_points(config)) == 19


def test_required_points_per_device(config: Configuration) -> None:
    for device in config.devices:
        names = [p.name for p in device.points]
        assert len(names) == len(set(names)), device.name
        assert set(names) == REQUIRED_POINTS[device.name], device.name


def test_data_type_coverage(config: Configuration) -> None:
    types = {p.data_type for _, p in _points(config)}
    assert {DataType.UINT32, DataType.INT32, DataType.UINT64} <= types


def test_scales_are_positive(config: Configuration) -> None:
    for _, point in _points(config):
        if point.scale is not None:
            assert point.scale > 0, point.name


def test_uptime_scale_is_one_hundredth_of_a_second(config: Configuration) -> None:
    uptimes = [p for _, p in _points(config) if p.name == "uptime"]
    assert len(uptimes) == 2
    for point in uptimes:
        assert point.data_type == DataType.UINT32
        assert point.scale == 0.01
        assert point.unit == "s"


def test_units_are_not_empty(config: Configuration) -> None:
    for device, point in _points(config):
        assert point.unit.strip() != "", f"{device.name}.{point.name}"


def test_status_points_carry_labels(config: Configuration) -> None:
    found = {p.name for _, p in _points(config) if p.labels}
    assert found == STATUS_POINTS
    for _, point in _points(config):
        if point.name in STATUS_POINTS:
            assert point.labels is not None
            assert all(text.strip() != "" for _, text in point.labels)


def test_every_address_parses_with_the_device_name_as_community(config: Configuration) -> None:
    for device, point in _points(config):
        address = parse_address(point.address)
        assert address.community == device.name, f"{device.name}.{point.name}"


def test_every_point_exists_in_the_simulator_map(config: Configuration) -> None:
    by_oid: dict[tuple[str, tuple[int, ...]], OidEntry] = {(e.device, e.oid): e for e in OID_MAP}
    seen: set[tuple[str, tuple[int, ...]]] = set()
    for device, point in _points(config):
        key = (device.name, parse_address(point.address).oid)
        entry = by_oid.get(key)
        assert entry is not None, f"{device.name}.{point.name}"
        assert entry.name == point.name
        assert COMPATIBLE_TYPES[entry.snmp_type] == point.data_type, point.name
        seen.add(key)
    assert seen == set(by_oid)


def test_labels_cover_every_reachable_status_value(config: Configuration) -> None:
    by_key = {(e.device, e.name): e for e in OID_MAP}
    for device, point in _points(config):
        if point.labels is None:
            continue
        entry = by_key[(device.name, point.name)]
        reachable = set(range(entry.minimum, entry.maximum + 1)) | {entry.initial}
        assert reachable <= {value for value, _ in point.labels}, f"{device.name}.{point.name}"


def test_bad_field_gives_one_message_naming_file_device_and_field(tmp_path: Path) -> None:
    bad = tmp_path / "devices.yaml"
    bad.write_text(
        "devices:\n"
        "  - name: core_switch\n"
        "    points:\n"
        "      - name: uptime\n"
        '        address: "core_switch:1.3.6.1.2.1.1.3.0"\n'
        "        data_type: uint32\n"
        "        unit: s\n"
        "        scale: -0.01\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as caught:
        load_config(bad)
    message = str(caught.value)
    assert "\n" not in message
    assert str(bad) in message
    assert "core_switch" in message
    assert "scale" in message
