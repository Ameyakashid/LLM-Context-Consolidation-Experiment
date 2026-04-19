"""Cross-consumer integration suite for Task 16's Taskwarrior wiring.

Proves that with ``TASKWARRIOR_ENABLED=true``, the three consumer paths
— the LLM tool registry, the dashboard ``/tasks`` endpoint, and the
MagicMirror hook's ``tasks.md`` feed — all see the same Taskwarrior
backend end-to-end, and each supports a full create/read/update/delete
round-trip. Skipped at collection time when the ``task`` CLI is absent.
"""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Coroutine
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

if shutil.which("task") is None:
    pytest.skip(
        "Taskwarrior CLI not installed — skipping task-16 integration suite.",
        allow_module_level=True,
    )

pytest.importorskip("tasklib")

import dashboard_api  # noqa: E402
from buffer_store import BufferStore  # noqa: E402
from checkin_schedule import CheckInScheduleStore  # noqa: E402
from magicmirror_feeds import render_tasks_markdown  # noqa: E402
from magicmirror_hook import MagicMirrorHook  # noqa: E402
from nanobot.agent.tools.registry import ToolRegistry  # type: ignore[import-untyped]  # noqa: E402
from task_store import TaskStoreProtocol  # noqa: E402
from task_store_factory import build_task_store  # noqa: E402
from task_tools import register_task_tools  # noqa: E402
from taskwarrior_store import TaskwarriorStore  # noqa: E402


FIXED_NOW = datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc)


def _run(coro: Coroutine[Any, Any, str]) -> str:
    return asyncio.run(coro)


def _titles(payload: dict[str, object]) -> set[str]:
    tasks = cast(list[dict[str, Any]], payload["tasks"])
    return {task["title"] for task in tasks}


@pytest.fixture()
def tw_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> dict[str, str]:
    tw_dir = tmp_path / "tw"
    env = {
        "TASKWARRIOR_ENABLED": "true",
        "TASKWARRIOR_DATA_DIR": str(tw_dir),
    }
    monkeypatch.setenv("TASKWARRIOR_ENABLED", "true")
    monkeypatch.setenv("TASKWARRIOR_DATA_DIR", str(tw_dir))
    return env


@pytest.fixture()
def tw_store(tw_env: dict[str, str], tmp_path: Path) -> TaskStoreProtocol:
    store = build_task_store(env=tw_env, repo_root=tmp_path)
    assert isinstance(store, TaskwarriorStore)
    return store


# ---------------------------------------------------------------------------
# Path 1: LLM tool registry
# ---------------------------------------------------------------------------

class TestToolRegistryPath:
    def test_create_then_list_via_tools(
        self, tw_store: TaskStoreProtocol,
    ) -> None:
        registry = ToolRegistry()
        register_task_tools(registry, tw_store)
        created = _run(registry.execute(
            "create_task", {"title": "Write report", "priority": "high"},
        ))
        assert "Write report" in created
        listed = _run(registry.execute("list_tasks", {}))
        assert "Write report" in listed

    def test_get_task_after_create(
        self, tw_store: TaskStoreProtocol,
    ) -> None:
        registry = ToolRegistry()
        register_task_tools(registry, tw_store)
        _run(registry.execute(
            "create_task", {"title": "Inspect me", "priority": "low"},
        ))
        task_id = tw_store.list_tasks()[0].id
        fetched = _run(registry.execute("get_task", {"task_id": task_id}))
        assert "Inspect me" in fetched

    def test_update_task_via_tool(
        self, tw_store: TaskStoreProtocol,
    ) -> None:
        registry = ToolRegistry()
        register_task_tools(registry, tw_store)
        _run(registry.execute(
            "create_task", {"title": "Rename me", "priority": "medium"},
        ))
        task_id = tw_store.list_tasks()[0].id
        updated = _run(registry.execute(
            "update_task",
            {"task_id": task_id, "title": "Renamed", "priority": "high"},
        ))
        assert "Renamed" in updated
        reloaded = tw_store.get_task(task_id)
        assert reloaded.title == "Renamed"
        assert reloaded.priority == "high"

    def test_complete_task_via_tool(
        self, tw_store: TaskStoreProtocol,
    ) -> None:
        registry = ToolRegistry()
        register_task_tools(registry, tw_store)
        _run(registry.execute(
            "create_task", {"title": "Finish me", "priority": "low"},
        ))
        task_id = tw_store.list_tasks()[0].id
        completed = _run(
            registry.execute("complete_task", {"task_id": task_id}),
        )
        assert "Finish me" in completed
        reloaded = tw_store.get_task(task_id)
        assert reloaded.status == "done"

    def test_full_crud_round_trip(
        self, tw_store: TaskStoreProtocol,
    ) -> None:
        registry = ToolRegistry()
        register_task_tools(registry, tw_store)
        _run(registry.execute(
            "create_task", {"title": "Round trip", "priority": "high"},
        ))
        task_id = tw_store.list_tasks()[0].id
        _run(registry.execute(
            "update_task",
            {"task_id": task_id, "status": "in_progress"},
        ))
        assert tw_store.get_task(task_id).status == "in_progress"
        _run(registry.execute("complete_task", {"task_id": task_id}))
        assert tw_store.get_task(task_id).status == "done"


# ---------------------------------------------------------------------------
# Path 2: Dashboard /tasks endpoint
# ---------------------------------------------------------------------------

class TestDashboardPath:
    def test_handle_tasks_reads_taskwarrior(
        self,
        tw_store: TaskStoreProtocol,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        tw_store.create_task("Dashboard A", "high", None, None, [])
        tw_store.create_task("Dashboard B", "low", None, None, [])
        monkeypatch.setattr(dashboard_api, "_repo_root", lambda: tmp_path)

        result = dashboard_api.handle_tasks(tmp_path / "data")
        titles = _titles(result)
        assert {"Dashboard A", "Dashboard B"}.issubset(titles)

    def test_handle_tasks_hides_completed(
        self,
        tw_store: TaskStoreProtocol,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        done = tw_store.create_task("Done already", "medium", None, None, [])
        tw_store.mark_complete(done.id)
        tw_store.create_task("Still open", "low", None, None, [])
        monkeypatch.setattr(dashboard_api, "_repo_root", lambda: tmp_path)

        result = dashboard_api.handle_tasks(tmp_path / "data")
        titles = _titles(result)
        assert "Still open" in titles
        assert "Done already" not in titles


# ---------------------------------------------------------------------------
# Path 3: MagicMirror hook feed refresh
# ---------------------------------------------------------------------------

def _build_mm_hook(
    tmp_path: Path, task_store: TaskStoreProtocol,
) -> tuple[MagicMirrorHook, Path]:
    feed_dir = tmp_path / "feeds"
    buffer_store = BufferStore(storage_path=tmp_path / "buffers.json")
    schedule_store = CheckInScheduleStore(
        storage_path=tmp_path / "checkins.json",
    )
    hook = MagicMirrorHook(
        webhook_base_url="http://127.0.0.1:8080",
        feed_dir=feed_dir,
        task_store=task_store,
        buffer_store=buffer_store,
        schedule_store=schedule_store,
        is_scheduled_session=lambda: True,
        get_cognitive_state=lambda: "baseline",
        get_current_datetime=lambda: FIXED_NOW,
    )
    return hook, feed_dir


class TestMagicMirrorPath:
    def test_refresh_writes_taskwarrior_rows(
        self,
        tw_store: TaskStoreProtocol,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "magicmirror_hook.send_alert_async", lambda payload, url: None,
        )
        tw_store.create_task("Via MM", "high", None, None, [])
        hook, feed_dir = _build_mm_hook(tmp_path, tw_store)
        asyncio.run(hook.before_iteration(MagicMock()))

        written = (feed_dir / "tasks.md").read_text(encoding="utf-8")
        expected = render_tasks_markdown(tw_store.list_tasks(), FIXED_NOW)
        assert written == expected
        assert "Via MM" in written

    def test_completion_moves_task_between_sections(
        self,
        tw_store: TaskStoreProtocol,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "magicmirror_hook.send_alert_async", lambda payload, url: None,
        )
        created = tw_store.create_task(
            "Move me", "medium", None, None, [],
        )
        hook, feed_dir = _build_mm_hook(tmp_path, tw_store)
        asyncio.run(hook.before_iteration(MagicMock()))
        first = (feed_dir / "tasks.md").read_text(encoding="utf-8")
        active_index = first.index("## Active")
        assert "Move me" in first[active_index:]

        tw_store.mark_complete(created.id)
        asyncio.run(hook.before_iteration(MagicMock()))
        second = (feed_dir / "tasks.md").read_text(encoding="utf-8")
        completed_index = second.index("## Completed today")
        assert "Move me" in second[completed_index:]


# ---------------------------------------------------------------------------
# Cross-path coherence: all three consumers see the same row
# ---------------------------------------------------------------------------

class TestCrossPathCoherence:
    def test_tool_create_visible_via_dashboard_and_mm(
        self,
        tw_store: TaskStoreProtocol,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "magicmirror_hook.send_alert_async", lambda payload, url: None,
        )
        monkeypatch.setattr(dashboard_api, "_repo_root", lambda: tmp_path)

        registry = ToolRegistry()
        register_task_tools(registry, tw_store)
        _run(registry.execute(
            "create_task",
            {"title": "Shared ledger row", "priority": "high"},
        ))

        dashboard_result = dashboard_api.handle_tasks(tmp_path / "data")
        assert "Shared ledger row" in _titles(dashboard_result)

        hook, feed_dir = _build_mm_hook(tmp_path, tw_store)
        asyncio.run(hook.before_iteration(MagicMock()))
        tasks_md = (feed_dir / "tasks.md").read_text(encoding="utf-8")
        assert "Shared ledger row" in tasks_md
