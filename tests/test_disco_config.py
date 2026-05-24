"""Tests for disco_config.py -- config loading, activation logic, voice selection."""

import os
from pathlib import Path

import pytest

from disco_config import (
    DiscoConfig,
    DiscoVoice,
    is_disco_enabled,
    load_disco_config,
    select_initial_voice,
    should_activate_disco,
)

YAML_PATH = Path(__file__).resolve().parent.parent / "workspace" / "disco_voices.yaml"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def config() -> DiscoConfig:
    """Load the real disco_voices.yaml for integration tests."""
    return load_disco_config(YAML_PATH)


@pytest.fixture()
def minimal_config() -> DiscoConfig:
    """A minimal valid config for unit tests (no file I/O)."""
    return DiscoConfig(
        enabled=True,
        activation_states=["avoidance", "overwhelm", "rsd"],
        skip_intents=["list_tasks", "create_task", "simple_query"],
        model="anthropic/claude-3-haiku",
        max_voices=1,
        first_voice="volition",
        voices={
            "volition": DiscoVoice(
                display_name="VOLITION",
                description="Hold yourself together.",
                tone="Firm, grounded.",
                speaks_when=["avoidance", "overwhelm", "rsd"],
                example_lines=["Hold. Don't let go."],
            ),
        },
    )


# ---------------------------------------------------------------------------
# Config loading tests
# ---------------------------------------------------------------------------

class TestLoadDiscoConfig:
    def test_load_valid_config(self, config: DiscoConfig) -> None:
        assert len(config.voices) == 4

    def test_load_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="Disco config not found"):
            load_disco_config(tmp_path / "nonexistent.yaml")

    def test_load_invalid_yaml(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("just a string, not a mapping", encoding="utf-8")
        with pytest.raises(ValueError, match="top-level 'voices' key"):
            load_disco_config(bad_file)

    def test_load_missing_voices_key(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "missing_voices.yaml"
        bad_file.write_text(
            "enabled: true\nactivation_states: [avoidance]\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="top-level 'voices' key"):
            load_disco_config(bad_file)

    def test_load_invalid_first_voice(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad_first.yaml"
        bad_file.write_text(
            "enabled: true\n"
            "activation_states: [avoidance]\n"
            "skip_intents: []\n"
            "model: test\n"
            "max_voices: 1\n"
            "first_voice: nonexistent\n"
            "voices:\n"
            "  volition:\n"
            "    display_name: V\n"
            "    description: d\n"
            "    tone: t\n"
            "    speaks_when: [avoidance]\n"
            "    example_lines: [x]\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="first_voice 'nonexistent' not found"):
            load_disco_config(bad_file)

    def test_load_invalid_activation_state(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad_state.yaml"
        bad_file.write_text(
            "enabled: true\n"
            "activation_states: [avoidance, fake_state]\n"
            "skip_intents: []\n"
            "model: test\n"
            "max_voices: 1\n"
            "first_voice: volition\n"
            "voices:\n"
            "  volition:\n"
            "    display_name: V\n"
            "    description: d\n"
            "    tone: t\n"
            "    speaks_when: [avoidance]\n"
            "    example_lines: [x]\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="unknown states"):
            load_disco_config(bad_file)


# ---------------------------------------------------------------------------
# Voice validation tests
# ---------------------------------------------------------------------------

class TestVoiceValidation:
    def test_config_has_four_voices(self, config: DiscoConfig) -> None:
        expected = {"volition", "empathy", "logic", "inland_empire"}
        assert set(config.voices.keys()) == expected

    def test_each_voice_has_required_fields(self, config: DiscoConfig) -> None:
        for voice_key, voice in config.voices.items():
            assert voice.display_name, f"{voice_key} missing display_name"
            assert voice.description, f"{voice_key} missing description"
            assert voice.tone, f"{voice_key} missing tone"
            assert len(voice.speaks_when) > 0, f"{voice_key} has empty speaks_when"
            assert len(voice.example_lines) > 0, f"{voice_key} has empty example_lines"

    def test_config_has_volition(self, config: DiscoConfig) -> None:
        assert "volition" in config.voices

    def test_config_first_voice_is_volition(self, config: DiscoConfig) -> None:
        assert config.first_voice == "volition"

    def test_invalid_speaks_when_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown states"):
            DiscoVoice(
                display_name="BAD",
                description="d",
                tone="t",
                speaks_when=["not_a_real_state"],
                example_lines=["x"],
            )


# ---------------------------------------------------------------------------
# Activation logic tests
# ---------------------------------------------------------------------------

class TestShouldActivateDisco:
    """All activation tests set VOICE_DISCO_ENABLED=true via monkeypatch."""

    def test_activate_avoidance(
        self, minimal_config: DiscoConfig, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VOICE_DISCO_ENABLED", "true")
        assert should_activate_disco("avoidance", None, minimal_config) is True

    def test_activate_overwhelm(
        self, minimal_config: DiscoConfig, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VOICE_DISCO_ENABLED", "true")
        assert should_activate_disco("overwhelm", None, minimal_config) is True

    def test_activate_rsd(
        self, minimal_config: DiscoConfig, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VOICE_DISCO_ENABLED", "true")
        assert should_activate_disco("rsd", None, minimal_config) is True

    def test_not_activate_baseline(
        self, minimal_config: DiscoConfig, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VOICE_DISCO_ENABLED", "true")
        assert should_activate_disco("baseline", None, minimal_config) is False

    def test_not_activate_focus(
        self, minimal_config: DiscoConfig, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VOICE_DISCO_ENABLED", "true")
        assert should_activate_disco("focus", None, minimal_config) is False

    def test_not_activate_hyperfocus(
        self, minimal_config: DiscoConfig, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VOICE_DISCO_ENABLED", "true")
        assert should_activate_disco("hyperfocus", None, minimal_config) is False

    def test_not_activate_skip_intent_list_tasks(
        self, minimal_config: DiscoConfig, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VOICE_DISCO_ENABLED", "true")
        assert should_activate_disco("avoidance", "list_tasks", minimal_config) is False

    def test_not_activate_skip_intent_create_task(
        self, minimal_config: DiscoConfig, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VOICE_DISCO_ENABLED", "true")
        assert should_activate_disco("avoidance", "create_task", minimal_config) is False

    def test_not_activate_skip_intent_simple_query(
        self, minimal_config: DiscoConfig, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VOICE_DISCO_ENABLED", "true")
        assert should_activate_disco("avoidance", "simple_query", minimal_config) is False

    def test_activate_none_intent(
        self, minimal_config: DiscoConfig, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VOICE_DISCO_ENABLED", "true")
        assert should_activate_disco("avoidance", None, minimal_config) is True

    def test_not_activate_disabled_env(
        self, minimal_config: DiscoConfig, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VOICE_DISCO_ENABLED", "false")
        assert should_activate_disco("avoidance", None, minimal_config) is False

    def test_not_activate_missing_env(
        self, minimal_config: DiscoConfig, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("VOICE_DISCO_ENABLED", raising=False)
        assert should_activate_disco("avoidance", None, minimal_config) is False

    def test_activate_non_skip_intent(
        self, minimal_config: DiscoConfig, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("VOICE_DISCO_ENABLED", "true")
        assert should_activate_disco("avoidance", "chat", minimal_config) is True


# ---------------------------------------------------------------------------
# Env var toggle tests
# ---------------------------------------------------------------------------

class TestIsDiscoEnabled:
    def test_enabled_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VOICE_DISCO_ENABLED", "true")
        assert is_disco_enabled() is True

    def test_enabled_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VOICE_DISCO_ENABLED", "1")
        assert is_disco_enabled() is True

    def test_enabled_yes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VOICE_DISCO_ENABLED", "yes")
        assert is_disco_enabled() is True

    def test_enabled_true_uppercase(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VOICE_DISCO_ENABLED", "TRUE")
        assert is_disco_enabled() is True

    def test_disabled_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VOICE_DISCO_ENABLED", "false")
        assert is_disco_enabled() is False

    def test_disabled_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VOICE_DISCO_ENABLED", "0")
        assert is_disco_enabled() is False

    def test_disabled_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VOICE_DISCO_ENABLED", "")
        assert is_disco_enabled() is False

    def test_disabled_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("VOICE_DISCO_ENABLED", raising=False)
        assert is_disco_enabled() is False


# ---------------------------------------------------------------------------
# Voice selection tests
# ---------------------------------------------------------------------------

class TestSelectInitialVoice:
    def test_returns_volition(self, config: DiscoConfig) -> None:
        voice = select_initial_voice(config)
        assert voice is config.voices["volition"]

    def test_returns_volition_display_name(self, config: DiscoConfig) -> None:
        voice = select_initial_voice(config)
        assert voice.display_name == "VOLITION"

    def test_returns_configured_first_voice(
        self, minimal_config: DiscoConfig,
    ) -> None:
        voice = select_initial_voice(minimal_config)
        assert voice.display_name == "VOLITION"
