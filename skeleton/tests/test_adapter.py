"""Unit tests for adapter registration and skeleton layering."""

import ast
from pathlib import Path

import pytest

from seance.adapter import (
    REQUIRED_METHODS,
    AdapterReadError,
    AdapterRegistrationError,
    ProtocolAdapter,
    check_adapter,
)
from tests.fakes import Fake_Adapter

SKELETON_DIR = Path(__file__).resolve().parent.parent / "seance"
FORBIDDEN_ROOTS = {"pymodbus", "pysnmp", "apps"}
WRITE_PREFIXES = ("write", "set", "put", "post", "delete", "update", "send", "poke")


def test_complete_adapter_passes_check() -> None:
    check_adapter(Fake_Adapter())


@pytest.mark.parametrize("missing", REQUIRED_METHODS)
def test_missing_method_raises_naming_method_and_class(missing: str) -> None:
    namespace: dict[str, object] = {
        name: (lambda self, *a, **k: None) for name in REQUIRED_METHODS if name != missing
    }
    broken_cls = type("BrokenAdapter", (), namespace)

    with pytest.raises(AdapterRegistrationError) as excinfo:
        check_adapter(broken_cls())

    message = str(excinfo.value)
    assert missing in message
    assert "BrokenAdapter" in message
    assert excinfo.value.missing_method == missing
    assert excinfo.value.adapter_class_name == "BrokenAdapter"


def test_non_callable_attribute_counts_as_missing() -> None:
    class Odd:
        connect = None

        def close(self) -> None: ...

        def read(self, device: object, point: object) -> bytes:
            return b""

        def health(self, device: object) -> None: ...

    with pytest.raises(AdapterRegistrationError, match="connect"):
        check_adapter(Odd())


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_skeleton_modules_exist_to_scan() -> None:
    assert list(SKELETON_DIR.rglob("*.py"))


def test_skeleton_does_not_import_protocol_libraries_or_apps() -> None:
    offenders = {
        str(path.relative_to(SKELETON_DIR)): sorted(_imported_roots(path) & FORBIDDEN_ROOTS)
        for path in SKELETON_DIR.rglob("*.py")
        if _imported_roots(path) & FORBIDDEN_ROOTS
    }
    assert offenders == {}


def test_protocol_adapter_exposes_no_write_method() -> None:
    public = {name for name in vars(ProtocolAdapter) if not name.startswith("_")}
    assert public == set(REQUIRED_METHODS)
    assert not [n for n in public if n.lower().startswith(WRITE_PREFIXES)]


def test_adapter_read_error_carries_its_message() -> None:
    err = AdapterReadError("press has no register at 100. Check the point address.")
    assert err.message == "press has no register at 100. Check the point address."
    assert str(err) == err.message
    assert isinstance(err, Exception)
