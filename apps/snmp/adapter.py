"""SNMP v2c adapter. This is the only file in the repository that imports pysnmp.

The adapter sends GET requests and nothing else. It has no write method and it
imports no other command generator. One private event loop runs on one daemon
thread and owns the one SnmpEngine, so a read from any worker thread never
creates a loop.
"""

import asyncio
import contextlib
import struct
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    get_cmd,
)
from pysnmp.proto.rfc1902 import Counter32, Counter64, Gauge32, Integer32, OctetString, TimeTicks
from pysnmp.proto.rfc1905 import EndOfMibView, NoSuchInstance, NoSuchObject

from apps.snmp.address import AddressError, format_oid, parse_address
from seance.adapter import AdapterReadError, HealthStatus
from seance.points import DataType, DeviceConfig, PointConfig

_JOIN_SECONDS = 5.0
_START_SECONDS = 5.0
_EXTRA_WAIT_SECONDS = 1.0

_STATUS_WORDS: dict[int, str] = {
    1: "tooBig",
    2: "noSuchName",
    3: "badValue",
    4: "readOnly",
    5: "genErr",
    6: "noAccess",
    7: "wrongType",
    8: "wrongLength",
    9: "wrongEncoding",
    10: "wrongValue",
    11: "noCreation",
    12: "inconsistentValue",
    13: "resourceUnavailable",
    14: "commitFailed",
    15: "undoFailed",
    16: "authorizationError",
    17: "notWritable",
    18: "inconsistentName",
}


class _DeviceSilent(AdapterReadError, TimeoutError):
    """The device did not answer. Health maps it to unreachable.

    It is also a TimeoutError, so the Tool_Server answers with its Timeout_Sentence.
    """


def _type_name(value: object) -> str:
    """Name an SNMP value type with standard protocol words."""
    if isinstance(value, Counter64):
        return "Counter64"
    if isinstance(value, Counter32):
        return "Counter32"
    if isinstance(value, Gauge32):
        return "Gauge32"
    if isinstance(value, TimeTicks):
        return "TimeTicks"
    if isinstance(value, Integer32):
        return "INTEGER"
    if isinstance(value, OctetString):
        return "OCTET STRING"
    return "an unsupported type"


class SnmpAdapter:
    """Reads SNMP v2c values from one UDP endpoint. Read-only by construction."""

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._engine: SnmpEngine | None = None
        self._targets: dict[str, UdpTransportTarget] = {}

    def connect(self) -> None:
        """Start the loop thread and create the one SnmpEngine. Does nothing if started."""
        with self._lock:
            if self._thread is not None:
                return
            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=self._run_loop, args=(loop,), name="snmp-adapter", daemon=True
            )
            self._loop = loop
            self._thread = thread
            thread.start()
            try:
                asyncio.run_coroutine_threadsafe(self._make_engine(), loop).result(
                    timeout=_START_SECONDS
                )
            except BaseException:
                self._stop_locked()
                raise

    def close(self) -> None:
        """Close the engine, stop the loop and join the thread. Safe to call twice."""
        with self._lock:
            self._stop_locked()

    def read(self, device: DeviceConfig, point: PointConfig) -> bytes:
        """Send one GET and return the value as bytes in the Codec's layout."""
        try:
            address = parse_address(point.address)
        except AddressError as error:
            raise AdapterReadError(f"Point {point.name} has a bad address. {error}") from None
        loop = self._loop
        if loop is None or self._engine is None:
            raise AdapterReadError(
                f"The SNMP adapter is not connected, so point {point.name} was not read. "
                f"Restart the server."
            )
        future = asyncio.run_coroutine_threadsafe(
            self._get(device, point, address.community, format_oid(address.oid)), loop
        )
        try:
            return future.result(timeout=device.timeout_seconds + _EXTRA_WAIT_SECONDS)
        except FutureTimeoutError:
            future.cancel()
            raise _DeviceSilent(self._silence_sentence(device, point)) from None

    def health(self, device: DeviceConfig) -> HealthStatus:
        """Read the first point: ok if it answers, degraded on an error, else unreachable."""
        if not device.points:
            running = self._engine is not None
            return HealthStatus.OK if running else HealthStatus.UNREACHABLE
        try:
            self.read(device, device.points[0])
        except _DeviceSilent:
            return HealthStatus.UNREACHABLE
        except AdapterReadError:
            return HealthStatus.DEGRADED
        return HealthStatus.OK

    @staticmethod
    def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        try:
            loop.run_forever()
        finally:
            loop.close()

    async def _make_engine(self) -> None:
        self._engine = SnmpEngine()

    async def _close_engine(self) -> None:
        engine = self._engine
        self._engine = None
        self._targets = {}
        if engine is not None:
            engine.close_dispatcher()

    def _stop_locked(self) -> None:
        loop = self._loop
        thread = self._thread
        if loop is None or thread is None:
            return
        self._loop = None
        self._thread = None
        # Closing must always finish stopping the loop, so a failed engine close is ignored.
        with contextlib.suppress(Exception):
            asyncio.run_coroutine_threadsafe(self._close_engine(), loop).result(
                timeout=_JOIN_SECONDS
            )
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=_JOIN_SECONDS)

    async def _target(self, device: DeviceConfig) -> UdpTransportTarget:
        target = self._targets.get(device.name)
        if target is None:
            target = await UdpTransportTarget.create(
                (self._host, self._port), timeout=device.timeout_seconds, retries=0
            )
            self._targets[device.name] = target
        return target

    async def _get(
        self, device: DeviceConfig, point: PointConfig, community: str, oid_text: str
    ) -> bytes:
        engine = self._engine
        if engine is None:
            raise AdapterReadError(
                f"The SNMP adapter is not connected, so point {point.name} was not read. "
                f"Restart the server."
            )
        try:
            target = await self._target(device)
            error_indication, error_status, _error_index, var_binds = await asyncio.wait_for(
                get_cmd(
                    engine,
                    CommunityData(community, mpModel=1),
                    target,
                    ContextData(),
                    ObjectType(ObjectIdentity(oid_text)),
                    lookupMib=False,
                ),
                device.timeout_seconds,
            )
        except (TimeoutError, OSError):
            raise _DeviceSilent(self._silence_sentence(device, point)) from None
        if error_indication:
            raise _DeviceSilent(self._silence_sentence(device, point))
        status = int(error_status)
        if status != 0:
            word = _STATUS_WORDS.get(status, f"status {status}")
            raise AdapterReadError(
                f"Device {device.name} refused the read of point {point.name} ({word}). "
                f"Try again later."
            )
        if len(var_binds) < 1:
            raise AdapterReadError(self._no_value_sentence(device, point, oid_text))
        value = var_binds[0][1]
        if isinstance(value, (NoSuchObject, NoSuchInstance, EndOfMibView)):
            raise AdapterReadError(self._no_value_sentence(device, point, oid_text))
        return self._to_bytes(device, point, value)

    @staticmethod
    def _to_bytes(device: DeviceConfig, point: PointConfig, value: object) -> bytes:
        number = int(value) if isinstance(value, Integer32) else None
        if isinstance(value, Counter64):
            if point.data_type == DataType.UINT64:
                return struct.pack(">Q", int(value))
        elif isinstance(value, (Counter32, Gauge32, TimeTicks)):
            if point.data_type == DataType.UINT32:
                return struct.pack(">I", int(value))
        elif number is not None and point.data_type == DataType.INT32:
            return struct.pack(">i", number)
        raise AdapterReadError(
            f"Point {point.name} is {point.data_type.value} but device {device.name} "
            f"returned {_type_name(value)}. Check the data_type in the configuration."
        )

    @staticmethod
    def _silence_sentence(device: DeviceConfig, point: PointConfig) -> str:
        return (
            f"Device {device.name} did not answer for point {point.name} "
            f"within {device.timeout_seconds:g} seconds. Check that it is powered "
            f"and reachable, then try again."
        )

    @staticmethod
    def _no_value_sentence(device: DeviceConfig, point: PointConfig, oid_text: str) -> str:
        return (
            f"Device {device.name} has no value for point {point.name} at {oid_text}. "
            f"Check the OID in the configuration."
        )
