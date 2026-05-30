"""Verify start.py wires the Cabinet static server into its lifecycle."""

from __future__ import annotations

from typing import Any

import pytest

import start


def test_spawn_cabinet_flag_off_returns_none() -> None:
    # Real launch_cabinet, flag off -> no server, no port bound.
    assert start.spawn_cabinet({}) is None


def test_spawn_cabinet_flag_false_returns_none() -> None:
    assert start.spawn_cabinet({"CABINET_AUTOSTART_ENABLED": "false"}) is None


def test_spawn_cabinet_delegates_to_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    captured: dict[str, Any] = {}

    def fake_launch(repo_root: Any, env: Any) -> Any:
        captured["repo_root"] = repo_root
        captured["env"] = env
        return sentinel

    monkeypatch.setattr(start, "launch_cabinet", fake_launch)
    result = start.spawn_cabinet({"CABINET_AUTOSTART_ENABLED": "true"})
    assert result is sentinel
    assert captured["env"] == {"CABINET_AUTOSTART_ENABLED": "true"}


def test_stop_cabinet_none_is_noop() -> None:
    start.stop_cabinet(None)


def test_stop_cabinet_calls_stop_on_handle() -> None:
    calls: list[str] = []

    class _FakeServer:
        def stop(self) -> None:
            calls.append("stopped")

    start.stop_cabinet(_FakeServer())  # type: ignore[arg-type]
    assert calls == ["stopped"]


def test_main_wires_cabinet_stop_before_syncall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []

    class _Server:
        def stop(self) -> None:
            order.append("cabinet")

    def fake_spawn_cabinet(_env: Any) -> _Server:
        return _Server()

    def fake_spawn_syncall(_env: Any, popen: Any = None) -> None:  # noqa: ARG001
        return None

    def fake_stop_syncall(_proc: Any) -> None:
        order.append("syncall")

    def fake_run_gateway(*_args: Any, **_kwargs: Any) -> int:
        return 0

    def fake_create_server(_config: Any) -> Any:
        class _Dash:
            timeout = 1.0

            def handle_request(self) -> None:
                pass

            def server_close(self) -> None:
                pass

        return _Dash()

    monkeypatch.setattr(start, "spawn_cabinet", fake_spawn_cabinet)
    monkeypatch.setattr(start, "spawn_syncall_daemon", fake_spawn_syncall)
    monkeypatch.setattr(start, "stop_syncall_daemon", fake_stop_syncall)
    monkeypatch.setattr(start, "run_gateway", fake_run_gateway)
    monkeypatch.setattr(start, "create_dashboard_server", fake_create_server)
    monkeypatch.setattr(start, "load_config_from_env", lambda: object())

    def fake_exit(_code: int) -> None:
        raise SystemExit(_code)

    monkeypatch.setattr("sys.exit", fake_exit)

    with pytest.raises(SystemExit):
        start.main()

    assert order == ["cabinet", "syncall"]
