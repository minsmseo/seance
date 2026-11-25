"""Unit tests for the SNMP Entry_Point (apps/snmp/__main__.py).

The MCP stdio loop, the adapter and the Simulator are replaced by fakes that
record events, so no test touches the network and no test creates an event loop.
The busy-port case uses a fake Simulator that raises the same SimulatorError
text the real one raises when the UDP port is taken.
"""

from __future__ import annotations

import importlib
import io
from pathlib import Path

import pytest

from apps.snmp.simulator import Simulator, SimulatorError
from seance.config import ConfigError

entry = importlib.import_module("apps.snmp.__main__")

DEVICES_YAML = Path(entry.__file__).parent / "devices.yaml"


class FakeSimulator:
    """Records start and stop. Never opens a socket."""

    def __init__(
        self,
        events: list[str],
        host: str,
        port: int,
        seed: int,
        start_error: str | None = None,
    ) -> None:
        self.events = events
        self.host = host
        self.port = port
        self.seed = seed
        self.start_error = start_error

    def start(self) -> None:
        if self.start_error is not None:
            raise SimulatorError(self.start_error)
        self.events.append("simulator.start")

    def stop(self) -> None:
        self.events.append("simulator.stop")


class FakeAdapter:
    """Stands in for SnmpAdapter. Records connect and close."""

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
        self.start_error: str | None = None

    def simulator_factory(self, host: str, port: int, seed: int) -> Simulator:
        self.sim_args = (host, port, seed)
        return FakeSimulator(  # type: ignore[return-value]
            self.events, host, port, seed, self.start_error
        )

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

    monkeypatch.setattr(entry, "SnmpAdapter", make_adapter)
    return h


def write_config(tmp_path: Path, address: str) -> Path:
    config = tmp_path / "devices.yaml"
    config.write_text(
        "devices:\n"
        "  - name: core_switch\n"
        "    description: Test switch\n"
        "    points:\n"
        "      - name: uptime\n"
        f'        address: "{address}"\n'
        "        data_type: uint32\n"
        "        unit: s\n",
        encoding="utf-8",
    )
    return config


# --- Environment variables (7.2 to 7.5) ----------------------------------------------------


def test_defaults_when_no_variable_is_set(harness: Harness) -> None:
    assert harness.run({}) == 0
    assert harness.sim_args == ("127.0.0.1", 1161, entry.SIMULATOR_SEED)
    assert harness.adapter_args == ("127.0.0.1", 1161)
    assert harness.serve_kwargs == {"console_host": "127.0.0.1", "console_port": 8080}


def test_all_four_variables_override_the_defaults(harness: Harness) -> None:
    env = {
        "SEANCE_SNMP_HOST": "127.0.0.2",
        "SEANCE_SNMP_PORT": "11161",
        "SEANCE_CONSOLE_HOST": "127.0.0.3",
        "SEANCE_CONSOLE_PORT": "18080",
    }
    assert harness.run(env) == 0
    assert harness.sim_args == ("127.0.0.2", 11161, entry.SIMULATOR_SEED)
    assert harness.adapter_args == ("127.0.0.2", 11161)
    assert harness.serve_kwargs == {"console_host": "127.0.0.3", "console_port": 18080}


# --- Invalid ports (7.7) -------------------------------------------------------------------


@pytest.mark.parametrize("variable", ["SEANCE_SNMP_PORT", "SEANCE_CONSOLE_PORT"])
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


def test_port_in_use_gives_one_message_naming_port_and_variable(
    harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    harness.start_error = "Port 4321 is already in use. Try another port."
    assert harness.run({"SEANCE_SNMP_PORT": "4321"}) == 1
    lines = harness.stderr.getvalue().splitlines()
    assert len(lines) == 1
    assert "4321" in lines[0]
    assert "SEANCE_SNMP_PORT" in lines[0]
    assert "serve" not in harness.events
    assert capsys.readouterr().out == ""


# --- Bad points in the config (4.13, 4.14) -------------------------------------------------


def test_invalid_address_names_device_point_and_reason(
    harness: Harness, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config(tmp_path, "core_switch:1.3.6.01.2")
    assert harness.run({}, config_path=config) == 1
    lines = harness.stderr.getvalue().splitlines()
    assert len(lines) == 1
    assert "core_switch" in lines[0]
    assert "uptime" in lines[0]
    assert "leading zeros" in lines[0]
    assert "serve" not in harness.events
    assert harness.events[-1] == "simulator.stop"
    assert capsys.readouterr().out == ""


def test_community_that_differs_from_device_name_names_device_point_and_reason(
    harness: Harness, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config(tmp_path, "other:1.3.6.1.2.1.1.3.0")
    assert harness.run({}, config_path=config) == 1
    lines = harness.stderr.getvalue().splitlines()
    assert len(lines) == 1
    assert "core_switch" in lines[0]
    assert "uptime" in lines[0]
    assert "other" in lines[0]
    assert "must equal" in lines[0]
    assert "serve" not in harness.events
    assert harness.events[-1] == "simulator.stop"
    assert capsys.readouterr().out == ""


def test_shipped_config_passes_the_point_check() -> None:
    entry.check_points(DEVICES_YAML)


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


def test_shutdown_order_serve_then_adapter_close_then_simulator_stop(
    harness: Harness,
) -> None:
    assert harness.run({}) == 0
    events = harness.events
    assert events.count("adapter.connect") == 1
    assert events.count("adapter.close") == 1
    assert events.count("simulator.stop") == 1
    assert (
        events.index("serve")
        < events.index("adapter.connect")
        < events.index("adapter.close")
        < events.index("simulator.stop")
    )


def test_adapter_and_simulator_are_closed_when_serve_raises(harness: Harness) -> None:
    harness.serve_error = ConfigError("devices.yaml", "x", "name", "is required")
    assert harness.run({}) == 1
    events = harness.events
    # serve closes in its finally block, then main closes again (harmless).
    assert events.count("adapter.close") == 2
    assert events.count("simulator.stop") == 1
    assert events.index("serve") < events.index("adapter.close")
    assert events[-1] == "simulator.stop"


def test_adapter_is_closed_when_the_point_check_fails(harness: Harness, tmp_path: Path) -> None:
    config = write_config(tmp_path, "other:1.3.6.1.2.1.1.3.0")
    assert harness.run({}, config_path=config) == 1
    events = harness.events
    assert "adapter.connect" not in events
    assert events.count("adapter.close") == 1
    assert (
        events.index("adapter.create")
        < events.index("adapter.close")
        < events.index("simulator.stop")
    )


# --- Standard output (7.9) -----------------------------------------------------------------


def test_nothing_is_written_to_standard_output(
    harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    harness.run({})
    harness.run({"SEANCE_SNMP_PORT": "0"})
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
