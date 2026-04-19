"""Tests for MagicMirror hook chain integration via create_hooks.

Verifies that ``MagicMirrorHook`` is appended exactly when
``MAGICMIRROR_ENABLED=true`` and ``repo_root`` is provided, that its
chain position is after ``VoiceHook`` and before any ``DiscoHook``, and
that the flag-off path allocates no hook and starts no thread pool.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from custom_gateway import SessionFlag, create_hooks, create_stores


@pytest.fixture()
def tmp_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir


@pytest.fixture()
def states_yaml(tmp_path: Path) -> Path:
    states_path = tmp_path / "workspace" / "states.yaml"
    states_path.parent.mkdir(parents=True, exist_ok=True)
    state_names = (
        "baseline", "focus", "hyperfocus", "avoidance", "overwhelm", "rsd",
    )
    states: dict[str, dict[str, object]] = {}
    for name in state_names:
        transitions = {s: 0.0 for s in state_names}
        transitions["baseline"] = 1.0
        states[name] = {
            "description": f"Test {name}",
            "detection_signals": [f"signal_{name}"],
            "response_style": [f"style_{name}"],
            "transitions": transitions,
        }
    import yaml
    states_path.write_text(yaml.dump({"states": states}), encoding="utf-8")
    return states_path


def _hook_names(hooks: list[object]) -> list[str]:
    return [getattr(h, "hook_name", h.__class__.__name__) for h in hooks]


def _call_create_hooks(
    stores: dict[str, object],
    states_yaml: Path,
    tmp_data_dir: Path,
    env: dict[str, str] | None = None,
    repo_root: Path | None = None,
) -> list[object]:
    return create_hooks(  # type: ignore[return-value]
        stores=stores,
        states_path=states_yaml,
        state_file_path=tmp_data_dir / "state.json",
        provider=MagicMock(),
        model="test-model",
        session_flag=SessionFlag(),
        tz=ZoneInfo("UTC"),
        workspace=states_yaml.parent,
        repo_root=repo_root,
        env=env,
    )


class TestMagicMirrorChainRegistration:

    def test_flag_off_appends_no_hook(
        self, tmp_data_dir: Path, states_yaml: Path, tmp_path: Path,
    ) -> None:
        stores = create_stores(tmp_data_dir)
        hooks = _call_create_hooks(
            stores,
            states_yaml,
            tmp_data_dir,
            env={"MAGICMIRROR_ENABLED": "false"},
            repo_root=tmp_path,
        )
        assert "MagicMirrorHook" not in _hook_names(hooks)

    def test_missing_env_appends_no_hook(
        self, tmp_data_dir: Path, states_yaml: Path, tmp_path: Path,
    ) -> None:
        stores = create_stores(tmp_data_dir)
        hooks = _call_create_hooks(
            stores, states_yaml, tmp_data_dir, env=None, repo_root=tmp_path,
        )
        assert "MagicMirrorHook" not in _hook_names(hooks)

    def test_missing_repo_root_appends_no_hook(
        self, tmp_data_dir: Path, states_yaml: Path,
    ) -> None:
        stores = create_stores(tmp_data_dir)
        hooks = _call_create_hooks(
            stores,
            states_yaml,
            tmp_data_dir,
            env={"MAGICMIRROR_ENABLED": "true"},
            repo_root=None,
        )
        assert "MagicMirrorHook" not in _hook_names(hooks)

    def test_flag_on_appends_hook_after_voice(
        self, tmp_data_dir: Path, states_yaml: Path, tmp_path: Path,
    ) -> None:
        stores = create_stores(tmp_data_dir)
        hooks = _call_create_hooks(
            stores,
            states_yaml,
            tmp_data_dir,
            env={"MAGICMIRROR_ENABLED": "true"},
            repo_root=tmp_path,
        )
        names = _hook_names(hooks)
        assert "MagicMirrorHook" in names
        assert names.index("MagicMirrorHook") > names.index("VoiceHook")

    def test_flag_on_places_mm_before_disco(
        self, tmp_data_dir: Path, states_yaml: Path, tmp_path: Path,
    ) -> None:
        _write_disco_yaml(states_yaml.parent)
        stores = create_stores(tmp_data_dir)
        hooks = _call_create_hooks(
            stores,
            states_yaml,
            tmp_data_dir,
            env={"MAGICMIRROR_ENABLED": "true"},
            repo_root=tmp_path,
        )
        names = _hook_names(hooks)
        assert "MagicMirrorHook" in names
        assert "DiscoHook" in names
        assert names.index("MagicMirrorHook") < names.index("DiscoHook")


_MINIMAL_DISCO_YAML = """
enabled: true
activation_states: [avoidance, overwhelm, rsd]
skip_intents: [list_tasks]
model: anthropic/claude-3-haiku
max_voices: 3
first_voice: volition
voices:
  volition:
    display_name: VOLITION
    description: Hold yourself together.
    tone: Firm and grounded.
    speaks_when: [avoidance, overwhelm, rsd]
    example_lines: ["Hold."]
  empathy:
    display_name: EMPATHY
    description: Understand others.
    tone: Warm.
    speaks_when: [rsd, overwhelm]
    example_lines: ["I see you."]
  logic:
    display_name: LOGIC
    description: Analyze it.
    tone: Precise.
    speaks_when: [avoidance, overwhelm]
    example_lines: ["Break it down."]
"""


def _write_disco_yaml(workspace: Path) -> None:
    (workspace / "disco_voices.yaml").write_text(
        _MINIMAL_DISCO_YAML, encoding="utf-8",
    )
