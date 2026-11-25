"""Tests for the shipped apps/modbus/devices.yaml.

Facts about one file, so these are examples, not properties. One module-scoped
Simulator on 127.0.0.1 and an OS-assigned port serves the read-through test, so
the module creates one asyncio event loop.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from apps.modbus import simulator as sim_module
from apps.modbus.adapter import ModbusAdapter
from apps.modbus.address import Table, parse_address
from apps.modbus.simulator import Simulator
from seance.codec import required_length
from seance.config import ConfigError, load_config
from seance.points import Configuration, DataType

HOST = "127.0.0.1"
CONFIG_PATH = Path(__file__).resolve().parent.parent / "devices.yaml"
BIT_TABLES = (Table.COIL, Table.DISCRETE)


@pytest.fixture(scope="module")
def config() -> Configuration:
    return load_config(CONFIG_PATH)


@pytest.fixture(scope="module")
def simulator() -> Iterator[Simulator]:
    patch = pytest.MonkeyPatch()
    patch.setattr(sim_module, "DRIFT_INTERVAL_SECONDS", 3600.0)
    running = Simulator(HOST, 0, 1)
    running.start()
    try:
        yield running
    finally:
        running.stop()
        patch.undo()


@pytest.fixture(scope="module")
def adapter(simulator: Simulator) -> Iterator[ModbusAdapter]:
    connected = ModbusAdapter(HOST, simulator.port)
    connected.connect()
    yield connected
    connected.close()


def test_three_devices(config: Configuration) -> None:
    assert [d.name for d in config.devices] == ["mixing_tank", "feed_pump", "chiller"]


def test_point_count_is_11_to_13(config: Configuration) -> None:
    total = sum(len(d.points) for d in config.devices)
    assert 11 <= total <= 13


def test_every_table_is_covered(config: Configuration) -> None:
    tables = {parse_address(p.address).table for d in config.devices for p in d.points}
    assert tables == set(Table)


def test_every_register_data_type_is_covered(config: Configuration) -> None:
    types = {p.data_type for d in config.devices for p in d.points}
    assert {DataType.UINT16, DataType.INT16, DataType.UINT32, DataType.FLOAT32} <= types


def test_scales_are_positive_and_units_are_not_empty(config: Configuration) -> None:
    for device in config.devices:
        for point in device.points:
            assert point.unit.strip() != ""
            if point.scale is not None:
                assert point.scale > 0


def test_every_address_parses_and_fits_its_data_type(config: Configuration) -> None:
    for device in config.devices:
        for point in device.points:
            address = parse_address(point.address)
            is_bit_table = address.table in BIT_TABLES
            assert (point.data_type == DataType.BOOL) == is_bit_table, point.name


def test_every_point_reads_from_the_simulator(
    config: Configuration, adapter: ModbusAdapter, simulator: Simulator
) -> None:
    for device in config.devices:
        for point in device.points:
            raw = adapter.read(device, point)
            assert len(raw) == required_length(point.data_type), f"{device.name}.{point.name}"
        assert adapter.health(device).value == "ok"


def test_bad_field_gives_one_message_naming_file_device_and_field(tmp_path: Path) -> None:
    bad = tmp_path / "devices.yaml"
    bad.write_text(
        "devices:\n"
        "  - name: feed_pump\n"
        "    points:\n"
        "      - name: flow_rate\n"
        '        address: "2:input:0"\n'
        "        data_type: float32\n"
        "        unit: L/min\n"
        "        scale: -1\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as caught:
        load_config(bad)
    message = str(caught.value)
    assert "\n" not in message
    assert str(bad) in message
    assert "feed_pump" in message
    assert "scale" in message
