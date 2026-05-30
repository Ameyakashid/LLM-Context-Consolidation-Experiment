"""Lifecycle tests for launch_cabinet via an injected server stub.

No real uvicorn server is started: a ``_StubServer`` is injected through
``server_factory`` so we exercise flag-gating, the index-present
precondition, dir creation, and config plumbing without binding a port.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cabinet_server import CabinetServer, launch_cabinet


class _StubServer:
    instances: list["_StubServer"] = []

    def __init__(self, app: Any, host: str, port: int) -> None:
        self.app = app
        self.host = host
        self.port = port
        self.started = False
        self.stopped = False
        _StubServer.instances.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self, timeout: float = 10.0) -> None:
        self.stopped = True

    def is_running(self) -> bool:
        return self.started and not self.stopped


@pytest.fixture(autouse=True)
def _reset() -> None:
    _StubServer.instances = []


def _make_cabinet(tmp_path: Path) -> Path:
    cabinet = tmp_path / "cabinet"
    cabinet.mkdir(parents=True)
    (cabinet / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
    return cabinet


def test_flag_off_returns_none(tmp_path: Path) -> None:
    _make_cabinet(tmp_path)
    server = launch_cabinet(
        tmp_path, {"CABINET_AUTOSTART_ENABLED": "false"}, server_factory=_StubServer,
    )
    assert server is None
    assert _StubServer.instances == []


def test_flag_on_starts_server(tmp_path: Path) -> None:
    _make_cabinet(tmp_path)
    server = launch_cabinet(
        tmp_path, {"CABINET_AUTOSTART_ENABLED": "true"}, server_factory=_StubServer,
    )
    assert server is not None
    assert len(_StubServer.instances) == 1
    assert _StubServer.instances[0].started is True


def test_autostart_falls_back_to_legacy_flag(tmp_path: Path) -> None:
    _make_cabinet(tmp_path)
    server = launch_cabinet(
        tmp_path,
        {"MAGICMIRROR_AUTOSTART_ENABLED": "true"},
        server_factory=_StubServer,
    )
    assert server is not None


def test_missing_index_raises(tmp_path: Path) -> None:
    (tmp_path / "cabinet").mkdir()
    with pytest.raises(RuntimeError, match="Cabinet frontend missing"):
        launch_cabinet(
            tmp_path,
            {"CABINET_AUTOSTART_ENABLED": "true"},
            server_factory=_StubServer,
        )


def test_creates_feed_and_wallpaper_dirs(tmp_path: Path) -> None:
    _make_cabinet(tmp_path)
    launch_cabinet(
        tmp_path, {"CABINET_AUTOSTART_ENABLED": "true"}, server_factory=_StubServer,
    )
    assert (tmp_path / "cabinet" / "feeds").is_dir()
    assert (tmp_path / "cabinet" / "wallpapers").is_dir()


def test_host_and_port_plumbed(tmp_path: Path) -> None:
    _make_cabinet(tmp_path)
    launch_cabinet(
        tmp_path,
        {
            "CABINET_AUTOSTART_ENABLED": "true",
            "CABINET_HOST": "0.0.0.0",
            "CABINET_PORT": "9090",
        },
        server_factory=_StubServer,
    )
    assert _StubServer.instances[0].host == "0.0.0.0"
    assert _StubServer.instances[0].port == 9090


def test_real_server_is_single_use(tmp_path: Path) -> None:
    # CabinetServer.stop marks the instance spent; start after stop raises.
    server = CabinetServer(app=object(), host="127.0.0.1", port=8099)  # type: ignore[arg-type]
    server.stop()
    with pytest.raises(RuntimeError, match="single-use"):
        server.start()


def test_stop_idempotent_without_start(tmp_path: Path) -> None:
    server = CabinetServer(app=object(), host="127.0.0.1", port=8099)  # type: ignore[arg-type]
    server.stop()
    server.stop()
    assert server.is_running() is False
