"""Payload-model and URL-validation tests for the MagicMirror webhook client.

Client-side send/async/pool tests live in
``test_magicmirror_webhook_client.py`` so neither file breaches the
300-line cap.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from magicmirror_setup import MAGICMIRROR_WEBHOOK_TEMPLATE_NAMES
from magicmirror_webhook import (
    BufferAlertPayload,
    MissedCheckinPayload,
    StateChangePayload,
    WebhookPayload,
    _build_alert_url,
    validate_local_url,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = REPO_ROOT / "magicmirror" / "config" / "config.js.template"
_PLACEHOLDER_RX = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _sample_state_change() -> StateChangePayload:
    return StateChangePayload(
        message="Shifted from focus to avoidance. Want to try a tiny next step?",
        from_state="focus",
        to_state="avoidance",
        timestamp=datetime(2026, 4, 19, 14, 30, tzinfo=timezone.utc),
    )


def _sample_buffer_alert() -> BufferAlertPayload:
    return BufferAlertPayload(
        message="Only 2 left of 10. Consider refilling soon.",
        buffer_name="dog food",
        current_level=2,
        capacity=10,
        threshold=3,
        timestamp=datetime(2026, 4, 19, 9, 15, tzinfo=timezone.utc),
    )


def _sample_missed_checkin() -> MissedCheckinPayload:
    return MissedCheckinPayload(
        message="Morning plan slot passed without a check-in.",
        checkin_type="morning_plan",
        due_at=datetime(2026, 4, 19, 9, 0, tzinfo=timezone.utc),
        detected_at=datetime(2026, 4, 19, 11, 5, tzinfo=timezone.utc),
    )


_SAMPLES: tuple[WebhookPayload, ...] = (
    _sample_state_change(),
    _sample_buffer_alert(),
    _sample_missed_checkin(),
)


def _extract_placeholders_for_template(
    template_source: str, template_name: str
) -> set[str]:
    block_rx = re.compile(
        r'templateName:\s*"' + re.escape(template_name) + r'".*?\}\s*[,\]]',
        re.DOTALL,
    )
    match = block_rx.search(template_source)
    assert match, f"Template block for {template_name!r} not found"
    return set(_PLACEHOLDER_RX.findall(match.group(0)))


class TestPayloadTemplateNames:
    def test_state_change_template_matches_setup(self) -> None:
        assert StateChangePayload.template_name == "state_change"
        assert StateChangePayload.template_name in MAGICMIRROR_WEBHOOK_TEMPLATE_NAMES

    def test_buffer_alert_template_matches_setup(self) -> None:
        assert BufferAlertPayload.template_name == "buffer_alert"
        assert BufferAlertPayload.template_name in MAGICMIRROR_WEBHOOK_TEMPLATE_NAMES

    def test_missed_checkin_template_matches_setup(self) -> None:
        assert MissedCheckinPayload.template_name == "missed_checkin"
        assert MissedCheckinPayload.template_name in MAGICMIRROR_WEBHOOK_TEMPLATE_NAMES

    def test_no_duplicate_template_name_literal_in_module(self) -> None:
        source = (REPO_ROOT / "magicmirror_webhook.py").read_text(encoding="utf-8")
        for name in MAGICMIRROR_WEBHOOK_TEMPLATE_NAMES:
            literal = f'"{name}"'
            assert literal not in source, (
                f"Template name {name!r} duplicated in magicmirror_webhook.py; "
                f"import MAGICMIRROR_WEBHOOK_TEMPLATE_NAMES from magicmirror_setup instead."
            )


class TestPayloadJsonBody:
    def test_state_change_body_contains_mustache_keys(self) -> None:
        body = _sample_state_change().to_json_body()
        assert body["message"] == (
            "Shifted from focus to avoidance. Want to try a tiny next step?"
        )
        assert body["state"] == "avoidance"
        assert body["from_state"] == "focus"
        assert body["timestamp"] == "2026-04-19T14:30:00+00:00"

    def test_buffer_alert_body_contains_mustache_keys(self) -> None:
        body = _sample_buffer_alert().to_json_body()
        assert body["message"] == "Only 2 left of 10. Consider refilling soon."
        assert body["buffer"] == "dog food"
        assert body["level"] == 2
        assert body["capacity"] == 10
        assert body["threshold"] == 3

    def test_missed_checkin_body_contains_mustache_keys(self) -> None:
        body = _sample_missed_checkin().to_json_body()
        assert body["message"] == "Morning plan slot passed without a check-in."
        assert body["checkin_type"] == "morning_plan"
        assert body["due_at"] == "2026-04-19T09:00:00+00:00"
        assert body["detected_at"] == "2026-04-19T11:05:00+00:00"

    @pytest.mark.parametrize("payload", _SAMPLES)
    def test_body_always_includes_message(self, payload: WebhookPayload) -> None:
        body = payload.to_json_body()
        assert "message" in body
        assert isinstance(body["message"], str)
        assert body["message"]

    @pytest.mark.parametrize("payload", _SAMPLES)
    def test_body_covers_every_template_placeholder(
        self, payload: WebhookPayload
    ) -> None:
        template_source = TEMPLATE_PATH.read_text(encoding="utf-8")
        placeholders = _extract_placeholders_for_template(
            template_source, payload.template_name
        )
        body_keys = set(payload.to_json_body().keys())
        missing = placeholders - body_keys
        assert not missing, (
            f"Template {payload.template_name!r} body references "
            f"{sorted(missing)}, but {type(payload).__name__}.to_json_body() "
            f"emits {sorted(body_keys)}. Overlay would render literal "
            f"{{{{X}}}} markup."
        )


class TestValidateLocalUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1:8080",
            "http://127.0.0.1:8080/webhook",
            "http://localhost:8080",
            "http://LOCALHOST:8080/webhook",
            "http://[::1]:8080",
            "http://127.1.2.3:9000",
        ],
    )
    def test_accepts_loopback(self, url: str) -> None:
        validate_local_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://192.168.1.50:8080",
            "http://10.0.0.1:8080",
            "http://172.16.0.1:8080",
            "http://example.com:8080",
            "http://203.0.113.7/webhook",
            "http://0.0.0.0:8080",
        ],
    )
    def test_rejects_non_loopback(self, url: str) -> None:
        with pytest.raises(ValueError) as exc_info:
            validate_local_url(url)
        message = str(exc_info.value)
        assert "only loopback urls are accepted" in message.lower()

    def test_rejection_names_rejected_host(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            validate_local_url("http://192.168.1.50:8080")
        assert "192.168.1.50" in str(exc_info.value)

    def test_rejects_url_without_host(self) -> None:
        with pytest.raises(ValueError):
            validate_local_url("not-a-url")


class TestBuildAlertUrl:
    def test_appends_webhook_path_and_query(self) -> None:
        url = _build_alert_url("http://127.0.0.1:8080", "state_change")
        assert url == "http://127.0.0.1:8080/webhook?templateName=state_change"

    def test_trims_trailing_slash(self) -> None:
        url = _build_alert_url("http://127.0.0.1:8080/", "buffer_alert")
        assert url == "http://127.0.0.1:8080/webhook?templateName=buffer_alert"
