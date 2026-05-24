"""Disco Elysium voice configuration for the ADHD assistant.

Loads voice definitions from workspace/disco_voices.yaml, validates them
with Pydantic models, and provides pure functions for activation logic
and voice selection.

The module exposes pure functions and Pydantic models -- no global state.
"""

import logging
import os
from pathlib import Path

import yaml
from pydantic import BaseModel, model_validator

from state_detection import ALL_STATES

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class DiscoVoice(BaseModel):
    """One inner voice as defined in disco_voices.yaml."""

    display_name: str
    description: str
    tone: str
    speaks_when: list[str]
    example_lines: list[str]

    @model_validator(mode="after")
    def validate_speaks_when(self) -> "DiscoVoice":
        invalid = set(self.speaks_when) - ALL_STATES
        if invalid:
            raise ValueError(
                f"speaks_when contains unknown states: {sorted(invalid)}. "
                f"Valid states: {sorted(ALL_STATES)}"
            )
        return self


class DiscoConfig(BaseModel):
    """Complete disco configuration loaded from YAML."""

    enabled: bool
    activation_states: list[str]
    skip_intents: list[str]
    model: str
    max_voices: int
    first_voice: str
    voices: dict[str, DiscoVoice]

    @model_validator(mode="after")
    def validate_config(self) -> "DiscoConfig":
        invalid_states = set(self.activation_states) - ALL_STATES
        if invalid_states:
            raise ValueError(
                f"activation_states contains unknown states: "
                f"{sorted(invalid_states)}. Valid states: {sorted(ALL_STATES)}"
            )
        if self.first_voice not in self.voices:
            raise ValueError(
                f"first_voice '{self.first_voice}' not found in voices dict. "
                f"Available voices: {sorted(self.voices.keys())}"
            )
        if self.max_voices < 1:
            raise ValueError(
                f"max_voices must be >= 1, got {self.max_voices}"
            )
        if self.max_voices > len(self.voices):
            raise ValueError(
                f"max_voices ({self.max_voices}) exceeds available voices "
                f"({len(self.voices)})"
            )
        return self


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_disco_config(config_path: Path) -> DiscoConfig:
    """Load and validate disco voice configuration from a YAML file."""
    if not config_path.exists():
        raise FileNotFoundError(
            f"Disco config not found at {config_path}. "
            f"Expected workspace/disco_voices.yaml in the repo root."
        )
    raw = config_path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    if not isinstance(data, dict) or "voices" not in data:
        raise ValueError(
            f"Disco config at {config_path} must have a top-level 'voices' key"
        )
    return DiscoConfig.model_validate(data)


# ---------------------------------------------------------------------------
# Env var toggle
# ---------------------------------------------------------------------------

def is_disco_enabled() -> bool:
    """Check whether disco voice layer is enabled via environment variable."""
    return os.environ.get("VOICE_DISCO_ENABLED", "").lower() in (
        "true", "1", "yes"
    )


# ---------------------------------------------------------------------------
# Activation logic
# ---------------------------------------------------------------------------

def should_activate_disco(
    state: str,
    intent: str | None,
    config: DiscoConfig,
) -> bool:
    """Decide whether the disco voice layer should activate.

    Returns True only when all conditions are met:
    1. VOICE_DISCO_ENABLED env var is truthy
    2. Current cognitive state is in the configured activation_states
    3. Intent (if provided) is not in the configured skip_intents
    """
    if not is_disco_enabled():
        return False
    if state not in config.activation_states:
        return False
    if intent is not None and intent in config.skip_intents:
        return False
    return True


# ---------------------------------------------------------------------------
# Voice selection
# ---------------------------------------------------------------------------

def select_initial_voice(config: DiscoConfig) -> DiscoVoice:
    """Return the configured first voice (Volition by default)."""
    return config.voices[config.first_voice]
