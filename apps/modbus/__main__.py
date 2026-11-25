"""Entry point: ``uv run python -m apps.modbus``.

Starts the Simulator, then the MCP server (stdio) and the web console together.
Standard output carries the MCP protocol, so every log and message goes to
standard error. The app needs no secret and calls nothing beyond its own host.
"""

import logging
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol, TextIO

from apps.modbus.adapter import ModbusAdapter
from apps.modbus.address import AddressError, parse_address
from apps.modbus.simulator import Simulator, SimulatorError
from seance.adapter import ProtocolAdapter
from seance.audit import Audit_Log
from seance.config import ConfigError, load_config
from seance.guard import Read_Only_Guard
from seance.server import serve

ENV_HOST = "SEANCE_MODBUS_HOST"
ENV_PORT = "SEANCE_MODBUS_PORT"
ENV_CONSOLE_HOST = "SEANCE_CONSOLE_HOST"
ENV_CONSOLE_PORT = "SEANCE_CONSOLE_PORT"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5020
DEFAULT_CONSOLE_HOST = "127.0.0.1"
DEFAULT_CONSOLE_PORT = 8080
SIMULATOR_SEED = 1

CONFIG_PATH = Path(__file__).parent / "devices.yaml"

EXIT_OK = 0
EXIT_STARTUP_ERROR = 1


class StartupError(Exception):
    """A start-up problem. The message is the one sentence shown to the user."""


class ServeFunction(Protocol):
    """The shape of ``seance.server.serve``, so tests can replace the stdio loop."""

    def __call__(
        self,
        config_path: Path,
        adapter: ProtocolAdapter,
        guard: Read_Only_Guard | None = None,
        audit: Audit_Log | None = None,
        console_host: str = ...,
        console_port: int = ...,
    ) -> None: ...


def read_port(env: Mapping[str, str], name: str, default: int) -> int:
    """Read a port from the environment. Raise StartupError if it is not 1 to 65535."""
    text = env.get(name)
    if text is None:
        return default
    stripped = text.strip()
    if stripped.isascii() and stripped.isdigit() and 1 <= int(stripped) <= 65535:
        return int(stripped)
    raise StartupError(f"{name} must be a whole number from 1 to 65535, got '{text}'.")


def check_addresses(config_path: Path) -> None:
    """Load the config and parse every point address. Raise on the first problem."""
    config = load_config(config_path)
    for device in config.devices:
        for point in device.points:
            try:
                parse_address(point.address)
            except AddressError as error:
                raise StartupError(
                    f"Device '{device.name}', point '{point.name}': bad address "
                    f"'{point.address}'. {error}"
                ) from None


def _start_simulator(
    factory: Callable[[str, int, int], Simulator], host: str, port: int, port_env: str
) -> Simulator:
    simulator = factory(host, port, SIMULATOR_SEED)
    try:
        simulator.start()
    except SimulatorError as error:
        if "already in use" in str(error):
            raise StartupError(
                f"Port {port} is already in use. Set {port_env} to a free port and try again."
            ) from None
        raise StartupError(str(error)) from None
    return simulator


def main(
    env: Mapping[str, str] | None = None,
    serve_fn: ServeFunction = serve,
    simulator_factory: Callable[[str, int, int], Simulator] = Simulator,
    config_path: Path = CONFIG_PATH,
    stderr: TextIO | None = None,
) -> int:
    """Run the Modbus app until the MCP server stops. Return the process exit code.

    Every message goes to ``stderr`` (default ``sys.stderr``).
    """
    out = stderr if stderr is not None else sys.stderr
    environment = env if env is not None else os.environ
    simulator: Simulator | None = None
    try:
        host = environment.get(ENV_HOST, DEFAULT_HOST)
        port = read_port(environment, ENV_PORT, DEFAULT_PORT)
        console_host = environment.get(ENV_CONSOLE_HOST, DEFAULT_CONSOLE_HOST)
        console_port = read_port(environment, ENV_CONSOLE_PORT, DEFAULT_CONSOLE_PORT)
        simulator = _start_simulator(simulator_factory, host, port, ENV_PORT)
        adapter = ModbusAdapter(simulator.host, simulator.port)
        try:
            check_addresses(config_path)
            # serve() connects the adapter once and closes it when it returns.
            serve_fn(
                config_path,
                adapter,
                console_host=console_host,
                console_port=console_port,
            )
        except BaseException:
            # A failure before or inside serve(). Closing twice is harmless: the
            # Modbus client ignores a close on a closed connection.
            adapter.close()
            raise
    except StartupError as error:
        print(str(error), file=out)
        return EXIT_STARTUP_ERROR
    except ConfigError as error:
        print(str(error), file=out)
        return EXIT_STARTUP_ERROR
    finally:
        if simulator is not None:
            try:
                simulator.stop()
            except SimulatorError as error:
                print(str(error), file=out)
    return EXIT_OK


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    sys.exit(main())
