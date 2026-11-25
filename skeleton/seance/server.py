"""Tool_Server: the five MCP tools over a Configuration, an adapter, a guard and an audit log.

Every tool call goes through ToolServer.call, which asks the guard first, runs the
handler, and records exactly one AuditEntry in a finally block.
"""

import difflib
import json
import logging
import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, TypeVar

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from seance.adapter import AdapterReadError, ProtocolAdapter, check_adapter
from seance.audit import Audit_Log, AuditEntry
from seance.codec import RawValue, apply_scale, decode, round_value
from seance.config import load_config
from seance.guard import READ_TOOLS, Read_Only_Guard, Rejected
from seance.points import Configuration, DeviceConfig, PointConfig

if TYPE_CHECKING:
    import uvicorn
    from fastapi import FastAPI

logger = logging.getLogger("seance.server")

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]

TOOL_NAMES: tuple[str, ...] = (
    "list_devices",
    "list_points",
    "read_point",
    "read_points",
    "device_health",
)

_MAX_NAME_CHARS = 40
_MAX_MESSAGE_CHARS = 200
_MAX_SUGGESTIONS = 3
_MAX_LISTED = 5
_MAX_WORKERS = 8
_CONSOLE_STOP_SECONDS = 5.0

DEFAULT_CONSOLE_HOST = "127.0.0.1"
DEFAULT_CONSOLE_PORT = 8080

T = TypeVar("T")


@dataclass(frozen=True)
class ToolResult:
    """Outcome of one tool call.

    payload is a plain sentence (str) for a failed call, or JSON-ready data.
    outcome is the value written to the audit log.
    """

    ok: bool
    outcome: str
    payload: JsonValue

    @property
    def text(self) -> str:
        """The result as text for an agent: a sentence, or JSON."""
        if isinstance(self.payload, str):
            return self.payload
        return json.dumps(self.payload)


class _ToolFailure(Exception):
    """Internal: a handler stops with an outcome and a sentence for the agent."""

    def __init__(self, outcome: str, message: str) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.message = message


def _clip(name: str) -> str:
    """Make an echoed name safe and short: one line, at most 40 characters."""
    flat = " ".join(name.split())
    if len(flat) > _MAX_NAME_CHARS:
        return flat[: _MAX_NAME_CHARS - 3] + "..."
    return flat


def _clip_message(message: str) -> str:
    """Make an adapter's sentence one line, at most 200 characters."""
    flat = " ".join(message.split())
    if not flat:
        return "The adapter reported an error. Try again, or check the device connection."
    if len(flat) > _MAX_MESSAGE_CHARS:
        return flat[: _MAX_MESSAGE_CHARS - 3] + "..."
    return flat


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _unknown(kind: str, name: str, known: list[str], where: str = "") -> _ToolFailure:
    """Build an unknown-name failure that lists the closest matches."""
    head = f"Unknown {kind} '{_clip(name)}'{where}."
    if not known:
        return _ToolFailure("unknown_target", f"{head} No {kind}s are configured.")
    close = difflib.get_close_matches(name, known, n=_MAX_SUGGESTIONS, cutoff=0.6)
    if close:
        names = ", ".join(_clip(n) for n in close)
        return _ToolFailure("unknown_target", f"{head} Closest matches: {names}.")
    names = ", ".join(_clip(n) for n in known[:_MAX_LISTED])
    return _ToolFailure("unknown_target", f"{head} Known {kind}s: {names}.")


def _required_text(args: Mapping[str, object], name: str) -> str:
    if name not in args or args[name] is None:
        raise _ToolFailure("invalid_argument", f"Invalid argument '{name}': it is required.")
    value = args[name]
    if not isinstance(value, str) or not value.strip():
        raise _ToolFailure(
            "invalid_argument", f"Invalid argument '{name}': expected a non-empty text value."
        )
    return value


def _required_names(args: Mapping[str, object], name: str) -> list[str]:
    if name not in args or args[name] is None:
        raise _ToolFailure("invalid_argument", f"Invalid argument '{name}': it is required.")
    value = args[name]
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(v, str) and v.strip() for v in value)
    ):
        raise _ToolFailure(
            "invalid_argument",
            f"Invalid argument '{name}': expected a non-empty list of point names.",
        )
    return [str(v) for v in value]


def _audit_text(args: Mapping[str, object], name: str) -> str:
    value = args.get(name)
    return value if isinstance(value, str) else ""


def _audit_point(args: Mapping[str, object]) -> str:
    point = _audit_text(args, "point")
    if point:
        return point
    points = args.get("points")
    if isinstance(points, list):
        return ",".join(p for p in points if isinstance(p, str))
    return ""


class ToolServer:
    """Runs the five read tools against one adapter and one Configuration."""

    def __init__(
        self,
        config: Configuration,
        adapter: ProtocolAdapter,
        guard: Read_Only_Guard | None = None,
        audit: Audit_Log | None = None,
    ) -> None:
        self._config = config
        self._adapter = adapter
        self._guard = guard if guard is not None else Read_Only_Guard()
        self._audit = audit if audit is not None else Audit_Log()
        self._executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="seance")
        self._handlers: dict[str, Callable[[Mapping[str, object]], tuple[str, JsonValue]]] = {
            "list_devices": self._list_devices,
            "list_points": self._list_points,
            "read_point": self._read_point,
            "read_points": self._read_points,
            "device_health": self._device_health,
        }

    @property
    def audit(self) -> Audit_Log:
        return self._audit

    @property
    def config(self) -> Configuration:
        return self._config

    def close(self) -> None:
        """Stop waiting on adapter threads."""
        self._executor.shutdown(wait=False, cancel_futures=True)

    # ----- shared wrapper -------------------------------------------------

    def call(self, tool: str, args: Mapping[str, object] | None = None) -> ToolResult:
        """Run one tool call. Writes exactly one AuditEntry, whatever happens."""
        arguments: Mapping[str, object] = args if args is not None else {}
        started = time.perf_counter()
        result: ToolResult | None = None
        try:
            result = self._run(tool, arguments)
        except Exception:
            logger.exception("Unexpected failure in tool %s", tool)
            result = ToolResult(
                False,
                "error",
                "The server could not complete that call. Try again, then check the server log.",
            )
        finally:
            outcome = result.outcome if result is not None else "error"
            self._audit.record(
                AuditEntry(
                    _now(),
                    tool,
                    _audit_text(arguments, "device"),
                    _audit_point(arguments),
                    outcome=outcome,
                    duration_ms=(time.perf_counter() - started) * 1000.0,
                )
            )
        return result

    def _run(self, tool: str, args: Mapping[str, object]) -> ToolResult:
        verdict = self._guard.check(tool, args)
        if isinstance(verdict, Rejected):
            return ToolResult(False, "rejected", verdict.message)
        handler = self._handlers.get(tool)
        if handler is None:
            return ToolResult(
                False,
                "unknown_tool",
                f"Tool '{_clip(tool)}' is not available. Use one of: {', '.join(TOOL_NAMES)}.",
            )
        try:
            outcome, payload = handler(args)
        except _ToolFailure as failure:
            return ToolResult(False, failure.outcome, failure.message)
        return ToolResult(outcome == "ok", outcome, payload)

    # ----- lookups --------------------------------------------------------

    def _device(self, args: Mapping[str, object]) -> DeviceConfig:
        name = _required_text(args, "device")
        for device in self._config.devices:
            if device.name == name:
                return device
        raise _unknown("device", name, [d.name for d in self._config.devices])

    @staticmethod
    def _point(device: DeviceConfig, name: str) -> PointConfig:
        for point in device.points:
            if point.name == name:
                return point
        raise _unknown(
            "point", name, [p.name for p in device.points], f" on device '{_clip(device.name)}'"
        )

    # ----- adapter calls --------------------------------------------------

    def _with_timeout(self, device: DeviceConfig, action: str, fn: Callable[[], T]) -> T:
        future = self._executor.submit(fn)
        try:
            return future.result(timeout=device.timeout_seconds)
        except TimeoutError:
            future.cancel()
            raise _ToolFailure(
                "timeout",
                f"{_clip(device.name)} did not respond within {device.timeout_seconds:g}s. "
                "Try again or check the device connection.",
            ) from None
        except AdapterReadError as err:
            logger.warning("Adapter %s failed for device %s: %s", action, device.name, err.message)
            raise _ToolFailure("adapter_error", _clip_message(err.message)) from None
        except Exception:
            logger.exception("Adapter %s failed for device %s", action, device.name)
            raise _ToolFailure(
                "adapter_error",
                f"{_clip(device.name)} {action} failed: the adapter reported an error. "
                "Try again, or check the device connection and the server log.",
            ) from None

    def _read_value(self, device: DeviceConfig, point: PointConfig) -> dict[str, JsonValue]:
        raw = self._with_timeout(device, "read", lambda: self._adapter.read(device, point))
        try:
            value: RawValue = round_value(
                apply_scale(decode(point.data_type, raw), point.scale),
                point.data_type,
                point.decimals,
            )
        except ValueError:
            logger.exception("Decode failed for %s/%s", device.name, point.name)
            raise _ToolFailure(
                "adapter_error",
                f"{_clip(device.name)} read failed: data for point '{_clip(point.name)}' "
                f"did not match type {point.data_type.value}. "
                "Check the point's data_type and address in the configuration.",
            ) from None
        return {
            "device": device.name,
            "point": point.name,
            "value": value,
            "unit": point.unit,
            "timestamp": _now(),
        }

    # ----- tool handlers --------------------------------------------------

    def _list_devices(self, args: Mapping[str, object]) -> tuple[str, JsonValue]:
        devices: list[JsonValue] = [
            {"name": d.name, "description": d.description} for d in self._config.devices
        ]
        return "ok", devices

    def _list_points(self, args: Mapping[str, object]) -> tuple[str, JsonValue]:
        device = self._device(args)
        points: list[JsonValue] = [
            {"name": p.name, "data_type": p.data_type.value, "unit": p.unit} for p in device.points
        ]
        return "ok", points

    def _read_point(self, args: Mapping[str, object]) -> tuple[str, JsonValue]:
        device = self._device(args)
        point = self._point(device, _required_text(args, "point"))
        return "ok", self._read_value(device, point)

    def _read_points(self, args: Mapping[str, object]) -> tuple[str, JsonValue]:
        device = self._device(args)
        names = _required_names(args, "points")
        results: list[JsonValue] = []
        outcome = "ok"
        for name in names:
            try:
                results.append(self._read_value(device, self._point(device, name)))
            except _ToolFailure as failure:
                if outcome == "ok":
                    outcome = failure.outcome
                results.append({"point": name, "error": failure.message})
        return outcome, {"device": device.name, "results": results}

    def _device_health(self, args: Mapping[str, object]) -> tuple[str, JsonValue]:
        device = self._device(args)
        status = self._with_timeout(device, "health check", lambda: self._adapter.health(device))
        return "ok", {"device": device.name, "status": str(status.value), "timestamp": _now()}

    # ----- console --------------------------------------------------------

    def build_console(self) -> "FastAPI":
        """Build the web console app over this server. It needs no API key.

        Calls made through the console use ToolServer.call, so each writes one AuditEntry.
        The console module imports this one, so it is imported here, not at the top.
        """
        from seance.console.app import create_app

        return create_app(self)

    # ----- MCP ------------------------------------------------------------

    def build_mcp(self, name: str = "seance") -> MCPServer:
        """Build the MCP server and register the five tools.

        Parameters are typed loosely so that a wrong argument type reaches
        ToolServer.call, which names the argument and writes the audit entry.
        """
        mcp = MCPServer(name)
        text_arg = Annotated[
            object, Field(description="Name of the item.", json_schema_extra={"type": "string"})
        ]
        names_arg = Annotated[
            object,
            Field(
                description="Point names, in the order wanted.",
                json_schema_extra={"type": "array", "items": {"type": "string"}},
            ),
        ]

        def list_devices() -> str:
            return self.call("list_devices", {}).text

        def list_points(device: text_arg) -> str:
            return self.call("list_points", {"device": device}).text

        def read_point(device: text_arg, point: text_arg) -> str:
            return self.call("read_point", {"device": device, "point": point}).text

        def read_points(device: text_arg, points: names_arg) -> str:
            return self.call("read_points", {"device": device, "points": points}).text

        def device_health(device: text_arg) -> str:
            return self.call("device_health", {"device": device}).text

        docs = {
            "list_devices": (list_devices, "List every device with its name and description."),
            "list_points": (list_points, "List the points of one device: name, type and unit."),
            "read_point": (read_point, "Read one point: value, unit and ISO 8601 timestamp."),
            "read_points": (read_points, "Read several points, results in the order requested."),
            "device_health": (device_health, "Report device status and an ISO 8601 timestamp."),
        }
        assert set(docs) == READ_TOOLS
        for tool_name, (fn, description) in docs.items():
            mcp.add_tool(fn, name=tool_name, description=description, structured_output=False)
        return mcp


def build_tool_server(
    config_path: Path,
    adapter: ProtocolAdapter,
    guard: Read_Only_Guard | None = None,
    audit: Audit_Log | None = None,
) -> ToolServer:
    """Start-up sequence: load the Configuration, check the adapter, connect once.

    Raises ConfigError or AdapterRegistrationError before any tool is served.
    """
    config = load_config(config_path)
    check_adapter(adapter)
    adapter.connect()
    return ToolServer(config, adapter, guard, audit)


def serve(
    config_path: Path,
    adapter: ProtocolAdapter,
    guard: Read_Only_Guard | None = None,
    audit: Audit_Log | None = None,
    console_host: str = DEFAULT_CONSOLE_HOST,
    console_port: int = DEFAULT_CONSOLE_PORT,
) -> None:
    """Run the MCP server over stdio and the web console, until stdio stops.

    The console runs in a background thread on console_host:console_port and is
    stopped, then the adapter is closed, when the MCP server returns.
    """
    server = build_tool_server(config_path, adapter, guard, audit)
    console = _start_console(server.build_console(), console_host, console_port)
    try:
        server.build_mcp().run()
    finally:
        _stop_console(console)
        server.close()
        adapter.close()


def _start_console(app: "FastAPI", host: str, port: int) -> "_ConsoleThread":
    import uvicorn

    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    uv_server = uvicorn.Server(config)
    thread = threading.Thread(target=uv_server.run, name="seance-console", daemon=True)
    thread.start()
    return _ConsoleThread(uv_server, thread)


def _stop_console(console: "_ConsoleThread") -> None:
    console.server.should_exit = True
    console.thread.join(timeout=_CONSOLE_STOP_SECONDS)


@dataclass(frozen=True)
class _ConsoleThread:
    server: "uvicorn.Server"
    thread: threading.Thread
