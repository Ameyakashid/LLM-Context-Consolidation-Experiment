"""Verify start.py's syncall daemon spawn + shutdown wiring."""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

import start


class _StubPopen:
    """Minimal Popen stand-in that records its construction args."""

    instances: list["_StubPopen"] = []

    def __init__(self, argv: list[str], **kwargs: Any) -> None:
        self.argv = argv
        self.kwargs = kwargs
        self.pid = 1234
        self._terminated = False
        self._killed = False
        self.returncode = 0
        _StubPopen.instances.append(self)

    def poll(self) -> int | None:
        return self.returncode if self._terminated else None

    def terminate(self) -> None:
        self._terminated = True

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode

    def kill(self) -> None:
        self._killed = True
        self._terminated = True


@pytest.fixture(autouse=True)
def _reset_stub_popen() -> None:
    _StubPopen.instances = []


def test_spawn_syncall_daemon_skips_when_flag_off() -> None:
    handle = start.spawn_syncall_daemon({}, popen=_StubPopen)  # type: ignore[arg-type]
    assert handle is None
    assert _StubPopen.instances == []


def test_spawn_syncall_daemon_invokes_popen_when_flag_on() -> None:
    env = {"SYNCALL_ENABLED": "true"}
    handle = start.spawn_syncall_daemon(env, popen=_StubPopen)  # type: ignore[arg-type]
    assert isinstance(handle, _StubPopen)
    assert len(_StubPopen.instances) == 1
    argv = _StubPopen.instances[0].argv
    assert "syncall_daemon" in " ".join(argv)


def test_spawn_syncall_daemon_uses_current_python_executable() -> None:
    import sys
    env = {"SYNCALL_ENABLED": "true"}
    start.spawn_syncall_daemon(env, popen=_StubPopen)  # type: ignore[arg-type]
    argv = _StubPopen.instances[0].argv
    assert argv[0] == sys.executable


def test_stop_syncall_daemon_is_noop_for_none() -> None:
    start.stop_syncall_daemon(None)


def test_stop_syncall_daemon_terminates_running_child() -> None:
    env = {"SYNCALL_ENABLED": "true"}
    proc = start.spawn_syncall_daemon(env, popen=_StubPopen)  # type: ignore[arg-type]
    assert proc is not None
    start.stop_syncall_daemon(proc)  # type: ignore[arg-type]
    assert proc._terminated  # type: ignore[attr-defined]


def test_stop_syncall_daemon_kills_on_timeout() -> None:
    class SlowPopen(_StubPopen):
        def wait(self, timeout: float | None = None) -> int:
            raise subprocess.TimeoutExpired(cmd=self.argv, timeout=timeout or 0)

    env = {"SYNCALL_ENABLED": "true"}
    proc = start.spawn_syncall_daemon(env, popen=SlowPopen)  # type: ignore[arg-type]
    assert proc is not None
    # wait() raises on terminate(), so we override kill path: use a new
    # mock that returns 0 from wait() after kill. Patch wait on the stub.
    kill_wait_calls = {"n": 0}

    def post_kill_wait(timeout: float | None = None) -> int:
        kill_wait_calls["n"] += 1
        return 0

    # First call raises TimeoutExpired; after kill() the code calls wait(5)
    # which we now allow to return cleanly.
    original_wait = proc.wait  # type: ignore[attr-defined]

    def maybe_raise(timeout: float | None = None) -> int:
        if not proc._killed:  # type: ignore[attr-defined]
            raise subprocess.TimeoutExpired(cmd=proc.argv, timeout=timeout or 0)  # type: ignore[attr-defined]
        return post_kill_wait(timeout)

    proc.wait = maybe_raise  # type: ignore[attr-defined, method-assign]
    start.stop_syncall_daemon(proc)  # type: ignore[arg-type]
    assert proc._killed  # type: ignore[attr-defined]
