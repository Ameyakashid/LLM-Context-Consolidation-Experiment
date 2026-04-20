"""Verify start.py wires the MagicMirror launcher into its lifecycle."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import start
from magicmirror_launcher import MagicMirrorProcess


class _StubPopen:
    instances: list["_StubPopen"] = []

    def __init__(self, argv: list[str], **kwargs: Any) -> None:
        self.argv = argv
        self.kwargs = kwargs
        self.pid = 9001
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


def _make_real_config() -> Path:
    repo_root = Path(start.__file__).resolve().parent
    config = repo_root / "magicmirror" / "config" / "config.js"
    return config


def test_spawn_magicmirror_flag_off_returns_none() -> None:
    handle = start.spawn_magicmirror({}, popen=_StubPopen)  # type: ignore[arg-type]
    assert handle is None
    assert _StubPopen.instances == []


def test_spawn_magicmirror_flag_false_returns_none() -> None:
    handle = start.spawn_magicmirror(
        {"MAGICMIRROR_AUTOSTART_ENABLED": "false"},
        popen=_StubPopen,  # type: ignore[arg-type]
    )
    assert handle is None
    assert _StubPopen.instances == []


def test_spawn_magicmirror_flag_on_invokes_popen() -> None:
    if not _make_real_config().is_file():
        pytest.skip("rendered magicmirror config.js not present in this checkout")
    handle = start.spawn_magicmirror(
        {"MAGICMIRROR_AUTOSTART_ENABLED": "true"},
        popen=_StubPopen,  # type: ignore[arg-type]
    )
    assert isinstance(handle, MagicMirrorProcess)
    assert len(_StubPopen.instances) == 1
    argv = _StubPopen.instances[0].argv
    assert argv[0] == "npm"
    assert argv[1] == "start"
    assert argv[2] == "--prefix"


def test_spawn_magicmirror_raises_when_config_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        start,
        "launch_magicmirror",
        _fake_launch_raising,
    )
    with pytest.raises(RuntimeError, match="config.js"):
        start.spawn_magicmirror(
            {"MAGICMIRROR_AUTOSTART_ENABLED": "true"},
            popen=_StubPopen,  # type: ignore[arg-type]
        )


def _fake_launch_raising(*_args: Any, **_kwargs: Any) -> MagicMirrorProcess | None:
    raise RuntimeError("MagicMirror config missing (config.js) — run setup_workspace()")


def test_stop_magicmirror_none_is_noop() -> None:
    start.stop_magicmirror(None)


def test_stop_magicmirror_calls_stop_on_handle(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[float] = []

    class _FakeHandle:
        def stop(self, timeout: float = 10.0) -> None:
            calls.append(timeout)

    start.stop_magicmirror(_FakeHandle())  # type: ignore[arg-type]
    assert len(calls) == 1


def test_main_wires_magicmirror_stop_before_syncall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []

    class _Handle:
        def stop(self, timeout: float = 10.0) -> None:
            order.append("magicmirror")

    def fake_spawn_magicmirror(
        _env: Any,
        popen: Any = None,  # noqa: ARG001
    ) -> _Handle:
        return _Handle()

    def fake_spawn_syncall(
        _env: Any,
        popen: Any = None,  # noqa: ARG001
    ) -> None:
        return None

    def fake_stop_syncall(_proc: Any) -> None:
        order.append("syncall")

    def fake_run_gateway(*_args: Any, **_kwargs: Any) -> int:
        return 0

    def fake_create_server(_config: Any) -> Any:
        class _Server:
            timeout = 1.0

            def handle_request(self) -> None:
                pass

            def server_close(self) -> None:
                pass

        return _Server()

    def fake_load_config() -> Any:
        return object()

    monkeypatch.setattr(start, "spawn_magicmirror", fake_spawn_magicmirror)
    monkeypatch.setattr(start, "spawn_syncall_daemon", fake_spawn_syncall)
    monkeypatch.setattr(start, "stop_syncall_daemon", fake_stop_syncall)
    monkeypatch.setattr(start, "run_gateway", fake_run_gateway)
    monkeypatch.setattr(start, "create_dashboard_server", fake_create_server)
    monkeypatch.setattr(start, "load_config_from_env", fake_load_config)

    def fake_exit(_code: int) -> None:
        raise SystemExit(_code)

    monkeypatch.setattr("sys.exit", fake_exit)

    with pytest.raises(SystemExit):
        start.main()

    assert order == ["magicmirror", "syncall"]
