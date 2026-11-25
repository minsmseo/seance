"""Property tests for the audit log driven through the Tool_Server (Properties 10 and 11)."""

from hypothesis import given, settings
from hypothesis import strategies as st

from seance.audit import Audit_Log, AuditEntry
from seance.points import Configuration, DataType, DeviceConfig, PointConfig
from seance.server import TOOL_NAMES, ToolServer
from tests.fakes import Fake_Adapter

SETTINGS = settings(max_examples=100, deadline=None)

CONFIG = Configuration(
    (
        DeviceConfig(
            "press",
            "Hydraulic press",
            0.02,
            (PointConfig("temperature", "1", DataType.INT16, "C"),),
        ),
        DeviceConfig("lathe", "Metal lathe", 0.02, ()),
    )
)

TEXT = st.text(max_size=20)
DEVICE_VALUES = st.one_of(st.sampled_from(["press", "lathe"]), TEXT, st.integers(), st.none())
POINT_VALUES = st.one_of(st.sampled_from(["temperature"]), TEXT, st.integers(), st.none())
TOOLS = st.one_of(st.sampled_from(TOOL_NAMES), TEXT)


@st.composite
def calls(draw: st.DrawFn) -> tuple[str, dict[str, object]]:
    tool = draw(TOOLS)
    args: dict[str, object] = {}
    if draw(st.booleans()):
        args["device"] = draw(DEVICE_VALUES)
    if draw(st.booleans()):
        args["point"] = draw(POINT_VALUES)
    return tool, args


def make_server(mode: str) -> tuple[ToolServer, Fake_Adapter]:
    if mode == "error":
        adapter = Fake_Adapter(error=RuntimeError("boom"))
    elif mode == "slow":
        adapter = Fake_Adapter(data=b"\x00\x01", delay=0.06)
    else:
        adapter = Fake_Adapter(data=b"\x00\x01")
    return ToolServer(CONFIG, adapter), adapter


# Feature: skeleton-core, Property 10: For any sequence of tool calls, the number of audit
# entries equals the number of calls.
@SETTINGS
@given(
    sequence=st.lists(calls(), max_size=10),
    mode=st.sampled_from(["ok", "ok", "error", "slow"]),
)
def test_property_10_audit_entry_count_matches_call_count(
    sequence: list[tuple[str, dict[str, object]]], mode: str
) -> None:
    """**Validates: Requirements 6.1, 6.2, 6.3**"""
    server, _ = make_server(mode)
    try:
        for tool, args in sequence:
            server.call(tool, args)
    finally:
        server.close()
    entries = server.audit.recent(len(sequence) + 10)
    assert len(entries) == len(sequence)
    assert [e.tool for e in reversed(entries)] == [tool for tool, _ in sequence]


# Feature: skeleton-core, Property 11: For any tool call, the audit entry stores the
# device/point when named and an empty string otherwise.
@SETTINGS
@given(
    tool=TOOLS.filter(lambda t: t != "read_points"),
    call=calls(),
)
def test_property_11_audit_entries_record_supplied_fields(
    tool: str, call: tuple[str, dict[str, object]]
) -> None:
    """**Validates: Requirements 6.4, 6.5**"""
    _, args = call
    server, _ = make_server("ok")
    try:
        server.call(tool, args)
    finally:
        server.close()
    (entry,) = server.audit.recent(5)
    device = args.get("device")
    point = args.get("point")
    assert entry.tool == tool
    assert entry.device == (device if isinstance(device, str) else "")
    assert entry.point == (point if isinstance(point, str) else "")
    assert entry.outcome != ""
    assert entry.duration_ms >= 0


# Feature: console-redesign, Property 3: the audit view is never longer than n or the log,
# and is newest first.
@SETTINGS
@given(
    tools=st.lists(TEXT, max_size=30),
    n=st.integers(min_value=-5, max_value=40),
)
def test_recent_never_exceeds_n_or_total_and_is_newest_first(tools: list[str], n: int) -> None:
    """**Validates: Requirements 9.1**"""
    log = Audit_Log()
    entries = [AuditEntry("2025-01-01T00:00:00Z", f"{i}:{t}") for i, t in enumerate(tools)]
    for entry in entries:
        log.record(entry)
    view = log.recent(n)
    assert len(view) <= max(n, 0)
    assert len(view) <= len(entries)
    assert len(view) == min(max(n, 0), len(entries))
    assert view == list(reversed(entries))[: len(view)]
