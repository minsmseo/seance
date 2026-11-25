"""Shared pytest setup: one event loop per session, loop accounting, Windows rerun net.

On Windows every new asyncio event loop opens a loopback socket pair (the self-pipe).
Each closed pair stays in TIME_WAIT for about two minutes, and thousands of them make
Winsock fail with WinError 10014. Tests therefore share the loops below instead of
creating one per test or per hypothesis example.
"""

import asyncio
import re
import sys
import threading
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from types import FrameType

import pytest
from anyio.from_thread import BlockingPortal, start_blocking_portal

_REPO_ROOT = Path(__file__).resolve().parent
_ROOT_PREFIX = _REPO_ROOT.as_posix().rstrip("/").casefold() + "/"
_THIS_FILE = Path(__file__).resolve().as_posix().casefold()
_MAX_DEPTH = 60
_TOP_SITES = 8


def _posix(filename: str) -> str:
    return filename.replace("\\", "/")


def _generic_thread_name() -> str:
    """Thread name without trailing numbers, so equal sites aggregate."""
    return re.sub(r"-\d+", "", threading.current_thread().name)


def _call_site(start: FrameType | None) -> str:
    """Name the code that created a loop, walking outward from ``start``.

    The first frame inside the repo (not conftest.py, not .venv or site-packages) wins.
    If there is none, fall back to the innermost frame outside asyncio and conftest.
    """
    fallback: str | None = None
    frame = start
    depth = 0
    while frame is not None and depth < _MAX_DEPTH:
        path = _posix(frame.f_code.co_filename)
        folded = path.casefold()
        if folded != _THIS_FILE:
            in_env = "/.venv/" in folded or "/site-packages/" in folded
            if folded.startswith(_ROOT_PREFIX) and not in_env:
                site = f"{path[len(_ROOT_PREFIX) :]}:{frame.f_lineno}"
                name = _generic_thread_name()
                if name != "MainThread":
                    site += f" [thread={name}]"
                return site
            if fallback is None and "/asyncio/" not in folded:
                short = path.split("site-packages/", 1)[-1]
                fallback = f"{short}:{frame.f_lineno}"
        frame = frame.f_back
        depth += 1
    if fallback is None:
        fallback = "unknown"
    return f"<external> {fallback} [thread={_generic_thread_name()}]"


class _LoopCounter:
    """Counts every BaseEventLoop construction, from any thread, by call site."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._count = 0
        self._sites: Counter[str] = Counter()
        self._original_init = asyncio.BaseEventLoop.__init__
        self._installed = False

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    def top_sites(self, limit: int) -> list[tuple[str, int]]:
        with self._lock:
            return self._sites.most_common(limit)

    def install(self) -> None:
        """Wrap BaseEventLoop.__init__.

        Every loop class (selector, proactor, and any subclass) runs this constructor,
        so asyncio.run, asyncio.Runner, anyio, direct new_event_loop() calls and loops
        made in background threads are all counted. Patching only the new_event_loop
        names would miss loops created through the policy or by instantiating a loop
        class directly.
        """
        if self._installed:
            return
        original = self._original_init
        counter = self

        def counting_init(self: asyncio.BaseEventLoop) -> None:
            site = _call_site(sys._getframe(1))
            with counter._lock:
                counter._count += 1
                counter._sites[site] += 1
            original(self)

        asyncio.BaseEventLoop.__init__ = counting_init  # type: ignore[method-assign]
        self._installed = True

    def uninstall(self) -> None:
        if self._installed:
            asyncio.BaseEventLoop.__init__ = self._original_init  # type: ignore[method-assign]
            self._installed = False


_LOOPS = _LoopCounter()


def pytest_configure(config: pytest.Config) -> None:
    # Installed at configure time so collection and import-time loops are counted too.
    _LOOPS.install()


def pytest_unconfigure(config: pytest.Config) -> None:
    _LOOPS.uninstall()


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, exitstatus: int, config: pytest.Config
) -> None:
    terminalreporter.write_line(f"asyncio event loops created: {_LOOPS.count}")
    terminalreporter.write_line("top event loop call sites:")
    for site, count in _LOOPS.top_sites(_TOP_SITES):
        terminalreporter.write_line(f"  {count:>5}  {site}")


@pytest.fixture(scope="session")
def session_loop() -> Iterator[asyncio.AbstractEventLoop]:
    """The one event loop for test coroutines. Use ``session_loop.run_until_complete``.

    Session scope is allowed inside hypothesis ``@given`` tests, so property tests
    reuse this loop instead of creating one per example.
    """
    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            loop.close()


@pytest.fixture(scope="session")
def session_portal() -> Iterator[BlockingPortal]:
    """One anyio portal (one event loop on a helper thread) shared by all TestClients."""
    with start_blocking_portal() as portal:
        yield portal


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    # Intermittent WinError 10014 from Winsock on some Windows machines can hit any
    # socket call. Rerun there only; other platforms stay strict.
    if sys.platform != "win32":
        return
    for item in items:
        item.add_marker(pytest.mark.flaky(reruns=3, reruns_delay=0.5))
