"""Tests for create_hooks DiscoHook conditional registration."""

from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from custom_gateway import SessionFlag, create_hooks, create_stores


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


@pytest.fixture()
def tmp_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir


@pytest.fixture()
def states_yaml(tmp_path: Path) -> Path:
    states_path = tmp_path / "workspace" / "states.yaml"
    states_path.parent.mkdir(parents=True, exist_ok=True)
    states: dict[str, dict[str, object]] = {}
    for state_name in ("baseline", "focus", "hyperfocus", "avoidance", "overwhelm", "rsd"):
        transitions = {s: 0.0 for s in ("baseline", "focus", "hyperfocus", "avoidance", "overwhelm", "rsd")}
        transitions["baseline"] = 1.0
        states[state_name] = {
            "description": f"Test {state_name}",
            "detection_signals": [f"signal_{state_name}"],
            "response_style": [f"style_{state_name}"],
            "transitions": transitions,
        }
    import yaml
    states_path.write_text(yaml.dump({"states": states}), encoding="utf-8")
    return states_path


class TestDiscoHookRegistration:
    def test_appends_disco_hook_when_yaml_present(
        self, tmp_data_dir: Path, states_yaml: Path,
    ) -> None:
        disco_yaml = states_yaml.parent / "disco_voices.yaml"
        disco_yaml.write_text(_MINIMAL_DISCO_YAML, encoding="utf-8")
        stores = create_stores(tmp_data_dir)
        provider = MagicMock()
        session_flag = SessionFlag()
        hooks = create_hooks(
            stores=stores,
            states_path=states_yaml,
            state_file_path=tmp_data_dir / "state.json",
            provider=provider,
            model="test-model",
            session_flag=session_flag,
            tz=ZoneInfo("UTC"),
        )
        assert len(hooks) == 6
        names = [getattr(h, "hook_name", h.__class__.__name__) for h in hooks]
        assert names[-1] == "DiscoHook"

    def test_no_disco_hook_when_yaml_absent(
        self, tmp_data_dir: Path, states_yaml: Path,
    ) -> None:
        stores = create_stores(tmp_data_dir)
        provider = MagicMock()
        session_flag = SessionFlag()
        hooks = create_hooks(
            stores=stores,
            states_path=states_yaml,
            state_file_path=tmp_data_dir / "state.json",
            provider=provider,
            model="test-model",
            session_flag=session_flag,
            tz=ZoneInfo("UTC"),
        )
        assert len(hooks) == 5
        names = [getattr(h, "hook_name", h.__class__.__name__) for h in hooks]
        assert "DiscoHook" not in names
