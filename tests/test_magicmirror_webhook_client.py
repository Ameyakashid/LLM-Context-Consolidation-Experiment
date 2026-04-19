"""Send / async / shutdown tests for the MagicMirror webhook client.

Payload-model and URL-validation tests live in
``test_magicmirror_webhook_payloads.py``.
"""

from __future__ import annotations

import io
import socket
import urllib.error
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

import pytest

from magicmirror_webhook import (
    BufferAlertPayload,
    SendResult,
    StateChangePayload,
    MissedCheckinPayload,
    send_alert_async,
    send_alert_sync,
    shutdown_webhook_pool,
)


def _sample_state_change() -> StateChangePayload:
    return StateChangePayload(
        message="Shifted from focus to avoidance.",
        from_state="focus",
        to_state="avoidance",
        timestamp=datetime(2026, 4, 19, 14, 30, tzinfo=timezone.utc),
    )


def _sample_buffer_alert() -> BufferAlertPayload:
    return BufferAlertPayload(
        message="Only 2 left of 10.",
        buffer_name="dog food",
        current_level=2,
        capacity=10,
        threshold=3,
        timestamp=datetime(2026, 4, 19, 9, 15, tzinfo=timezone.utc),
    )


def _sample_missed_checkin() -> MissedCheckinPayload:
    return MissedCheckinPayload(
        message="Morning plan slot passed.",
        checkin_type="morning_plan",
        due_at=datetime(2026, 4, 19, 9, 0, tzinfo=timezone.utc),
        detected_at=datetime(2026, 4, 19, 11, 5, tzinfo=timezone.utc),
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
    shutdown_webhook_pool()
    yield
    shutdown_webhook_pool()


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
