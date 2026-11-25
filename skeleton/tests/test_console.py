"""Route tests for the web console. Uses the Fake_Adapter and TestClient; no network."""

import html
import json
from collections.abc import Callable, Iterator
from contextlib import ExitStack

import pytest
from anyio.from_thread import BlockingPortal
from fastapi.testclient import TestClient

from seance.console.app import AUDIT_LIMIT, create_app
from seance.points import Configuration, DataType, DeviceConfig, PointConfig
from seance.server import ToolServer
from tests.fakes import Fake_Adapter

ODD_NAME = "Line A & B <main>"

CONFIG = Configuration(
    devices=(
        DeviceConfig(
            name="press",
            description="Hydraulic press",
            timeout_seconds=0.2,
            points=(
                PointConfig("temperature", "100", DataType.INT16, "C", 0.1),
                PointConfig("running", "101", DataType.BOOL, "bool"),
                PointConfig(
                    "mode",
                    "102",
                    DataType.UINT16,
                    "state",
                    labels=((100, "up"), (2, "down")),
                    healthy="up",
                ),
            ),
        ),
        DeviceConfig(ODD_NAME, "Odd & <unusual> name", 0.2, ()),
    )
)


MakeClient = Callable[..., tuple[TestClient, ToolServer, Fake_Adapter]]


@pytest.fixture
def make(session_portal: BlockingPortal) -> Iterator[MakeClient]:
    """Build clients that share the session portal, so the whole run uses one event loop.

    ``with TestClient(...)`` would open a new portal (a new event loop) per test. The
    console app has no lifespan handlers, so attaching the shared portal is enough.
    Each test still gets a fresh ToolServer and audit log.
    """
    with ExitStack() as stack:

        def build(
            adapter: Fake_Adapter | None = None,
        ) -> tuple[TestClient, ToolServer, Fake_Adapter]:
            fake = adapter if adapter is not None else Fake_Adapter(data=b"\x00\x64")
            server = ToolServer(CONFIG, fake)
            client = TestClient(create_app(server))
            client.portal = session_portal
            stack.callback(client.close)
            return client, server, fake

        yield build


def test_index_lists_devices_and_points_with_live_values(make: MakeClient) -> None:
    client, server, _ = make()
    config = client.get("/config").json()
    by_name = {d["name"]: d for d in config["devices"]}
    assert set(by_name) == {"press", ODD_NAME}
    assert by_name["press"]["description"] == "Hydraulic press"
    assert {"temperature", "running"} <= {p["name"] for p in by_name["press"]["points"]}
    reply = client.post(
        "/tools/read_points", json={"device": "press", "points": ["temperature"]}
    ).json()
    assert reply["ok"] is True
    assert reply["result"]["results"][0]["value"] == pytest.approx(10.0)  # 100 * 0.1
    server.close()


def test_index_keeps_device_names_readable_after_escaping(make: MakeClient) -> None:
    client, server, _ = make()
    raw = client.get("/").text
    assert ODD_NAME not in raw
    assert html.escape(ODD_NAME) not in raw
    config = client.get("/config").json()
    names = [d["name"] for d in config["devices"]]
    descriptions = [d["description"] for d in config["devices"]]
    assert ODD_NAME in names
    assert "Odd & <unusual> name" in descriptions
    server.close()


def test_index_shows_adapter_error_sentence_unchanged(make: MakeClient) -> None:
    client, server, _ = make(Fake_Adapter(error=RuntimeError("boom")))
    body = {"device": "press", "points": ["temperature"]}
    response = client.post("/tools/read_points", json=body)
    text = response.text
    expected = (
        "press read failed: the adapter reported an error. "
        "Try again, or check the device connection and the server log."
    )
    assert expected in json.dumps(response.json()["result"])
    assert "boom" not in text
    assert "Traceback" not in text
    server.close()


def test_config_route_hides_decoding_details_and_reports_healthy(make: MakeClient) -> None:
    client, server, _ = make()
    config = client.get("/config").json()
    press = next(d for d in config["devices"] if d["name"] == "press")
    points = {p["name"]: p for p in press["points"]}
    assert points["temperature"] == {"name": "temperature", "unit": "C", "healthy": None}
    assert points["mode"] == {"name": "mode", "unit": "state", "healthy": "up"}
    for banned in ("address", "data_type", "scale", "decimals", "labels"):
        assert banned not in json.dumps(config)
    server.close()


def test_config_route_lists_the_five_read_tools(make: MakeClient) -> None:
    client, server, _ = make()
    assert sorted(client.get("/config").json()["tools"]) == [
        "device_health",
        "list_devices",
        "list_points",
        "read_point",
        "read_points",
    ]
    server.close()


def test_point_route_returns_live_value(make: MakeClient) -> None:
    client, server, _ = make()
    response = client.get("/points/press/temperature")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["result"]["value"] == pytest.approx(10.0)
    assert body["result"]["unit"] == "C"
    assert isinstance(body["result"]["timestamp"], str)
    server.close()


def test_point_route_unknown_point_returns_sentence_unchanged(make: MakeClient) -> None:
    client, server, _ = make()
    response = client.get("/points/press/temperatur")
    assert response.status_code == 404
    body = response.json()
    assert body["ok"] is False
    assert (
        body["result"] == server.call("read_point", {"device": "press", "point": "temperatur"}).text
    )
    assert "Unknown point 'temperatur'" in body["result"]
    server.close()


def test_point_route_handles_device_name_with_special_characters(make: MakeClient) -> None:
    client, server, _ = make()
    response = client.get("/points/Line%20A%20%26%20B%20%3Cmain%3E/x")
    assert response.status_code == 404
    assert f"on device '{ODD_NAME}'" in response.json()["result"]
    server.close()


def test_tool_invocation_returns_raw_result(make: MakeClient) -> None:
    client, server, _ = make()
    response = client.post("/tools/list_devices", json={})
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "outcome": "ok",
        "result": [
            {"name": "press", "description": "Hydraulic press"},
            {"name": ODD_NAME, "description": "Odd & <unusual> name"},
        ],
    }
    response = client.post("/tools/read_point", json={"device": "press", "point": "temperature"})
    assert response.json()["result"]["unit"] == "C"
    server.close()


def test_tool_invocation_errors_are_plain_sentences(make: MakeClient) -> None:
    client, server, _ = make()
    unknown = client.post("/tools/delete_everything", json={})
    assert unknown.status_code == 403
    assert "read-only" in unknown.json()["result"]
    bad_body = client.post("/tools/list_devices", content=b"[1, 2]")
    assert bad_body.status_code == 400
    assert "JSON object" in bad_body.json()["result"]
    missing = client.post("/tools/list_points", json={})
    assert missing.status_code == 400
    assert "'device'" in missing.json()["result"]
    server.close()


def test_console_does_not_forward_write_requests_to_the_adapter(make: MakeClient) -> None:
    client, server, fake = make()
    response = client.post("/tools/write_point", json={"device": "press", "value": 1})
    assert response.status_code == 403
    assert "read-only" in response.json()["result"]
    assert fake.call_count == 0
    server.close()


def test_audit_is_empty_at_start(make: MakeClient) -> None:
    client, server, _ = make()
    assert client.get("/audit").json() == []
    server.close()


def test_each_console_call_writes_one_audit_entry(make: MakeClient) -> None:
    client, server, _ = make()
    client.get("/points/press/temperature")
    assert len(server.audit.recent(100)) == 1
    client.post("/tools/list_devices", json={})
    client.post("/tools/nonexistent", json={})
    client.get("/points/press/nope")
    entries = client.get("/audit").json()
    assert [e["tool"] for e in entries] == [
        "read_point",
        "nonexistent",
        "list_devices",
        "read_point",
    ]
    assert [e["outcome"] for e in entries] == ["unknown_target", "rejected", "ok", "ok"]
    assert entries[0]["device"] == "press"
    assert entries[0]["point"] == "nope"
    assert {"timestamp", "tool", "device", "point", "outcome", "duration_ms"} <= set(entries[0])
    server.close()


def test_index_writes_one_audit_entry_per_device_with_points(make: MakeClient) -> None:
    client, server, fake = make()
    client.get("/")
    client.get("/config")
    assert server.audit.recent(100) == []
    assert fake.call_count == 0
    server.close()


def test_audit_view_is_capped_at_50_newest_first(make: MakeClient) -> None:
    client, server, _ = make()
    total = AUDIT_LIMIT + 10
    for i in range(total):
        server.call("list_points", {"device": f"d{i}"})
    entries = client.get("/audit").json()
    assert AUDIT_LIMIT == 50
    assert len(entries) == 50
    assert [e["device"] for e in entries] == [f"d{i}" for i in range(total - 1, total - 51, -1)]
    assert len(server.audit.recent(1000)) == total
    server.close()
