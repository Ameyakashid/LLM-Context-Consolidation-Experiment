"""Tests for ``is_pulse_engine_enabled`` truthiness contract.

Pins the feature flag to the majority project convention
(``.strip().lower() == "true"``). Deviations here — notably accepting
``"1"`` or ``"yes"`` — would put the Pulse rollout out of step with the
four existing ``is_*_enabled`` helpers (gcal / magicmirror / syncall /
taskwarrior) and break verification AC #6.
"""

from __future__ import annotations

import pytest

from pulse_checkin_store import is_pulse_engine_enabled


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, False),
        ({"PULSE_ENGINE_ENABLED": "true"}, True),
        ({"PULSE_ENGINE_ENABLED": "TRUE"}, True),
        ({"PULSE_ENGINE_ENABLED": "True"}, True),
        ({"PULSE_ENGINE_ENABLED": " true "}, True),
        ({"PULSE_ENGINE_ENABLED": "\ttrue\n"}, True),
        ({"PULSE_ENGINE_ENABLED": "false"}, False),
        ({"PULSE_ENGINE_ENABLED": "FALSE"}, False),
        ({"PULSE_ENGINE_ENABLED": ""}, False),
        ({"PULSE_ENGINE_ENABLED": "0"}, False),
        ({"PULSE_ENGINE_ENABLED": "1"}, False),
        ({"PULSE_ENGINE_ENABLED": "yes"}, False),
        ({"PULSE_ENGINE_ENABLED": "no"}, False),
        ({"PULSE_ENGINE_ENABLED": "on"}, False),
        ({"PULSE_ENGINE_ENABLED": "off"}, False),
        ({"PULSE_ENGINE_ENABLED": "truthy"}, False),
        ({"UNRELATED": "true"}, False),
    ],
)
def test_is_pulse_engine_enabled(env: dict[str, str], expected: bool) -> None:
    assert is_pulse_engine_enabled(env) is expected


def test_is_pulse_engine_enabled_accepts_os_environ_like_mapping() -> None:
    """``Mapping[str, str]`` must cover ``os.environ`` without a copy."""

    class ReadOnlyEnv:
        def __init__(self, data: dict[str, str]) -> None:
            self._data = data

        def __getitem__(self, key: str) -> str:
            return self._data[key]

        def __iter__(self):  # type: ignore[no-untyped-def]
            return iter(self._data)

        def __len__(self) -> int:
            return len(self._data)

        def get(self, key: str, default: str = "") -> str:
            return self._data.get(key, default)

    env = ReadOnlyEnv({"PULSE_ENGINE_ENABLED": "true"})
    assert is_pulse_engine_enabled(env) is True  # type: ignore[arg-type]
