"""Tests for the MagicMirror² webhook client.

Covers:
  * payload model construction + ``to_json_body`` shape against vendored
    ``config.js.template`` Mustache placeholders
  * ``validate_local_url`` accept/reject matrix
  * ``send_alert_sync`` returning ``SendResult`` on 200/400/500/timeout/refused
  * ``send_alert_async`` dispatching to the pool and shutdown idempotency
"""

from __future__ import annotations

import io
import re
import socket
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from magicmirror_setup import MAGICMIRROR_WEBHOOK_TEMPLATE_NAMES
from magicmirror_webhook import (
    BufferAlertPayload,
    MissedCheckinPayload,
    SendResult,
    StateChangePayload,
    WebhookPayload,
    _build_alert_url,
    send_alert_async,
    send_alert_sync,
    shutdown_webhook_pool,
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


class _FakeHTTPResponse:
    """Minimal stand-in for ``http.client.HTTPResponse`` in a ``with`` block."""

    def __init__(self, status: int, body: bytes = b"{}") -> None:
        self.status = status
        self._body = io.BytesIO(body)

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self._body.close()

    def read(self) -> bytes:
        return self._body.read()


@pytest.fixture(autouse=True)
def _clean_webhook_pool() -> Any:
    """Ensure the module-level pool is shut down around every test."""
    shutdown_webhook_pool()
    yield
    shutdown_webhook_pool()


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


def _extract_placeholders_for_template(
    template_source: str, template_name: str
) -> set[str]:
    """Pull every ``{{key}}`` referenced by the named template block."""
    block_rx = re.compile(
        r'templateName:\s*"' + re.escape(template_name) + r'".*?\}\s*[,\]]',
        re.DOTALL,
    )
    match = block_rx.search(template_source)
    assert match, f"Template block for {template_name!r} not found"
    return set(_PLACEHOLDER_RX.findall(match.group(0)))


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


class TestSendAlertSync:
    def test_returns_ok_on_200(self) -> None:
        with patch(
            "magicmirror_webhook.urllib.request.urlopen",
            return_value=_FakeHTTPResponse(200, b'{"status":200}'),
        ):
            result = send_alert_sync(_sample_state_change(), "http://127.0.0.1:8080")
        assert result == SendResult(
            ok=True, status_code=200, error=None, template_name="state_change"
        )

    def test_posts_json_body_with_content_type(self) -> None:
        captured: dict[str, Any] = {}

        def _capture(request: Any, timeout: float) -> _FakeHTTPResponse:
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["content_type"] = request.get_header("Content-type")
            captured["body"] = request.data
            captured["timeout"] = timeout
            return _FakeHTTPResponse(200)

        with patch(
            "magicmirror_webhook.urllib.request.urlopen", side_effect=_capture
        ):
            send_alert_sync(
                _sample_buffer_alert(), "http://127.0.0.1:8080", timeout=1.5
            )
        assert captured["method"] == "POST"
        assert captured["content_type"] == "application/json"
        assert captured["url"].endswith("?templateName=buffer_alert")
        assert b'"buffer"' in captured["body"]
        assert captured["timeout"] == 1.5

    def test_returns_not_ok_on_400(self) -> None:
        err = urllib.error.HTTPError(
            url="http://127.0.0.1:8080/webhook",
            code=400,
            msg="Bad Request",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(b'{"status":400,"error":"templateName missing"}'),
        )
        with patch(
            "magicmirror_webhook.urllib.request.urlopen", side_effect=err
        ):
            result = send_alert_sync(
                _sample_state_change(), "http://127.0.0.1:8080"
            )
        assert result.ok is False
        assert result.status_code == 400
        assert result.error is not None
        assert "400" in result.error

    def test_returns_not_ok_on_500(self) -> None:
        err = urllib.error.HTTPError(
            url="http://127.0.0.1:8080/webhook",
            code=500,
            msg="Internal Error",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(b""),
        )
        with patch(
            "magicmirror_webhook.urllib.request.urlopen", side_effect=err
        ):
            result = send_alert_sync(
                _sample_missed_checkin(), "http://127.0.0.1:8080"
            )
        assert result.ok is False
        assert result.status_code == 500

    def test_returns_not_ok_on_timeout(self) -> None:
        with patch(
            "magicmirror_webhook.urllib.request.urlopen",
            side_effect=socket.timeout("timed out"),
        ):
            result = send_alert_sync(
                _sample_state_change(), "http://127.0.0.1:8080", timeout=0.5
            )
        assert result.ok is False
        assert result.status_code is None
        assert result.error is not None
        assert "timeout" in result.error.lower()

    def test_returns_not_ok_on_connection_refused(self) -> None:
        with patch(
            "magicmirror_webhook.urllib.request.urlopen",
            side_effect=urllib.error.URLError(
                ConnectionRefusedError("connection refused")
            ),
        ):
            result = send_alert_sync(
                _sample_state_change(), "http://127.0.0.1:8080"
            )
        assert result.ok is False
        assert result.status_code is None
        assert result.error is not None

    def test_raises_when_url_not_loopback(self) -> None:
        with pytest.raises(ValueError):
            send_alert_sync(_sample_state_change(), "http://192.168.1.5:8080")


class TestSendAlertAsync:
    def test_future_resolves_to_send_result(self) -> None:
        with patch(
            "magicmirror_webhook.urllib.request.urlopen",
            return_value=_FakeHTTPResponse(200),
        ):
            future = send_alert_async(
                _sample_state_change(), "http://127.0.0.1:8080"
            )
            result = future.result(timeout=2.0)
        assert isinstance(result, SendResult)
        assert result.ok is True

    def test_two_concurrent_submissions(self) -> None:
        with patch(
            "magicmirror_webhook.urllib.request.urlopen",
            return_value=_FakeHTTPResponse(200),
        ):
            f1 = send_alert_async(_sample_state_change(), "http://127.0.0.1:8080")
            f2 = send_alert_async(_sample_buffer_alert(), "http://127.0.0.1:8080")
            r1 = f1.result(timeout=2.0)
            r2 = f2.result(timeout=2.0)
        assert r1.ok and r2.ok
        assert r1.template_name == "state_change"
        assert r2.template_name == "buffer_alert"


class TestShutdownIdempotency:
    def test_shutdown_without_prior_submit_is_noop(self) -> None:
        shutdown_webhook_pool()
        shutdown_webhook_pool()

    def test_shutdown_twice_after_submit(self) -> None:
        with patch(
            "magicmirror_webhook.urllib.request.urlopen",
            return_value=_FakeHTTPResponse(200),
        ):
            future = send_alert_async(
                _sample_state_change(), "http://127.0.0.1:8080"
            )
            future.result(timeout=2.0)
        shutdown_webhook_pool()
        shutdown_webhook_pool()

    def test_submit_after_shutdown_restarts_pool(self) -> None:
        with patch(
            "magicmirror_webhook.urllib.request.urlopen",
            return_value=_FakeHTTPResponse(200),
        ):
            send_alert_async(
                _sample_state_change(), "http://127.0.0.1:8080"
            ).result(timeout=2.0)
            shutdown_webhook_pool()
            result = send_alert_async(
                _sample_buffer_alert(), "http://127.0.0.1:8080"
            ).result(timeout=2.0)
        assert result.ok is True
