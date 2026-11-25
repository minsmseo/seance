"""Web console routes.

Every value shown here comes from ToolServer.call, so each console call writes
exactly one Audit_Entry. The console needs no API key.
"""

from __future__ import annotations

import json
from pathlib import Path

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


def _index_html() -> str:
    return (_TEMPLATE_DIR / "index.html").read_text(encoding="utf-8")


def _config_body(server: ToolServer) -> dict[str, JsonValue]:
    """Describe devices and points for the page. Exposes no addresses or decoding details."""
    devices: list[JsonValue] = [
        {
            "name": device.name,
            "description": device.description,
            "points": [
                {"name": p.name, "unit": p.unit, "healthy": p.healthy} for p in device.points
            ],
        }
        for device in server.config.devices
    ]
    tools: list[JsonValue] = list(sorted(READ_TOOLS))
    return {"devices": devices, "tools": tools}


def create_app(server: ToolServer) -> FastAPI:
    """Build the console app over one ToolServer."""
    app = FastAPI(title="Seance console")
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _index_html()

    @app.get("/config")
    def config() -> JSONResponse:
        return JSONResponse(_config_body(server))

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
