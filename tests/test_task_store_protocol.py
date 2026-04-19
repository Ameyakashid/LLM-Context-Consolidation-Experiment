"""Runtime parity: TaskStore and TaskwarriorStore both satisfy TaskStoreProtocol.

Signature-level parity is already enforced by
``tests/test_taskwarrior_store_contract.py``; this file adds the
runtime ``isinstance`` check on the ``@runtime_checkable`` Protocol and
a direct inspection-based re-assertion of each method's signature so the
factory's return-type claim is verified end-to-end.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from task_store import TaskStore, TaskStoreProtocol

PROTOCOL_METHODS = (
    "create_task",
    "get_task",
    "list_tasks",
    "list_tasks_by_status",
    "update_task",
    "mark_complete",
    "delete_task",
    "reload",
)


class TestProtocolSurface:
    @pytest.mark.parametrize("method", PROTOCOL_METHODS)
    def test_protocol_declares_method(self, method: str) -> None:
        assert hasattr(TaskStoreProtocol, method)

    def test_exactly_eight_public_methods(self) -> None:
        protocol_members = {
            name for name in dir(TaskStoreProtocol)
            if not name.startswith("_")
        }
        assert protocol_members == set(PROTOCOL_METHODS)


class TestTaskStoreSatisfiesProtocol:
    def test_json_backend_passes_isinstance(self, tmp_path: Path) -> None:
        store = TaskStore(storage_path=tmp_path / "tasks.json")
        assert isinstance(store, TaskStoreProtocol)

    @pytest.mark.parametrize("method", PROTOCOL_METHODS)
    def test_json_method_signature_matches(self, method: str) -> None:
        protocol_sig = inspect.signature(
            getattr(TaskStoreProtocol, method), eval_str=True,
        )
        concrete_sig = inspect.signature(
            getattr(TaskStore, method), eval_str=True,
        )
        assert concrete_sig.parameters == protocol_sig.parameters


class TestTaskwarriorStoreSatisfiesProtocol:
    def test_tw_class_has_all_methods(self) -> None:
        pytest.importorskip("tasklib")
        from taskwarrior_store import TaskwarriorStore
        for method in PROTOCOL_METHODS:
            assert callable(getattr(TaskwarriorStore, method))

    @pytest.mark.parametrize("method", PROTOCOL_METHODS)
    def test_tw_method_signature_matches(self, method: str) -> None:
        pytest.importorskip("tasklib")
        from taskwarrior_store import TaskwarriorStore
        protocol_sig = inspect.signature(
            getattr(TaskStoreProtocol, method), eval_str=True,
        )
        concrete_sig = inspect.signature(
            getattr(TaskwarriorStore, method), eval_str=True,
        )
        assert concrete_sig.parameters == protocol_sig.parameters


class TestProtocolRejectsMissingMethods:
    def test_bare_object_fails(self) -> None:
        not_a_store = MagicMock(spec=[])
        assert not isinstance(not_a_store, TaskStoreProtocol)

    def test_partial_impl_fails(self) -> None:
        partial = MagicMock(spec=["create_task", "list_tasks"])
        assert not isinstance(partial, TaskStoreProtocol)
