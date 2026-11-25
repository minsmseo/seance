"""Web console routes.

Every value shown here comes from ToolServer.call, so each console call writes
exactly one Audit_Entry. The console needs no API key.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from seance.guard import READ_TOOLS
from seance.server import JsonValue, ToolResult, ToolServer

AUDIT_LIMIT = 50

_HERE = Path(__file__).parent
_TEMPLATE_DIR = _HERE / "templates"
_STATIC_DIR = _HERE / "static"

_STATUS_BY_OUTCOME: dict[str, int] = {
    "unknown_target": 404,
    "unknown_tool": 404,
    "invalid_argument": 400,
    "rejected": 403,
    "timeout": 504,
    "adapter_error": 502,
}


def _result_body(result: ToolResult) -> dict[str, JsonValue]:
    return {"ok": result.ok, "outcome": result.outcome, "result": result.payload}


def _status_for(result: ToolResult) -> int:
    if result.ok:
        return 200
    return _STATUS_BY_OUTCOME.get(result.outcome, 500)


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _point_rows(server: ToolServer, device_name: str) -> str:
    """Render one table row per point of a device, reading all points in one call."""
    device = next(d for d in server.config.devices if d.name == device_name)
    if not device.points:
        return "<tr><td colspan='5'>No points configured.</td></tr>"
    names = [p.name for p in device.points]
    result = server.call("read_points", {"device": device_name, "points": names})
    readings: dict[str, dict[str, JsonValue]] = {}
    if isinstance(result.payload, dict):
        items = result.payload.get("results")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and isinstance(item.get("point"), str):
                    readings[str(item["point"])] = item
    rows: list[str] = []
    for point in device.points:
        reading = readings.get(point.name)
        if reading is not None and "value" in reading:
            value = _esc(reading["value"])
            timestamp = _esc(reading.get("timestamp", ""))
        elif reading is not None:
            value = _esc(reading.get("error", ""))
            timestamp = ""
        else:
            value = _esc(result.payload if isinstance(result.payload, str) else "")
            timestamp = ""
        link = _esc(f"/points/{quote(device.name, safe='')}/{quote(point.name, safe='')}")
        rows.append(
            f"<tr><td><a href='{link}'>{_esc(point.name)}</a></td>"
            f"<td>{value}</td><td>{_esc(point.unit)}</td><td>{timestamp}</td>"
            f"<td>{_esc(point.data_type.value)}</td></tr>"
        )
    return "".join(rows)


def _index_html(server: ToolServer) -> str:
    sections: list[str] = []
    for device in server.config.devices:
        sections.append(
            f"<article><h3>{_esc(device.name)}</h3><p>{_esc(device.description)}</p>"
            "<table><thead><tr><th>Point</th><th>Value</th><th>Unit</th><th>Timestamp</th>"
            f"<th>Type</th></tr></thead><tbody>{_point_rows(server, device.name)}</tbody>"
            "</table></article>"
        )
    body = "".join(sections) or "<p>No devices are configured.</p>"
    options = "".join(
        f"<option value='{_esc(name)}'>{_esc(name)}</option>" for name in sorted(READ_TOOLS)
    )
    template = (_TEMPLATE_DIR / "index.html").read_text(encoding="utf-8")
    return template.replace("{{DEVICES}}", body).replace("{{TOOL_OPTIONS}}", options)


def create_app(server: ToolServer) -> FastAPI:
    """Build the console app over one ToolServer."""
    app = FastAPI(title="Seance console")
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _index_html(server)

    @app.get("/points/{device}/{point}")
    def point_value(device: str, point: str) -> JSONResponse:
        result = server.call("read_point", {"device": device, "point": point})
        return JSONResponse(_result_body(result), status_code=_status_for(result))

    @app.post("/tools/{tool_name}")
    async def invoke_tool(tool_name: str, request: Request) -> JSONResponse:
        raw = await request.body()
        arguments: dict[str, object] = {}
        if raw.strip():
            try:
                parsed: object = json.loads(raw)
            except ValueError:
                parsed = None
            if not isinstance(parsed, dict):
                return JSONResponse(
                    {
                        "ok": False,
                        "outcome": "invalid_argument",
                        "result": "The request body must be a JSON object of arguments. "
                        "Send {} for a tool with no arguments.",
                    },
                    status_code=400,
                )
            arguments = {str(k): v for k, v in parsed.items()}
        result = await run_in_threadpool(server.call, tool_name, arguments)
        return JSONResponse(_result_body(result), status_code=_status_for(result))

    @app.get("/audit")
    def audit() -> list[dict[str, str | float]]:
        return [
            {
                "timestamp": e.timestamp,
                "tool": e.tool,
                "device": e.device,
                "point": e.point,
                "outcome": e.outcome,
                "duration_ms": e.duration_ms,
            }
            for e in server.audit.recent(AUDIT_LIMIT)
        ]

    return app
