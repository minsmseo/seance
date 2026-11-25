"""Modbus TCP simulator for a small batch mixing line.

The simulator serves three devices, one per Modbus unit id, from one TCP port.
Every device has all four tables. Values use the high word first and each word
big-endian (pymodbus packs ``>I``, ``>i`` and ``>f`` that way), so a uint32 at
offset N is registers N (high) and N+1 (low).

Memory map (``engineering = raw * scale``). This is the single source of truth
that ``devices.yaml`` (task 8.1) must match. Addresses read ``unit:table:offset``.

mixing_tank, unit 1
    level            1:holding:0   uint16   scale 0.1   unit percent   (0..1000 raw)
    agitator_speed   1:holding:1   uint32   scale 1     unit rpm       (registers 1 and 2)
    temperature      1:input:0     int16    scale 0.1   unit degC      (-200..1200 raw)
    agitator_running 1:coil:0      bool     scale 1     unit state
    low_level        1:discrete:0  bool     scale 1     unit state

feed_pump, unit 2
    runtime_hours    2:holding:0   uint32   scale 1     unit h         (registers 0 and 1)
    flow_rate        2:input:0     float32  scale 1     unit L/min     (registers 0 and 1)
    pump_running     2:coil:0      bool     scale 1     unit state
    overload_trip    2:discrete:0  bool     scale 1     unit state

chiller, unit 3
    setpoint         3:holding:0   int16    scale 0.1   unit degC      (-100..300 raw)
    supply_temp      3:input:0     float32  scale 1     unit degC      (registers 0 and 1)
    compressor_on    3:coil:0      bool     scale 1     unit state
    fault            3:discrete:0  bool     scale 1     unit state

Every offset not listed above is undefined. Reading one gives the Modbus
exception "illegal data address". Any function code other than 1, 2, 3 or 4
gives "illegal function". An unknown unit id gives "gateway target failed to
respond". Coil and discrete tables are addressed one bit per offset.

Extension points for drift and value access: ``MEMORY_MAP`` holds the initial
value, minimum and maximum of every entry, and ``Simulator.seed`` and
``Simulator.rng`` are the seeded random source. Live register storage is
``server.context.devices[unit].block`` inside pymodbus (keys ``h``, ``i``, ``c``
and ``d``); writes must go there directly because the request path is read-only.
"""

from __future__ import annotations

import asyncio
import random
import socket
import struct
import sys
import threading
import time
from dataclasses import dataclass
from typing import Literal

from pymodbus.constants import ExcCodes
from pymodbus.pdu import ExceptionResponse, ModbusPDU
from pymodbus.server import ModbusTcpServer
from pymodbus.server.requesthandler import ServerRequestHandler
from pymodbus.simulator import DataType, SimData, SimDevice

TableName = Literal["coil", "discrete", "input", "holding"]
DataTypeName = Literal["bool", "uint16", "int16", "uint32", "float32"]

READ_FUNCTION_CODES: frozenset[int] = frozenset({1, 2, 3, 4})
STOP_TIMEOUT_SECONDS = 2.0
START_TIMEOUT_SECONDS = 5.0
_MBAP_HEADER_LENGTH = 7


class SimulatorError(RuntimeError):
    """Raised with a short sentence when the simulator cannot start or stop."""


@dataclass(frozen=True)
class MapEntry:
    """One value in the simulator memory: where it lives and how it behaves."""

    device: str
    unit: int
    table: TableName
    offset: int
    name: str
    data_type: DataTypeName
    initial: int | float | bool
    minimum: int | float
    maximum: int | float
    scale: float
    engineering_unit: str


MEMORY_MAP: tuple[MapEntry, ...] = (
    MapEntry("mixing_tank", 1, "holding", 0, "level", "uint16", 650, 0, 1000, 0.1, "percent"),
    MapEntry("mixing_tank", 1, "holding", 1, "agitator_speed", "uint32", 120, 0, 300, 1, "rpm"),
    MapEntry("mixing_tank", 1, "input", 0, "temperature", "int16", 185, -200, 1200, 0.1, "degC"),
    MapEntry("mixing_tank", 1, "coil", 0, "agitator_running", "bool", True, 0, 1, 1, "state"),
    MapEntry("mixing_tank", 1, "discrete", 0, "low_level", "bool", False, 0, 1, 1, "state"),
    MapEntry("feed_pump", 2, "holding", 0, "runtime_hours", "uint32", 12345, 0, 4000000000, 1, "h"),
    MapEntry("feed_pump", 2, "input", 0, "flow_rate", "float32", 42.5, 0.0, 80.0, 1, "L/min"),
    MapEntry("feed_pump", 2, "coil", 0, "pump_running", "bool", True, 0, 1, 1, "state"),
    MapEntry("feed_pump", 2, "discrete", 0, "overload_trip", "bool", False, 0, 1, 1, "state"),
    MapEntry("chiller", 3, "holding", 0, "setpoint", "int16", 60, -100, 300, 0.1, "degC"),
    MapEntry("chiller", 3, "input", 0, "supply_temp", "float32", 6.5, -5.0, 25.0, 1, "degC"),
    MapEntry("chiller", 3, "coil", 0, "compressor_on", "bool", True, 0, 1, 1, "state"),
    MapEntry("chiller", 3, "discrete", 0, "fault", "bool", False, 0, 1, 1, "state"),
)

LEVEL_LOW_LIMIT_RAW = 200
"""Mixing tank level (raw, 0.1 percent steps) below which low_level is set: 20.0 percent."""

DRIFT_INTERVAL_SECONDS = 0.5
DRIFT_STEP_FRACTION = 0.02
_TABLE_BLOCK_KEY: dict[str, str] = {"coil": "c", "discrete": "d", "holding": "h", "input": "i"}
_MAP_BY_KEY: dict[tuple[str, str], MapEntry] = {(e.device, e.name): e for e in MEMORY_MAP}
_LEVEL_KEY = ("mixing_tank", "level")
_LOW_LEVEL_KEY = ("mixing_tank", "low_level")


def _drift_limit(entry: MapEntry) -> float:
    """Largest drift step: 2 percent of the start value, and at least 1 for integer types."""
    limit = abs(float(entry.initial)) * DRIFT_STEP_FRACTION
    if entry.data_type == "float32":
        return limit
    return max(limit, 1.0)


def _encode(entry: MapEntry, value: int | float) -> list[int]:
    """Encode a raw value as 16-bit register words, high word first, each word big-endian."""
    if entry.data_type == "uint16":
        return [int(value) & 0xFFFF]
    if entry.data_type == "int16":
        return [int(value) & 0xFFFF]
    if entry.data_type == "uint32":
        packed = struct.pack(">I", int(value))
    else:
        packed = struct.pack(">f", float(value))
    return [int.from_bytes(packed[:2], "big"), int.from_bytes(packed[2:], "big")]


def _decode(entry: MapEntry, words: list[int]) -> int | float:
    """Decode register words, the reverse of ``_encode``."""
    raw = b"".join(word.to_bytes(2, "big") for word in words)
    if entry.data_type == "uint16":
        return int.from_bytes(raw, "big")
    if entry.data_type == "int16":
        return int.from_bytes(raw, "big", signed=True)
    if entry.data_type == "uint32":
        return int.from_bytes(raw, "big")
    return float(struct.unpack(">f", raw)[0])


_SIM_TYPES: dict[str, DataType] = {
    "bool": DataType.BITS,
    "uint16": DataType.UINT16,
    "int16": DataType.INT16,
    "uint32": DataType.UINT32,
    "float32": DataType.FLOAT32,
}

_TABLE_INDEX: dict[str, int] = {"coil": 0, "discrete": 1, "holding": 2, "input": 3}


def _sim_data(entry: MapEntry) -> SimData:
    """Build the pymodbus SimData for one memory map entry."""
    if entry.data_type == "bool":
        return SimData(entry.offset, values=[bool(entry.initial)], datatype=DataType.BITS)
    is_float = entry.data_type == "float32"
    value: int | float = float(entry.initial) if is_float else int(entry.initial)
    return SimData(entry.offset, values=value, datatype=_SIM_TYPES[entry.data_type])


def _build_devices() -> list[SimDevice]:
    """Build one SimDevice per unit id, each with four separate tables."""
    units = sorted({entry.unit for entry in MEMORY_MAP})
    devices: list[SimDevice] = []
    for unit in units:
        tables: tuple[list[SimData], list[SimData], list[SimData], list[SimData]] = (
            [],
            [],
            [],
            [],
        )
        for entry in MEMORY_MAP:
            if entry.unit == unit:
                tables[_TABLE_INDEX[entry.table]].append(_sim_data(entry))
        devices.append(SimDevice(id=unit, simdata=tables))
    return devices


def _defined_bits() -> dict[int, dict[str, frozenset[int]]]:
    """Return the defined bit offsets per unit for the coil and discrete tables."""
    bits: dict[int, dict[str, set[int]]] = {}
    for entry in MEMORY_MAP:
        if entry.table in ("coil", "discrete"):
            bits.setdefault(entry.unit, {}).setdefault(entry.table, set()).add(entry.offset)
    return {
        unit: {table: frozenset(offsets) for table, offsets in tables.items()}
        for unit, tables in bits.items()
    }


class _ReadOnlyHandler(ServerRequestHandler):
    """Request handler that answers only function codes 1 to 4 and only defined bits."""

    async def handle_request(self, pdu: ModbusPDU) -> None:
        owner: _Server = self.server  # type: ignore[assignment]
        code: ExcCodes | None = None
        if pdu.function_code not in READ_FUNCTION_CODES:
            code = ExcCodes.ILLEGAL_FUNCTION
        elif pdu.dev_id not in owner.defined_bits_by_unit:
            code = ExcCodes.GATEWAY_NO_RESPONSE
        elif pdu.function_code in (1, 2):
            table = "coil" if pdu.function_code == 1 else "discrete"
            defined = owner.defined_bits_by_unit[pdu.dev_id].get(table, frozenset())
            wanted = range(pdu.address, pdu.address + pdu.count)  # type: ignore[attr-defined]
            if not all(bit in defined for bit in wanted):
                code = ExcCodes.ILLEGAL_ADDRESS
        if code is None:
            await super().handle_request(pdu)
            return
        response = ExceptionResponse(pdu.function_code, code)
        response.transaction_id = pdu.transaction_id
        response.dev_id = pdu.dev_id
        self.server_send(response, self.last_addr)


class _Server(ModbusTcpServer):
    """pymodbus TCP server that uses the read-only handler."""

    defined_bits_by_unit: dict[int, dict[str, frozenset[int]]] = {}

    def callback_new_connection(self) -> ServerRequestHandler:
        """Create the handler for a new client connection."""
        return _ReadOnlyHandler(self, self.trace_packet, self.trace_pdu, self.trace_connect)


def _port_bind_error(host: str, port: int) -> OSError | None:
    """Return the OSError if the port cannot be bound now, else None.

    pymodbus listens with address reuse, which on Windows lets a second server share
    a busy port. A plain bind (no reuse on Windows) detects that case before start.
    """
    probe = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET)
    try:
        if sys.platform != "win32":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((host, port))
    except OSError as exc:
        return exc
    finally:
        probe.close()
    return None


class Simulator:
    """Modbus TCP server for the three-device mixing line, run on a background thread.

    A Simulator runs once. It creates exactly one asyncio event loop, on its first
    ``start()``, and closes it when the server thread ends. Calling ``start()`` again,
    even after ``stop()`` or a failed start, raises ``SimulatorError``: create a new
    Simulator instead. Port 0 asks the operating system for a free port; ``port``
    then returns the real port once ``start()`` has returned.
    """

    def __init__(self, host: str, port: int, seed: int) -> None:
        self._host = host
        self._port = port
        self._started = False
        self._seed = seed
        self._rng = random.Random(seed)
        self._lock = threading.Lock()
        self._memory_lock = threading.RLock()
        self._stop_drift = threading.Event()
        self._drift_thread: threading.Thread | None = None
        self._function_codes: list[int] = []
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: _Server | None = None
        self._ready = threading.Event()
        self._start_error: str | None = None

    @property
    def host(self) -> str:
        """Host the server listens on."""
        return self._host

    @property
    def port(self) -> int:
        """Port the server listens on. For port 0 this is the real port after ``start()``."""
        return self._port

    @property
    def seed(self) -> int:
        """Random seed given at construction."""
        return self._seed

    @property
    def rng(self) -> random.Random:
        """Seeded random source for drift."""
        return self._rng

    @property
    def function_codes_seen(self) -> tuple[int, ...]:
        """Every function code received so far, in arrival order (a snapshot)."""
        with self._lock:
            return tuple(self._function_codes)

    @property
    def running(self) -> bool:
        """True while the server thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Start serving on a background thread. Returns once the port is listening.

        Works once per instance. A second call raises SimulatorError.
        """
        if self.running:
            raise SimulatorError("The simulator is already running.")
        if self._started:
            raise SimulatorError("This simulator already ran once. Create a new Simulator.")
        self._started = True
        if self._port != 0:
            bind_error = _port_bind_error(self._host, self._port)
            if bind_error is not None:
                raise SimulatorError(
                    f"Port {self._port} is already in use ({bind_error}). Try another port."
                ) from bind_error
        try:
            self._loop = asyncio.new_event_loop()
        except OSError as exc:
            raise SimulatorError(
                f"The simulator could not create its event loop ({exc}). Create a new Simulator."
            ) from exc
        self._ready.clear()
        self._start_error = None
        self._thread = threading.Thread(target=self._run, name="modbus-simulator", daemon=True)
        self._thread.start()
        if not self._ready.wait(START_TIMEOUT_SECONDS):
            raise SimulatorError("The simulator did not start in time. Try another port.")
        if self._start_error is not None:
            self._thread.join(STOP_TIMEOUT_SECONDS)
            raise SimulatorError(self._start_error)
        self._stop_drift.clear()
        self._drift_thread = threading.Thread(
            target=self._drift_loop, name="modbus-simulator-drift", daemon=True
        )
        self._drift_thread.start()

    def stop(self) -> None:
        """Stop drifting and serving and release the port, within 2 seconds.

        Safe to call when not running.
        """
        deadline = time.monotonic() + STOP_TIMEOUT_SECONDS
        self._stop_drift.set()
        drift = self._drift_thread
        if drift is not None:
            drift.join(max(deadline - time.monotonic(), 0.0))
            if drift.is_alive():
                raise SimulatorError("The drift thread did not stop in time.")
            self._drift_thread = None
        thread, loop, server = self._thread, self._loop, self._server
        if thread is None or loop is None or server is None or not thread.is_alive():
            if loop is not None and not loop.is_closed() and not (thread and thread.is_alive()):
                loop.close()
            return
        future = asyncio.run_coroutine_threadsafe(server.shutdown(), loop)
        try:
            future.result(max(deadline - time.monotonic(), 0.1))
        except Exception as exc:  # noqa: BLE001 - report one short sentence instead
            raise SimulatorError("The simulator did not stop cleanly. Try again.") from exc
        thread.join(max(deadline - time.monotonic(), 0.1))
        if thread.is_alive():
            raise SimulatorError("The simulator thread did not stop in time.")

    def get_value(self, device: str, name: str) -> int | float | bool:
        """Return the raw value of a point from the simulator memory (for tests).

        Raw means before ``scale``. Raises SimulatorError for an unknown point or
        when the simulator is not running.
        """
        entry = self._entry(device, name)
        with self._memory_lock:
            words = self._words(entry)
            if entry.data_type == "bool":
                return self._get_bit(entry, words)
            return _decode(entry, words[: 1 if entry.data_type in ("uint16", "int16") else 2])

    def set_value(self, device: str, name: str, value: int | float | bool) -> None:
        """Set the raw value of a point in the simulator memory (for tests).

        Setting the mixing tank level also updates its low-level input. The value is
        clamped to the declared minimum and maximum of the point.
        """
        entry = self._entry(device, name)
        with self._memory_lock:
            self._store(entry, value)
            if (device, name) == _LEVEL_KEY:
                self._update_low_level()

    def drift_step(self) -> None:
        """Apply one drift step to every analog value, then refresh the low-level input.

        Draws one random number per analog value in memory map order, so equal seeds
        give equal sequences. The drift thread calls this about every half second.
        """
        with self._memory_lock:
            for entry in MEMORY_MAP:
                if entry.data_type == "bool":
                    continue
                limit = _drift_limit(entry)
                step = self._rng.uniform(-limit, limit)
                current = self._read_number(entry)
                self._store(entry, current + step)
            self._update_low_level()

    def _drift_loop(self) -> None:
        """Thread body: drift until stopped."""
        while not self._stop_drift.wait(DRIFT_INTERVAL_SECONDS):
            self.drift_step()

    @staticmethod
    def _entry(device: str, name: str) -> MapEntry:
        """Find a memory map entry or raise one short sentence."""
        entry = _MAP_BY_KEY.get((device, name))
        if entry is None:
            raise SimulatorError(f"Unknown point {name} on device {device}. Check the name.")
        return entry

    def _block(self, entry: MapEntry) -> tuple[int, int, list[int], list[int]]:
        """Return the live pymodbus block for the entry's table."""
        server = self._server
        if server is None or not self.running:
            raise SimulatorError("The simulator is not running. Start it first.")
        return server.context.devices[entry.unit].block[_TABLE_BLOCK_KEY[entry.table]]

    def _words(self, entry: MapEntry) -> list[int]:
        """Return the live register words from the entry's offset to the end of its block."""
        start, _, registers, _ = self._block(entry)
        return registers[entry.offset - start :]

    def _get_bit(self, entry: MapEntry, words: list[int]) -> bool:
        """Read one bit; coil and discrete offsets are one register apart in this datastore."""
        return bool(words[0] & (1 << (entry.offset % 16)))

    def _read_number(self, entry: MapEntry) -> int | float:
        """Read an analog value as a number."""
        value = self.get_value(entry.device, entry.name)
        return float(value) if entry.data_type == "float32" else int(value)

    def _store(self, entry: MapEntry, value: int | float | bool) -> None:
        """Clamp and write one value into the live registers."""
        start, _, registers, _ = self._block(entry)
        index = entry.offset - start
        if entry.data_type == "bool":
            mask = 1 << (entry.offset % 16)
            registers[index] = (registers[index] | mask) if value else (registers[index] & ~mask)
            return
        clamped = min(max(value, entry.minimum), entry.maximum)
        number: int | float = clamped if entry.data_type == "float32" else round(clamped)
        for position, word in enumerate(_encode(entry, number)):
            registers[index + position] = word

    def _update_low_level(self) -> None:
        """Set low_level below the limit, clear it above, leave it unchanged at the limit."""
        level = self._read_number(_MAP_BY_KEY[_LEVEL_KEY])
        low_entry = _MAP_BY_KEY[_LOW_LEVEL_KEY]
        if level < LEVEL_LOW_LIMIT_RAW:
            self._store(low_entry, True)
        elif level > LEVEL_LOW_LIMIT_RAW:
            self._store(low_entry, False)

    def _record_packet(self, sending: bool, data: bytes) -> bytes:
        """Record the function code of every request frame the server receives."""
        if not sending:
            codes: list[int] = []
            position = 0
            while position + _MBAP_HEADER_LENGTH < len(data):
                codes.append(data[position + _MBAP_HEADER_LENGTH])
                length = int.from_bytes(data[position + 4 : position + 6], "big")
                position += 6 + max(length, 1)
            with self._lock:
                self._function_codes.extend(codes)
        return data

    def _run(self) -> None:
        """Thread body: run the simulator's one asyncio loop until stopped, then close it."""
        loop = self._loop
        try:
            if loop is None:
                raise SimulatorError("The simulator has no event loop.")
            loop.run_until_complete(self._serve())
        except Exception as exc:  # noqa: BLE001 - startup failures are reported through start()
            if not self._ready.is_set():
                self._start_error = (
                    f"The simulator could not listen on {self._host}:{self._port} ({exc}). "
                    "Try another port."
                )
                self._ready.set()
        finally:
            if loop is not None:
                loop.close()

    async def _serve(self) -> None:
        """Create the server, listen, signal readiness and wait for shutdown."""
        server = _Server(
            _build_devices(),
            address=(self._host, self._port),
            trace_packet=self._record_packet,
        )
        server.defined_bits_by_unit = _defined_bits()
        self._server = server
        await server.serve_forever(background=True)
        if self._port == 0:
            # server.transport is the asyncio.Server returned by create_server.
            sockets = server.transport.sockets  # type: ignore[attr-defined]
            self._port = int(sockets[0].getsockname()[1])
        self._ready.set()
        await server.serving
