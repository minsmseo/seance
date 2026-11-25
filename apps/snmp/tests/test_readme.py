"""Tests for apps/snmp/README.md against the shipped devices.yaml.

Reads files only and makes no network call.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from seance.config import load_config

APP_DIR = Path(__file__).resolve().parent.parent
README_PATH = APP_DIR / "README.md"
MODBUS_README_PATH = APP_DIR.parent / "modbus" / "README.md"
CONFIG_PATH = APP_DIR / "devices.yaml"
TOOL_NAMES = (
    "list_devices",
    "list_points",
    "read_point",
    "read_points",
    "device_health",
)
ENV_DEFAULTS = {
    "SEANCE_SNMP_HOST": "127.0.0.1",
    "SEANCE_SNMP_PORT": "1161",
    "SEANCE_CONSOLE_HOST": "127.0.0.1",
    "SEANCE_CONSOLE_PORT": "8080",
}


@pytest.fixture(scope="module")
def readme() -> str:
    return README_PATH.read_text(encoding="utf-8")


def _headings(text: str) -> list[str]:
    return re.findall(r"^## (.+)$", text, re.M)


def _section(text: str, heading: str) -> str:
    """Return the text under a level-2 heading, up to the next level-2 heading."""
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert match is not None, f"README has no section '{heading}'"
    return match.group(1)


def test_readme_is_ascii_only(readme: str) -> None:
    assert readme.isascii()


def test_headings_equal_modbus_readme_headings(readme: str) -> None:
    modbus = MODBUS_README_PATH.read_text(encoding="utf-8")
    assert _headings(readme) == _headings(modbus)


def test_readme_states_run_command(readme: str) -> None:
    assert "uv run python -m apps.snmp" in readme


@pytest.mark.parametrize(("name", "default"), sorted(ENV_DEFAULTS.items()))
def test_readme_lists_variable_with_default(readme: str, name: str, default: str) -> None:
    rows = [line for line in readme.splitlines() if f"`{name}`" in line]
    assert rows, f"README does not mention {name}"
    assert any(f"`{default}`" in row for row in rows)


def test_readme_explains_port_1161(readme: str) -> None:
    assert "1161" in readme
    assert "161" in readme
    assert "elevated privileges" in readme


def test_readme_states_community_convention(readme: str) -> None:
    assert "community" in readme
    assert "Simulator convention" in readme
    assert "device name" in readme
    assert "secret" in readme


def test_every_point_is_listed_with_its_fields(readme: str) -> None:
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in _section(readme, "Points").splitlines()
        if line.startswith("|")
    ]
    config = load_config(CONFIG_PATH)
    for device in config.devices:
        for point in device.points:
            scale = "none" if point.scale is None else str(point.scale)
            if point.labels is None:
                labels = "none"
            else:
                labels = ", ".join(f"{value}={word}" for value, word in point.labels)
            expected = [
                device.name,
                point.name,
                point.address,
                str(point.data_type),
                point.unit,
                scale,
                labels,
            ]
            assert expected in rows, f"README row missing for {expected}"


def test_three_example_questions_name_existing_tools(readme: str) -> None:
    section = _section(readme, "Example questions")
    items = re.split(r"^(?=\d+\. )", section, flags=re.M)
    questions = [item for item in items if re.match(r"\d+\. ", item)]
    assert len(questions) == 3
    for question in questions:
        words = set(re.findall(r"`(\w+)`", question))
        used = words & set(TOOL_NAMES)
        assert used, f"No tool call in: {question.splitlines()[0]}"


def test_an_example_question_asks_for_the_down_core_switch_port(readme: str) -> None:
    section = _section(readme, "Example questions")
    assert "core switch" in section
    assert "down" in section
    assert "port3_status" in section


def test_readme_mentions_test_command_and_mcp_json(readme: str) -> None:
    assert "uv run pytest apps/snmp/tests" in readme
    assert "mcp.json" in readme
