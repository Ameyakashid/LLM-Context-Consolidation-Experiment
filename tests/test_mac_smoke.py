"""Baseline Mac smoke + graceful shutdown (Part A.2 of sub-05).

Module-skipped on non-Darwin hosts — this is the ONE legitimate
``sys.platform`` branch in the codebase (AC #1 of sub-05).
Phase 2 flag cells live in ``tests/test_mac_smoke_phase2.py``.
Shared helpers live in ``tests/_mac_smoke_harness.py`` because the two
test files both drive ``start.py`` with the same subprocess posture.
"""

from __future__ import annotations

import sys

import pytest

if sys.platform != "darwin":
    pytest.skip(
        "tests/test_mac_smoke.py is Mac-only (AC #1 of sub-05)",
        allow_module_level=True,
    )

# ruff: noqa: E402
from tests._mac_smoke_harness import (
    BASELINE_MARKERS,
    SHUTDOWN_DEADLINE_S,
    TRACEBACK_SIGNAL,
    require_venv,
    run_until_markers,
    smoke_env,
    traceback_excerpt,
)


class TestBaselineSmoke:
    """Flags off, asserts 2026-04-16 baseline log markers reproduce on Mac."""

    def test_baseline_markers_appear(self) -> None:
        require_venv()
        result = run_until_markers(BASELINE_MARKERS, env=smoke_env())
        missing = [m for m, seen in result.markers_seen.items() if not seen]
        assert not missing, (
            f"Baseline markers missing after {result.boot_seconds:.1f}s: "
            f"{missing}"
        )

    def test_baseline_no_traceback(self) -> None:
        require_venv()
        result = run_until_markers(BASELINE_MARKERS, env=smoke_env())
        assert TRACEBACK_SIGNAL not in result.stdout, (
            f"Traceback in start.py output:\n"
            f"{traceback_excerpt(result.stdout)}"
        )

    def test_graceful_shutdown_within_deadline(self) -> None:
        require_venv()
        result = run_until_markers(BASELINE_MARKERS, env=smoke_env())
        assert result.shutdown_seconds <= SHUTDOWN_DEADLINE_S, (
            f"Shutdown took {result.shutdown_seconds:.1f}s "
            f"(deadline {SHUTDOWN_DEADLINE_S:.0f}s) — SIGINT reap regressed."
        )
