"""Tests for Cabinet service registration via create_hooks.

The legacy MagicMirrorHook is gone — feeds, voices.md, and alert evaluation
now live in CabinetRenderLoop. These tests verify create_hooks wires the
render loop / voice buffer / top-up generator into ``cabinet_services`` when
the Cabinet is enabled, and stays a no-op (back-compat) otherwise.
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


class TestCabinetRenderLoopRegistration:
    """create_hooks populates cabinet_services['render_loop'] when enabled."""

    def _call(
        self,
        stores: dict[str, object],
        states_yaml: Path,
        tmp_data_dir: Path,
        tmp_path: Path,
        env: dict[str, str] | None,
        services: dict[str, object] | None,
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
            repo_root=tmp_path,
            env=env,
            cabinet_services=services,
        )

    def test_loop_built_when_enabled(
        self, tmp_data_dir: Path, states_yaml: Path, tmp_path: Path,
    ) -> None:
        from cabinet_render_loop import CabinetRenderLoop

        stores = create_stores(tmp_data_dir)
        services: dict[str, object] = {}
        self._call(
            stores, states_yaml, tmp_data_dir, tmp_path,
            {"CABINET_ENABLED": "true"}, services,
        )
        loop = services.get("render_loop")
        assert isinstance(loop, CabinetRenderLoop)
        assert loop._feed_dir == tmp_path / "cabinet" / "feeds"

    def test_no_loop_when_disabled(
        self, tmp_data_dir: Path, states_yaml: Path, tmp_path: Path,
    ) -> None:
        stores = create_stores(tmp_data_dir)
        services: dict[str, object] = {}
        self._call(
            stores, states_yaml, tmp_data_dir, tmp_path,
            {"CABINET_ENABLED": "false"}, services,
        )
        assert "render_loop" not in services

    def test_chain_builds_when_services_not_provided(
        self, tmp_data_dir: Path, states_yaml: Path, tmp_path: Path,
    ) -> None:
        # Back-compat: callers that pass no cabinet_services dict still get a
        # valid chain (no MM hook, no crash).
        stores = create_stores(tmp_data_dir)
        hooks = self._call(
            stores, states_yaml, tmp_data_dir, tmp_path,
            {"CABINET_ENABLED": "true"}, None,
        )
        names = _hook_names(hooks)
        assert "StateResponseHook" in names
        assert "MagicMirrorHook" not in names

    def test_voice_generator_built_with_disco_and_data_dir(
        self, tmp_data_dir: Path, states_yaml: Path, tmp_path: Path,
    ) -> None:
        from voice_buffer import VoiceBuffer
        from voice_generator import VoiceTopUpGenerator

        _write_disco_yaml(states_yaml.parent)
        stores = create_stores(tmp_data_dir)
        services: dict[str, object] = {}
        create_hooks(
            stores=stores, states_path=states_yaml,
            state_file_path=tmp_data_dir / "state.json", provider=MagicMock(),
            model="test-model", session_flag=SessionFlag(), tz=ZoneInfo("UTC"),
            workspace=states_yaml.parent, repo_root=tmp_path,
            env={"CABINET_ENABLED": "true"}, cabinet_services=services,
            data_dir=tmp_data_dir,
        )
        assert isinstance(services.get("voice_buffer"), VoiceBuffer)
        assert isinstance(services.get("voice_generator"), VoiceTopUpGenerator)

    def test_no_voice_generator_without_data_dir(
        self, tmp_data_dir: Path, states_yaml: Path, tmp_path: Path,
    ) -> None:
        _write_disco_yaml(states_yaml.parent)
        stores = create_stores(tmp_data_dir)
        services: dict[str, object] = {}
        self._call(
            stores, states_yaml, tmp_data_dir, tmp_path,
            {"CABINET_ENABLED": "true"}, services,
        )  # _call passes no data_dir
        assert "render_loop" in services
        assert "voice_generator" not in services
