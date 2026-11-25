"""Modbus TCP adapter. This is the only file in the repository that talks Modbus.

The adapter fetches raw bytes with function codes 1 to 4 and nothing else. It has
no write method. Word order for 32-bit values is high word first, and each word
is big-endian, which is what the skeleton Codec expects.
"""

import struct
import threading

from pymodbus.client import ModbusTcpClient
from pymodbus.constants import ExcCodes
from pymodbus.exceptions import ModbusException

from apps.modbus.address import AddressError, ModbusAddress, Table, parse_address
from seance.adapter import AdapterReadError, HealthStatus
from seance.codec import required_length
from seance.points import DataType, DeviceConfig, PointConfig

_BIT_TABLES = frozenset({Table.COIL, Table.DISCRETE})
_REGISTER_TABLES = frozenset({Table.HOLDING, Table.INPUT})

_EXCEPTION_WORDS: dict[int, str] = {
    ExcCodes.ILLEGAL_FUNCTION: "does not support this kind of read",
    ExcCodes.ILLEGAL_VALUE: "rejected the number of values requested",
    ExcCodes.DEVICE_FAILURE: "reported an internal failure",
    ExcCodes.ACKNOWLEDGE: "accepted the request but is still working on it",
    ExcCodes.DEVICE_BUSY: "is busy",
    ExcCodes.NEGATIVE_ACKNOWLEDGE: "could not perform the read",
    ExcCodes.MEMORY_PARITY_ERROR: "reported a memory error",
    ExcCodes.GATEWAY_PATH_UNAVIABLE: "has no gateway path to the target",
    ExcCodes.GATEWAY_NO_RESPONSE: "got no answer from the target behind the gateway",
}


class _DeviceSilent(AdapterReadError):
    """The device did not answer: refused, reset or timed out. Health maps it to unreachable."""


class ModbusAdapter:
    """Reads Modbus tables from one TCP endpoint. Read-only by construction."""

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        # retries=0: one request is one timeout, so the device timeout is the real bound.
        self._client = ModbusTcpClient(host, port=port, timeout=2.0, retries=0)
        self._lock = threading.Lock()

    def connect(self) -> None:
        """Open the TCP connection. A device that is down is reported on read, not here."""
        with self._lock:
            self._client.connect()

    def close(self) -> None:
        """Close the TCP connection."""
        with self._lock:
            self._client.close()

    def read(self, device: DeviceConfig, point: PointConfig) -> bytes:
        """Read one point and return its raw bytes in the Codec's layout."""
        try:
            address = parse_address(point.address)
        except AddressError as error:
            raise AdapterReadError(f"Point {point.name} has a bad address. {error}") from None
        self._check_fit(point, address)
        return self._fetch(device, point, address)

    def health(self, device: DeviceConfig) -> HealthStatus:
        """Read the first point: ok if it answers, degraded on an exception, else unreachable."""
        if not device.points:
            with self._lock:
                connected = bool(self._client.connected)
            return HealthStatus.OK if connected else HealthStatus.UNREACHABLE
        try:
            self.read(device, device.points[0])
        except _DeviceSilent:
            return HealthStatus.UNREACHABLE
        except AdapterReadError:
            return HealthStatus.DEGRADED
        return HealthStatus.OK

    @staticmethod
    def _check_fit(point: PointConfig, address: ModbusAddress) -> None:
        """Raise AdapterReadError when the data type cannot live in the table."""
        is_bool = point.data_type == DataType.BOOL
        fits = (is_bool and address.table in _BIT_TABLES) or (
            not is_bool and address.table in _REGISTER_TABLES
        )
        if not fits:
            allowed = "coil or discrete" if is_bool else "holding or input"
            raise AdapterReadError(
                f"Point {point.name} is {point.data_type.value} but its table is "
                f"{address.table.value}. Use the {allowed} table for this type."
            )

    def _fetch(self, device: DeviceConfig, point: PointConfig, address: ModbusAddress) -> bytes:
        is_bits = address.table in _BIT_TABLES
        count = 1 if is_bits else required_length(point.data_type) // 2
        try:
            with self._lock:
                # The pymodbus sync client reads its timeout from here on every request.
                self._client.comm_params.timeout_connect = device.timeout_seconds
                if address.table == Table.COIL:
                    result = self._client.read_coils(
                        address.offset, count=count, device_id=address.unit
                    )
                elif address.table == Table.DISCRETE:
                    result = self._client.read_discrete_inputs(
                        address.offset, count=count, device_id=address.unit
                    )
                elif address.table == Table.HOLDING:
                    result = self._client.read_holding_registers(
                        address.offset, count=count, device_id=address.unit
                    )
                else:
                    result = self._client.read_input_registers(
                        address.offset, count=count, device_id=address.unit
                    )
        except (ModbusException, OSError, TimeoutError):
            self._client.close()
            raise _DeviceSilent(self._silence_sentence(device, point)) from None
        if result.isError():
            code = getattr(result, "exception_code", None)
            if not isinstance(code, int) or code == 0:
                # A result without an exception code is an I/O failure, not a device answer.
                self._client.close()
                raise _DeviceSilent(self._silence_sentence(device, point))
            raise AdapterReadError(self._exception_sentence(device, point, code))
        if is_bits:
            if not result.bits:
                raise AdapterReadError(self._short_answer(device, point))
            return b"\x01" if result.bits[0] else b"\x00"
        registers = list(result.registers)
        if len(registers) < count:
            raise AdapterReadError(self._short_answer(device, point))
        return b"".join(struct.pack(">H", word) for word in registers[:count])

    @staticmethod
    def _silence_sentence(device: DeviceConfig, point: PointConfig) -> str:
        return (
            f"Device {device.name} did not answer for point {point.name} "
            f"within {device.timeout_seconds:g} seconds. Check that it is powered "
            f"and reachable, then try again."
        )

    @staticmethod
    def _short_answer(device: DeviceConfig, point: PointConfig) -> str:
        return (
            f"Device {device.name} returned too little data for point {point.name}. "
            f"Try again, or check the point's data type."
        )

    @staticmethod
    def _exception_sentence(device: DeviceConfig, point: PointConfig, code: int) -> str:
        if code == ExcCodes.ILLEGAL_ADDRESS:
            return (
                f"Point {point.name} is outside the range of device {device.name}. "
                f"Check the address in the configuration."
            )
        words = _EXCEPTION_WORDS.get(code, f"answered with exception code {code}")
        return f"Device {device.name} {words} for point {point.name}. Try again later."
