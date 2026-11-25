"""Design-rule tests for the web console: page structure, /config and the served assets.

Uses the Fake_Adapter and the shared session_portal fixture; no network, no new event loop.
"""

import re
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path

import pytest
from anyio.from_thread import BlockingPortal
from fastapi.testclient import TestClient

from seance.config import load_config
from seance.console.app import create_app
from seance.points import Configuration, DataType, DeviceConfig, PointConfig
from seance.server import ToolServer
from tests.fakes import Fake_Adapter

CONSOLE_DIR = Path(__file__).resolve().parents[1] / "seance" / "console"
STATIC_DIR = CONSOLE_DIR / "static"


def load_css() -> str:
    return (STATIC_DIR / "console.css").read_text(encoding="utf-8")


def load_js() -> str:
    return (STATIC_DIR / "console.js").read_text(encoding="utf-8")


def make_device(name: str, point_count: int = 1) -> DeviceConfig:
    points = tuple(
        PointConfig(f"p{i}", str(100 + i), DataType.INT16, "C", 0.1) for i in range(point_count)
    )
    return DeviceConfig(name, f"{name} description", 0.2, points)


def make_config(device_count: int) -> Configuration:
    return Configuration(devices=tuple(make_device(f"dev{i}", i + 1) for i in range(device_count)))


MakeClient = Callable[[Configuration], TestClient]


@pytest.fixture
def make_client(session_portal: BlockingPortal) -> Iterator[MakeClient]:
    """Build clients that share the session portal, so the run uses one event loop."""
    with ExitStack() as stack:

        def build(config: Configuration) -> TestClient:
            server = ToolServer(config, Fake_Adapter(data=b"\x00\x64"))
            client = TestClient(create_app(server))
            client.portal = session_portal
            stack.callback(server.close)
            stack.callback(client.close)
            return client

        yield build


@pytest.fixture
def shell(make_client: MakeClient) -> str:
    response = make_client(make_config(1)).get("/")
    assert response.status_code == 200
    return response.text


def test_shell_has_regions_in_document_order(shell: str) -> None:
    markers = [
        '<header class="header"',
        'id="summary"',
        'id="devices"',
        'id="tool-panel"',
        'id="ledger"',
    ]
    positions = [shell.index(marker) for marker in markers]
    assert positions == sorted(positions)
    assert len(set(positions)) == len(markers)


def test_shell_devices_container_is_empty(shell: str) -> None:
    assert '<div id="devices"></div>' in shell


def test_console_js_fetches_config_and_builds_one_section_per_device() -> None:
    script = load_js()
    assert 'fetch("/config")' in script
    body = script.split("function renderDevices(", 1)[1]
    loop = body.split("for (const device of config.devices) {", 1)[1]
    assert 'document.createElement("section")' in loop.split("\n  }\n", 1)[0]


@pytest.mark.parametrize("device_count", [0, 1, 3])
def test_config_returns_one_entry_per_device(make_client: MakeClient, device_count: int) -> None:
    config = make_config(device_count)
    payload = make_client(config).get("/config").json()
    assert [d["name"] for d in payload["devices"]] == [d.name for d in config.devices]
    for entry, device in zip(payload["devices"], config.devices, strict=True):
        assert [p["name"] for p in entry["points"]] == [p.name for p in device.points]


def test_config_entry_count_follows_configuration_with_title(make_client: MakeClient) -> None:
    config = replace(make_config(2), title="Line")
    payload = make_client(config).get("/config").json()
    assert len(payload["devices"]) == 2
    assert payload["title"] == "Line"


# ---------------------------------------------------------------------------
# CSS rule tests (steering: design.md)
# ---------------------------------------------------------------------------

STEERING_TOKENS = {
    "--ground": "#0E0C0A",
    "--panel": "#17130F",
    "--ink": "#F4EDE1",
    "--mute": "#B3A592",
    "--line": "#2E2720",
    "--line-strong": "#5A4E40",
    "--alert": "#F08A24",
    "--alert-ink": "#FFB45C",
    "--alert-ground": "#2B1806",
}

COLOR_PROPERTIES = {
    "color",
    "background",
    "background-color",
    "border",
    "border-top",
    "border-right",
    "border-bottom",
    "border-left",
    "border-color",
    "outline",
    "outline-color",
    "fill",
    "stroke",
    "caret-color",
    "accent-color",
    "text-decoration-color",
}

# Words that may appear in colour properties and are not named colours.
NON_COLOR_WORDS = {
    "transparent",
    "currentcolor",
    "inherit",
    "initial",
    "unset",
    "none",
    "solid",
    "dashed",
    "dotted",
    "double",
    "thin",
    "medium",
    "thick",
    "auto",
    "no-repeat",
    "repeat",
    "px",
}

NAMED_COLORS = {
    "aliceblue", "antiquewhite", "aqua", "aquamarine", "azure", "beige", "bisque", "black",
    "blanchedalmond", "blue", "blueviolet", "brown", "burlywood", "cadetblue", "chartreuse",
    "chocolate", "coral", "cornflowerblue", "cornsilk", "crimson", "cyan", "darkblue",
    "darkcyan", "darkgoldenrod", "darkgray", "darkgreen", "darkgrey", "darkkhaki",
    "darkmagenta", "darkolivegreen", "darkorange", "darkorchid", "darkred", "darksalmon",
    "darkseagreen", "darkslateblue", "darkslategray", "darkslategrey", "darkturquoise",
    "darkviolet", "deeppink", "deepskyblue", "dimgray", "dimgrey", "dodgerblue", "firebrick",
    "floralwhite", "forestgreen", "fuchsia", "gainsboro", "ghostwhite", "gold", "goldenrod",
    "gray", "green", "greenyellow", "grey", "honeydew", "hotpink", "indianred", "indigo",
    "ivory", "khaki", "lavender", "lavenderblush", "lawngreen", "lemonchiffon", "lightblue",
    "lightcoral", "lightcyan", "lightgoldenrodyellow", "lightgray", "lightgreen", "lightgrey",
    "lightpink", "lightsalmon", "lightseagreen", "lightskyblue", "lightslategray",
    "lightslategrey", "lightsteelblue", "lightyellow", "lime", "limegreen", "linen",
    "magenta", "maroon", "mediumaquamarine", "mediumblue", "mediumorchid", "mediumpurple",
    "mediumseagreen", "mediumslateblue", "mediumspringgreen", "mediumturquoise",
    "mediumvioletred", "midnightblue", "mintcream", "mistyrose", "moccasin", "navajowhite",
    "navy", "oldlace", "olive", "olivedrab", "orange", "orangered", "orchid", "palegoldenrod",
    "palegreen", "paleturquoise", "palevioletred", "papayawhip", "peachpuff", "peru", "pink",
    "plum", "powderblue", "purple", "rebeccapurple", "red", "rosybrown", "royalblue",
    "saddlebrown", "salmon", "sandybrown", "seagreen", "seashell", "sienna", "silver",
    "skyblue", "slateblue", "slategray", "slategrey", "snow", "springgreen", "steelblue",
    "tan", "teal", "thistle", "tomato", "turquoise", "violet", "wheat", "white",
    "whitesmoke", "yellow", "yellowgreen",
}  # fmt: skip

GENERIC_FAMILIES = {
    "serif",
    "sans-serif",
    "monospace",
    "cursive",
    "fantasy",
    "system-ui",
    "ui-monospace",
    "ui-serif",
    "ui-sans-serif",
    "ui-rounded",
    "math",
    "emoji",
    "fangsong",
}

Declaration = tuple[str, str]
Rule = tuple[str, list[Declaration]]


def parse_css(css: str) -> list[Rule]:
    """Split CSS into (selector, declarations) rules, flattening @media blocks."""
    text = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    rules: list[Rule] = []

    def walk(chunk: str) -> None:
        pos = 0
        while True:
            open_at = chunk.find("{", pos)
            if open_at == -1:
                return
            depth = 1
            end = open_at + 1
            while depth and end < len(chunk):
                depth += {"{": 1, "}": -1}.get(chunk[end], 0)
                end += 1
            prelude = chunk[pos:open_at].strip()
            body = chunk[open_at + 1 : end - 1]
            if prelude.startswith("@"):
                walk(body)
            else:
                decls: list[Declaration] = []
                for part in body.split(";"):
                    if ":" in part:
                        prop, value = part.split(":", 1)
                        decls.append((prop.strip().lower(), value.strip()))
                for selector in prelude.split(","):
                    rules.append((" ".join(selector.split()), decls))
            pos = end

    walk(text)
    return rules


def _split_rules() -> tuple[list[Rule], list[Rule]]:
    rules = parse_css(load_css())
    root = [r for r in rules if r[0] == ":root"]
    other = [r for r in rules if r[0] != ":root"]
    return root, other


def test_parse_css_handles_comments_and_media() -> None:
    rules = parse_css("/* x { a: b } */ .a, .b { c: d; } @media (x) { .e { f: g } }")
    assert [selector for selector, _ in rules] == [".a", ".b", ".e"]
    assert rules[2][1] == [("f", "g")]


def test_root_holds_exactly_the_nine_steering_tokens() -> None:
    root, _ = _split_rules()
    assert len(root) == 1
    tokens = {prop: value for prop, value in root[0][1]}
    assert len(root[0][1]) == len(tokens)
    assert {k: v.upper() for k, v in tokens.items()} == {
        k: v.upper() for k, v in STEERING_TOKENS.items()
    }


def test_no_literal_colors_outside_root() -> None:
    _, other = _split_rules()
    offenders: list[str] = []
    for selector, decls in other:
        for prop, value in decls:
            if re.search(
                r"#[0-9a-fA-F]{3,8}\b|\b(rgb|rgba|hsl|hsla|hwb|lab|lch|oklab|oklch)\(", value
            ):
                offenders.append(f"{selector} {prop}: {value}")
            if prop not in COLOR_PROPERTIES:
                continue
            bare = re.sub(r"var\([^)]*\)", " ", value)
            for word in re.findall(r"[a-zA-Z][a-zA-Z-]*", bare):
                lowered = word.lower()
                if lowered in NON_COLOR_WORDS:
                    continue
                if lowered in NAMED_COLORS:
                    offenders.append(f"{selector} {prop}: {value}")
    assert offenders == []


def test_every_color_property_uses_a_steering_variable() -> None:
    _, other = _split_rules()
    offenders: list[str] = []
    for selector, decls in other:
        for prop, value in decls:
            for name in re.findall(r"var\(\s*(--[\w-]+)", value):
                if name not in STEERING_TOKENS:
                    offenders.append(f"{selector} {prop}: {value}")
            if prop in COLOR_PROPERTIES and "var(" not in value:
                words = set(re.findall(r"[a-zA-Z][a-zA-Z-]*", value.lower()))
                numbers_only = not words and re.fullmatch(r"[\d.\s]*(px)?", value) is not None
                if not (words <= NON_COLOR_WORDS or numbers_only):
                    offenders.append(f"{selector} {prop}: {value}")
    assert offenders == []


def test_no_shadows_or_gradients() -> None:
    css = re.sub(r"/\*.*?\*/", "", load_css(), flags=re.DOTALL)
    assert "box-shadow" not in css
    assert "text-shadow" not in css
    assert not re.search(r"gradient\s*\(", css)


def test_every_border_radius_is_3px() -> None:
    _, other = _split_rules()
    radii = [
        (selector, value)
        for selector, decls in other
        for prop, value in decls
        if prop.startswith("border") and prop.endswith("radius")
    ]
    assert radii
    assert all(value == "3px" for _, value in radii)


def test_every_font_family_ends_with_a_generic_family() -> None:
    rules = parse_css(load_css())
    families = [
        (selector, value)
        for selector, decls in rules
        for prop, value in decls
        if prop == "font-family"
    ]
    assert families
    for selector, value in families:
        last = value.split(",")[-1].strip().strip("\"'").lower()
        assert last in GENERIC_FAMILIES, f"{selector}: {value}"


def _is_tile_selector(selector: str) -> bool:
    return re.search(r"\.tile(?![\w-])|\.tile-(name|value|detail)\b", selector) is not None


def test_tile_height_is_set_once_on_the_tile_rule() -> None:
    rules = parse_css(load_css())
    height_props = {"height", "min-height", "max-height"}
    setters = [
        (selector, prop, value)
        for selector, decls in rules
        if _is_tile_selector(selector)
        for prop, value in decls
        if prop in height_props
    ]
    assert setters == [(".tile", "height", "108px")]


def test_tile_grid_uses_the_steering_columns_and_gap() -> None:
    rules = parse_css(load_css())
    grids = [
        dict(decls)
        for selector, decls in rules
        if selector == ".tile-grid"
        and "repeat(auto-fill" in dict(decls).get("grid-template-columns", "")
    ]
    assert len(grids) == 1
    assert grids[0]["grid-template-columns"] == "repeat(auto-fill, minmax(196px, 1fr))"
    assert grids[0]["gap"] == "10px"


# ---------------------------------------------------------------------------
# Shell text tests: parentheses, fonts, theme words, ASCII
# ---------------------------------------------------------------------------

THEME_WORDS = ("spirit", "summon", "seance", "beyond", "medium", "ouija", "ghost", "haunt")

JS_STRING = re.compile(r'"((?:[^"\\\n]|\\.)*)"')


def _visible_text(html: str) -> str:
    body = html.split("<body>", 1)[1]
    body = re.sub(r"<script\b.*?</script>", " ", body, flags=re.DOTALL)
    return " ".join(re.sub(r"<[^>]+>", " ", body).split())


def _shell_texts(html: str, tag_pattern: str) -> list[str]:
    found = re.findall(rf"<({tag_pattern})\b[^>]*>(.*?)</\1>", html, flags=re.DOTALL | re.I)
    return [" ".join(re.sub(r"<[^>]+>", " ", inner).split()) for _, inner in found]


def _js_literals(script: str) -> list[str]:
    return JS_STRING.findall(script)


def test_shell_headings_and_buttons_have_no_parentheses(shell: str) -> None:
    texts = _shell_texts(shell, "h[1-6]|button")
    assert len(texts) >= 5
    assert [t for t in texts if "(" in t or ")" in t] == []


def test_console_js_heading_and_button_text_has_no_parentheses() -> None:
    script = load_js()
    texts: list[str] = []
    # Text set through addText(parent, "h2"|"button", class, "literal").
    add_text = r'addText\([^,]+,\s*"(?:h[1-6]|button)"\s*,\s*[^,]+,\s*("(?:[^"\\\n]|\\.)*")'
    for match in re.finditer(add_text, script):
        texts.append(match.group(1))
    # Literals assigned to textContent anywhere (headings, buttons, chips and notes).
    for match in re.finditer(r'\.textContent\s*=\s*("(?:[^"\\\n]|\\.)*")', script):
        texts.append(match.group(1))
    assert texts
    assert [t for t in texts if "(" in t or ")" in t] == []


def test_google_fonts_links_use_display_swap(shell: str) -> None:
    links = re.findall(r'<link[^>]*href="(https://fonts\.googleapis\.com/css2[^"]*)"', shell)
    assert len(links) == 1
    href = links[0]
    assert "family=Fraunces" in href
    assert "family=Inter" in href
    assert "family=JetBrains+Mono" in href
    assert "display=swap" in href


def test_seance_appears_once_as_the_wordmark(shell: str) -> None:
    assert len(re.findall(r"seance", shell, flags=re.I)) == 1
    assert _shell_texts(shell, "h1") == ["Seance"]
    assert len(re.findall(r"\bSeance\b", _visible_text(shell))) == 1


def test_only_seance_and_ledger_are_theme_words(shell: str) -> None:
    visible = _visible_text(shell).lower()
    assert "ledger" in visible
    for word in THEME_WORDS:
        if word == "seance":
            continue
        assert word not in visible, word
    literals = " ".join(_js_literals(load_js())).lower()
    for word in THEME_WORDS:
        assert word not in literals, word


def test_console_sources_are_ascii_only(shell: str) -> None:
    sources = {
        "index.html": (CONSOLE_DIR / "templates" / "index.html").read_text(encoding="utf-8"),
        "console.css": load_css(),
        "console.js": load_js(),
    }
    for name, text in sources.items():
        assert text.isascii(), name
    assert shell.isascii()


def test_console_js_writes_degree_sign_only_as_an_escape() -> None:
    script = load_js()
    assert "\\u00b0" in script
    assert "\u00b0" not in script


# ---------------------------------------------------------------------------
# Name-free test: the console sources never contain a device or point name
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_CONFIG_FILES = (
    REPO_ROOT / "apps" / "modbus" / "devices.yaml",
    REPO_ROOT / "apps" / "snmp" / "devices.yaml",
)


def _name_hit(text: str, name: str) -> str | None:
    """Return the line of text that holds name as a whole identifier, or None."""
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", re.IGNORECASE)
    for number, line in enumerate(text.splitlines(), start=1):
        if pattern.search(line):
            return f"line {number}: {line.strip()[:120]}"
    return None


def test_console_sources_contain_no_device_or_point_names(make_client: MakeClient) -> None:
    script = load_js()
    stylesheet = load_css()
    template = (CONSOLE_DIR / "templates" / "index.html").read_text(encoding="utf-8")
    texts = {"console.js": script, "console.css": stylesheet, "index.html (template)": template}
    names: set[str] = set()
    for path in APP_CONFIG_FILES:
        config = load_config(path)
        client = make_client(config)
        response = client.get("/")
        assert response.status_code == 200
        texts[f"GET / ({path.parent.name})"] = response.text
        for device in config.devices:
            names.add(device.name)
            names.update(point.name for point in device.points)
    served_js = client.get("/static/console.js")
    assert served_js.status_code == 200
    texts["served console.js"] = served_js.text
    assert len(names) > 10
    found = [
        f"{file}: {name!r} at {hit}"
        for file, text in texts.items()
        for name in sorted(names)
        if (hit := _name_hit(text, name)) is not None
    ]
    assert found == []


# ---------------------------------------------------------------------------
# Properties 1 to 3 as example tests, and Formatter source checks (Requirement 11.4)
# The logic runs in browser JavaScript, so Python asserts the served data and the source.
# ---------------------------------------------------------------------------


def js_function(script: str, name: str) -> tuple[str, str]:
    """Return (parameter list, body) of the named top-level function in the script."""
    match = re.search(rf"(?:async\s+)?function\s+{re.escape(name)}\s*\(([^)]*)\)", script)
    assert match is not None, f"function {name} not found"
    start = script.index("{", match.end())
    depth = 0
    for index in range(start, len(script)):
        depth += {"{": 1, "}": -1}.get(script[index], 0)
        if depth == 0:
            return match.group(1), script[start + 1 : index]
    raise AssertionError(f"function {name} has no closing brace")


def js_body(script: str, name: str) -> str:
    return js_function(script, name)[1]


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _point(name: str, address: int = 100) -> PointConfig:
    return PointConfig(name, str(address), DataType.UINT16, "state")


def test_js_function_helper_extracts_params_and_body() -> None:
    params, body = js_function("async function f(a, b) { if (a) { return 1; } return b; }\n", "f")
    assert params == "a, b"
    assert body.strip() == "if (a) { return 1; } return b;"


# Feature: console-redesign, Property 1
TILE_CONFIGS: dict[str, tuple[DeviceConfig, ...]] = {
    "no devices": (),
    "device with no points": (DeviceConfig("lonely", "No points here", 0.2, ()),),
    "many points": (
        DeviceConfig("wide", "Many points", 0.2, tuple(_point(f"pt{i:02d}", i) for i in range(40))),
    ),
    "out of alphabetical order": (
        DeviceConfig("b-dev", "B", 0.2, tuple(_point(n) for n in ("zeta", "alpha", "mid"))),
        DeviceConfig("a-dev", "A", 0.2, tuple(_point(n) for n in ("m2", "m1", "a0"))),
    ),
    "special characters": (
        DeviceConfig(
            "Line A & B <main>",
            "Odd & <unusual> name",
            0.2,
            tuple(_point(n) for n in ("a&b", "<x>", "tom & jerry <3")),
        ),
    ),
}  # fmt: skip


@pytest.mark.parametrize("case", sorted(TILE_CONFIGS))
def test_config_lists_every_configured_point_in_order_with_exact_strings(
    make_client: MakeClient, case: str
) -> None:
    # Feature: console-redesign, Property 1
    config = Configuration(devices=TILE_CONFIGS[case])
    payload = make_client(config).get("/config").json()
    assert [d["name"] for d in payload["devices"]] == [d.name for d in config.devices]
    assert [d["description"] for d in payload["devices"]] == [d.description for d in config.devices]
    for entry, device in zip(payload["devices"], config.devices, strict=True):
        assert [p["name"] for p in entry["points"]] == [p.name for p in device.points]
        assert len(entry["points"]) == len(device.points)


def test_console_js_builds_one_tile_per_configured_point_in_order(
    make_client: MakeClient,
) -> None:
    # Feature: console-redesign, Property 1
    script = make_client(make_config(1)).get("/static/console.js").text
    assert script == load_js()
    read_device = js_body(script, "readDevice")
    assert "device.points.forEach(" in read_device
    assert len(re.findall(r"\brenderTile\(", read_device)) == 1
    assert len(re.findall(r"\btiles\.push\(", read_device)) == 1
    assert "view.grid.replaceChildren(...tiles)" in read_device
    for reorder in (".sort(", ".reverse(", ".filter(", ".slice(", ".splice(", ".concat("):
        assert reorder not in read_device, reorder
    outcomes = js_body(script, "outcomesFor")
    assert "device.points.map(" in outcomes
    for reorder in (".sort(", ".reverse(", ".filter(", ".slice("):
        assert reorder not in outcomes, reorder


# Feature: console-redesign, Property 2
MODE_POINT = PointConfig(
    "mode", "102", DataType.UINT16, "state", labels=((100, "up"), (2, "down")), healthy="up"
)


def _attention_config() -> Configuration:
    points = (_point("a"), _point("b"), MODE_POINT)
    return Configuration(devices=(DeviceConfig("dev", "Test device", 0.2, points),))


def _attention_count(config_points: tuple[PointConfig, ...], reply: dict[str, object]) -> int:
    """Count points the console marks as attention: failed reads and healthy-label mismatches."""
    result = reply["result"]
    if not isinstance(result, dict):
        return len(config_points)
    by_name = {item["point"]: item for item in result["results"]}
    count = 0
    for point in config_points:
        item = by_name[point.name]
        if "error" in item or (point.healthy is not None and item["value"] != point.healthy):
            count += 1
    return count


def _read_all(client: TestClient, config: Configuration) -> dict[str, object]:
    device = config.devices[0]
    body = {"device": device.name, "points": [p.name for p in device.points]}
    reply = client.post("/tools/read_points", json=body)
    assert reply.status_code == 200
    return reply.json()


def test_read_points_with_no_failures_gives_no_attention(
    session_portal: BlockingPortal,
) -> None:
    # Feature: console-redesign, Property 2
    config = _attention_config()
    with ExitStack() as stack:
        server = ToolServer(config, Fake_Adapter(data=b"\x00\x64"))
        stack.callback(server.close)
        client = TestClient(create_app(server))
        client.portal = session_portal
        stack.callback(client.close)
        reply = _read_all(client, config)
    assert reply["ok"] is True
    assert reply["result"]["results"][2]["value"] == "up"
    assert _attention_count(config.devices[0].points, reply) == 0


def test_read_points_with_a_healthy_label_mismatch_gives_one_attention(
    session_portal: BlockingPortal,
) -> None:
    # Feature: console-redesign, Property 2
    config = _attention_config()
    with ExitStack() as stack:
        server = ToolServer(config, Fake_Adapter(data=b"\x00\x02"))
        stack.callback(server.close)
        client = TestClient(create_app(server))
        client.portal = session_portal
        stack.callback(client.close)
        reply = _read_all(client, config)
    results = reply["result"]["results"]
    assert results[2]["value"] == "down"
    assert all("error" not in item for item in results)
    assert _attention_count(config.devices[0].points, reply) == 1


def test_read_points_with_every_point_failing_gives_one_attention_per_point(
    session_portal: BlockingPortal,
) -> None:
    # Feature: console-redesign, Property 2
    config = _attention_config()
    with ExitStack() as stack:
        server = ToolServer(config, Fake_Adapter(error=RuntimeError("boom")))
        stack.callback(server.close)
        client = TestClient(create_app(server))
        client.portal = session_portal
        stack.callback(client.close)
        reply = _read_all(client, config)
    results = reply["result"]["results"]
    assert [item["point"] for item in results] == ["a", "b", "mode"]
    assert all("error" in item and item["error"] for item in results)
    assert "boom" not in str(reply)
    assert _attention_count(config.devices[0].points, reply) == 3


def test_read_points_with_one_unknown_point_fails_only_that_point(
    session_portal: BlockingPortal,
) -> None:
    # Feature: console-redesign, Property 2
    config = _attention_config()
    with ExitStack() as stack:
        server = ToolServer(config, Fake_Adapter(data=b"\x00\x64"))
        stack.callback(server.close)
        client = TestClient(create_app(server))
        client.portal = session_portal
        stack.callback(client.close)
        reply = client.post(
            "/tools/read_points", json={"device": "dev", "points": ["a", "ghost", "mode"]}
        ).json()
    results = reply["result"]["results"]
    assert [("error" in item) for item in results] == [False, True, False]
    assert results[1]["point"] == "ghost"


def test_console_js_builds_tiles_and_chips_from_one_shared_list() -> None:
    # Feature: console-redesign, Property 2
    script = load_js()
    read_device = js_body(script, "readDevice")
    # One loop makes the tile and decides attention; the same record feeds the chip list.
    assert len(re.findall(r"\brenderTile\(", read_device)) == 1
    assert "const made = renderTile(point, outcome);" in _squash(read_device)
    assert len(re.findall(r"\battention\.push\(", read_device)) == 1
    push_at = read_device.index("attention.push(")
    assert "if (made.attention)" in read_device[:push_at]
    assert "tile: made.element" in read_device[push_at:]
    assert "return { read: read, attention: attention }" in _squash(read_device)
    summary = js_body(script, "renderSummaryStrip")
    assert "result.attention" in summary
    assert len(re.findall(r"\bchips\.push\(", summary)) == 1
    assert len(re.findall(r"for \(const item of chips\)", summary)) == 1
    assert len(re.findall(r'createElement\("button"\)', summary)) == 1
    # Chips never re-decide attention on their own.
    for other in ("renderTile(", "healthy", "formatReading("):
        assert other not in summary, other
    assert len(re.findall(r"\bdocument\.createElement\(", js_body(script, "renderTile"))) == 1
    assert "attention-chip" not in js_body(script, "renderTile")


# Feature: console-redesign, Property 3 (console half)
REASON_OUTCOMES = (
    "rejected",
    "unknown_tool",
    "unknown_target",
    "invalid_argument",
    "timeout",
    "adapter_error",
)


def _reason_table(script: str) -> dict[str, str]:
    block = script.split("const REASON_SENTENCES = {", 1)[1].split("};", 1)[0]
    return dict(re.findall(r'(\w+)\s*:\s*"((?:[^"\\\n]|\\.)*)"', block))


def test_render_ledger_rows_replaces_rows_in_one_pass_in_received_order() -> None:
    # Feature: console-redesign, Property 3
    script = load_js()
    body = js_body(script, "renderLedgerRows")
    for forbidden in (".sort(", ".slice(", ".reverse(", ".concat(", ".splice(", ".filter("):
        assert forbidden not in body, forbidden
    for old_rows in ("host.children", "host.childNodes", "host.innerHTML", "querySelector"):
        assert old_rows not in body, old_rows
    assert len(re.findall(r"\bentries\.map\(", body)) == 1
    assert len(re.findall(r"host\.replaceChildren\(", body)) == 2
    assert "host.replaceChildren(...rows)" in body
    poll = js_body(script, "pollAudit")
    assert "renderLedgerRows(entries)" in poll
    assert "const entries = await response.json();" in _squash(poll)


def test_each_ledger_outcome_has_a_distinct_non_empty_sentence_and_one_generic() -> None:
    # Feature: console-redesign, Property 3
    script = load_js()
    table = _reason_table(script)
    assert tuple(table) == REASON_OUTCOMES
    sentences = list(table.values())
    assert all(s.strip() and s.rstrip().endswith(".") for s in sentences)
    generic = re.search(r'const GENERIC_REASON\s*=\s*"((?:[^"\\\n]|\\.)*)"', script)
    assert generic is not None
    assert generic.group(1).strip()
    assert len({*sentences, generic.group(1)}) == len(REASON_OUTCOMES) + 1
    lookup = js_body(script, "reasonSentence")
    assert "REASON_SENTENCES" in lookup
    assert "GENERIC_REASON" in lookup
    assert "hasOwnProperty" in lookup


# Formatter source checks
FORMATTER_FUNCTIONS = (
    "formatSeconds",
    "formatBytes",
    "formatBoolean",
    "formatLabeled",
    "formatUnit",
    "formatTimestamp",
    "formatReading",
)


def test_format_seconds_branches_on_sixty_and_has_day_hour_minute_forms() -> None:
    body = _squash(js_body(load_js(), "formatSeconds"))
    assert re.search(r"seconds >= 60", body)
    assert re.search(r'days \+ "d " \+ hours \+ "h " \+ minutes \+ "m"', body)
    assert re.search(r'hours \+ "h " \+ minutes \+ "m"', body)
    assert re.search(r'minutes \+ "m " \+ rest \+ "s"', body)
    assert "Math.floor(" in body
    assert "86400" in body
    assert "3600" in body


def test_format_bytes_has_kb_mb_gb_tb_cutoffs() -> None:
    body = _squash(js_body(load_js(), "formatBytes"))
    steps = re.search(r"const steps = \[([^\]]*)\]", body)
    assert steps is not None
    assert re.findall(r'"(\w+)"', steps.group(1)) == ["kB", "MB", "GB", "TB"]
    assert "1000" in body
    assert "toFixed(2)" in body


@pytest.mark.parametrize("name", FORMATTER_FUNCTIONS)
def test_formatter_functions_take_no_name_or_description_parameter(name: str) -> None:
    params, body = js_function(load_js(), name)
    banned = re.compile(r"name|device|description|point|label_?text", re.IGNORECASE)
    names = [p.strip() for p in params.split(",") if p.strip()]
    assert names
    assert [p for p in names if banned.search(p)] == []
    assert "document" not in body
    assert re.search(r"\.(name|description)\b", body) is None
