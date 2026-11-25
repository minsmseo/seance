"""Unit tests for the Modbus Entry_Point (apps/modbus/__main__.py).

The MCP stdio loop and the adapter are replaced by fakes
that record events, so no test touches the network. The one exception is the
port-in-use test: it binds a real localhost socket on an OS-assigned port and
starts the real Simulator on that port, which fails before any event loop exists.
"""

from __future__ import annotations

import importlib
import io
import socket
from collections.abc import Iterator
from pathlib import Path

import pytest

from apps.modbus.simulator import Simulator
from seance.config import ConfigError

entry = importlib.import_module("apps.modbus.__main__")

DEVICES_YAML = Path(entry.__file__).parent / "devices.yaml"


class FakeSimulator:
    """Records start and stop. Never opens a socket."""

    def __init__(self, events: list[str], host: str, port: int, seed: int) -> None:
        self.events = events
        self.host = host
        self.port = port
        self.seed = seed

    def start(self) -> None:
        self.events.append("simulator.start")

    def stop(self) -> None:
        self.events.append("simulator.stop")


class FakeAdapter:
    """Stands in for ModbusAdapter. Records close."""

    def __init__(self, events: list[str], host: str, port: int) -> None:
        self.events = events
        self.host = host
        self.port = port

    def connect(self) -> None:
        self.events.append("adapter.connect")

    def close(self) -> None:
        self.events.append("adapter.close")


class Harness:
    """Collects events and keyword arguments across fakes for one main() call."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.sim_args: tuple[str, int, int] | None = None
        self.adapter_args: tuple[str, int] | None = None
        self.serve_kwargs: dict[str, object] = {}
        self.stderr = io.StringIO()
        self.serve_error: Exception | None = None

    def simulator_factory(self, host: str, port: int, seed: int) -> Simulator:
        self.sim_args = (host, port, seed)
        return FakeSimulator(self.events, host, port, seed)  # type: ignore[return-value]

    def serve_fn(self, config_path: Path, adapter: object, **kwargs: object) -> None:
        self.events.append("serve")
        self.serve_kwargs = dict(kwargs)
        # Like the real serve: connect once, and close the adapter when it returns.
        adapter.connect()  # type: ignore[attr-defined]
        try:
            if self.serve_error is not None:
                raise self.serve_error
        finally:
            adapter.close()  # type: ignore[attr-defined]

    def run(self, env: dict[str, str], config_path: Path = DEVICES_YAML) -> int:
        return entry.main(
            env=env,
            serve_fn=self.serve_fn,
            simulator_factory=self.simulator_factory,
            config_path=config_path,
            stderr=self.stderr,
        )


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    h = Harness()

    def make_adapter(host: str, port: int) -> FakeAdapter:
        h.adapter_args = (host, port)
        h.events.append("adapter.create")
        return FakeAdapter(h.events, host, port)

    monkeypatch.setattr(entry, "ModbusAdapter", make_adapter)
    return h


# --- Environment variables (7.2 to 7.5) ----------------------------------------------------


def test_defaults_when_no_variable_is_set(harness: Harness) -> None:
    assert harness.run({}) == 0
    assert harness.sim_args == ("127.0.0.1", 5020, entry.SIMULATOR_SEED)
    assert harness.adapter_args == ("127.0.0.1", 5020)
    assert harness.serve_kwargs == {"console_host": "127.0.0.1", "console_port": 8080}


def test_all_four_variables_override_the_defaults(harness: Harness) -> None:
    env = {
        "SEANCE_MODBUS_HOST": "127.0.0.2",
        "SEANCE_MODBUS_PORT": "15020",
        "SEANCE_CONSOLE_HOST": "127.0.0.3",
        "SEANCE_CONSOLE_PORT": "18080",
    }
    assert harness.run(env) == 0
    assert harness.sim_args == ("127.0.0.2", 15020, entry.SIMULATOR_SEED)
    assert harness.serve_kwargs == {"console_host": "127.0.0.3", "console_port": 18080}


# --- Invalid ports (7.7) -------------------------------------------------------------------


@pytest.mark.parametrize("variable", ["SEANCE_MODBUS_PORT", "SEANCE_CONSOLE_PORT"])
@pytest.mark.parametrize("bad", ["abc", "0", "65536", "-1", "", "80.5"])
def test_invalid_port_gives_one_message_naming_variable_and_range(
    harness: Harness, capsys: pytest.CaptureFixture[str], variable: str, bad: str
) -> None:
    assert harness.run({variable: bad}) == 1
    lines = harness.stderr.getvalue().splitlines()
    assert len(lines) == 1
    assert variable in lines[0]
    assert "1 to 65535" in lines[0]
    assert "serve" not in harness.events
    assert "simulator.start" not in harness.events
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("good", ["1", "65535"])
def test_port_range_edges_are_accepted(harness: Harness, good: str) -> None:
    assert harness.run({"SEANCE_CONSOLE_PORT": good}) == 0
    assert harness.serve_kwargs["console_port"] == int(good)


# --- Port in use (7.8) ---------------------------------------------------------------------


@pytest.fixture
def busy_port() -> Iterator[int]:
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    try:
        yield int(blocker.getsockname()[1])
    finally:
        blocker.close()


def test_port_in_use_gives_one_message_naming_port_and_variable(
    busy_port: int, capsys: pytest.CaptureFixture[str]
) -> None:
    serve_calls: list[str] = []

    def serve_fn(config_path: Path, adapter: object, **kwargs: object) -> None:
        serve_calls.append("serve")

    stderr = io.StringIO()
    code = entry.main(
        env={"SEANCE_MODBUS_HOST": "127.0.0.1", "SEANCE_MODBUS_PORT": str(busy_port)},
        serve_fn=serve_fn,
        simulator_factory=Simulator,
        config_path=DEVICES_YAML,
        stderr=stderr,
    )
    assert code == 1
    lines = stderr.getvalue().splitlines()
    assert len(lines) == 1
    assert str(busy_port) in lines[0]
    assert "SEANCE_MODBUS_PORT" in lines[0]
    assert serve_calls == []
    assert capsys.readouterr().out == ""


# --- Invalid address in the config (4.9) ---------------------------------------------------


def test_invalid_address_names_device_point_and_reason(
    harness: Harness, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "devices.yaml"
    config.write_text(
        "devices:\n"
        "  - name: boiler\n"
        "    description: Test boiler\n"
        "    points:\n"
        "      - name: pressure\n"
        '        address: "1:holding:99999"\n'
        "        data_type: uint16\n"
        "        unit: kPa\n",
        encoding="utf-8",
    )
    assert harness.run({}, config_path=config) == 1
    lines = harness.stderr.getvalue().splitlines()
    assert len(lines) == 1
    assert "boiler" in lines[0]
    assert "pressure" in lines[0]
    assert "offset" in lines[0]
    assert "serve" not in harness.events
    assert harness.events[-1] == "simulator.stop"
    assert capsys.readouterr().out == ""


def test_config_error_from_serve_is_one_message_and_stops_the_simulator(
    harness: Harness,
) -> None:
    harness.serve_error = ConfigError("devices.yaml", "x", "name", "is required")
    assert harness.run({}) == 1
    assert harness.stderr.getvalue().strip() == str(harness.serve_error)
    assert harness.events[-1] == "simulator.stop"


# --- Startup and shutdown order (7.1, 7.10) ------------------------------------------------


def test_startup_order_simulator_then_adapter_then_serve(harness: Harness) -> None:
    assert harness.run({}) == 0
    events = harness.events
    assert events.index("simulator.start") < events.index("adapter.create")
    assert events.index("adapter.create") < events.index("serve")
    assert events.index("simulator.start") < events.index("serve")


def test_simulator_stops_after_serve_returns(harness: Harness) -> None:
    assert harness.run({}) == 0
    assert harness.events[-2:] == ["serve", "simulator.stop"]
    assert harness.events.count("simulator.stop") == 1


def test_simulator_stops_when_serve_raises_a_config_error_only_once(harness: Harness) -> None:
    harness.serve_error = ConfigError("devices.yaml", "x", "name", "is required")
    harness.run({})
    assert harness.events.count("simulator.stop") == 1


# --- Adapter connect and close -------------------------------------------------------------


def test_adapter_connect_is_called_exactly_once_on_success(harness: Harness) -> None:
    assert harness.run({}) == 0
    assert harness.events.count("adapter.connect") == 1


def test_adapter_is_closed_when_serve_raises(harness: Harness) -> None:
    harness.serve_error = ConfigError("devices.yaml", "x", "name", "is required")
    assert harness.run({}) == 1
    assert "adapter.close" in harness.events
    assert harness.events.count("simulator.stop") == 1
    assert harness.events[-1] == "simulator.stop"


def test_adapter_is_closed_when_the_address_check_fails(harness: Harness, tmp_path: Path) -> None:
    config = tmp_path / "devices.yaml"
    config.write_text(
        "devices:\n"
        "  - name: boiler\n"
        "    description: Test boiler\n"
        "    points:\n"
        "      - name: pressure\n"
        '        address: "1:holding:99999"\n'
        "        data_type: uint16\n"
        "        unit: kPa\n",
        encoding="utf-8",
    )
    assert harness.run({}, config_path=config) == 1
    assert harness.events.count("adapter.close") == 1
    assert "adapter.connect" not in harness.events


def test_adapter_is_not_closed_again_after_a_successful_serve(harness: Harness) -> None:
    assert harness.run({}) == 0
    assert harness.events.count("adapter.close") == 1


# --- Standard output (7.9) -----------------------------------------------------------------


def test_nothing_is_written_to_standard_output(
    harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    harness.run({})
    harness.run({"SEANCE_MODBUS_PORT": "0"})
    assert capsys.readouterr().out == ""


def test_default_stream_is_standard_error(
    harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    code = entry.main(
        env={"SEANCE_CONSOLE_PORT": "nope"},
        serve_fn=harness.serve_fn,
        simulator_factory=harness.simulator_factory,
        config_path=DEVICES_YAML,
    )
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "SEANCE_CONSOLE_PORT" in captured.err
