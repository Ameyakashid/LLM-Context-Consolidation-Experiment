"""Webhook client for the MagicMirror² MMM-WebHookAlerts module.

Three frozen payload types — one per vendored ``config.js.template`` entry —
each with a ``template_name`` class var that references
``MAGICMIRROR_WEBHOOK_TEMPLATE_NAMES`` (single source of truth, no string
duplication) and a ``to_json_body()`` method that re-keys the richer
Python field names to the flat Mustache placeholders the upstream template
actually renders (``{{state}}``, ``{{buffer}}``, ``{{level}}``, …).

``validate_local_url`` enforces that the sender only targets loopback hosts;
``send_alert_sync`` returns a structured :class:`SendResult` on every
transport or HTTP failure instead of propagating exceptions so the calling
hook can stay simple. ``send_alert_async`` dispatches the same call to a
module-level :class:`ThreadPoolExecutor`; ``shutdown_webhook_pool`` tears
it down idempotently for tests and process exit.
"""

from __future__ import annotations

import atexit
import ipaddress
import json
import logging
import socket
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import ClassVar

from magicmirror_setup import MAGICMIRROR_WEBHOOK_TEMPLATE_NAMES
from state_detection import StateName

log = logging.getLogger(__name__)

_STATE_CHANGE, _BUFFER_ALERT, _MISSED_CHECKIN = MAGICMIRROR_WEBHOOK_TEMPLATE_NAMES

DEFAULT_TIMEOUT_SECONDS: float = 3.0
_POOL_MAX_WORKERS: int = 2
_LOOPBACK_HOSTNAME: str = "localhost"
_LOOPBACK_HINT: str = (
    "only loopback URLs are accepted. "
    "Configure MAGICMIRROR_WEBHOOK_HOST to 127.0.0.1 / localhost / ::1."
)


@dataclass(frozen=True)
class StateChangePayload:
    """Payload for the MagicMirror ``state_change`` template.

    The vendored template body references ``{{state}}`` and ``{{message}}``;
    ``to_json_body()`` emits both. ``from_state`` is carried for audit
    logging on the MagicMirror side even though the current template does
    not render it — upstream can add ``{{from_state}}`` without a Python
    change.
    """

    message: str
    from_state: StateName
    to_state: StateName
    timestamp: datetime

    template_name: ClassVar[str] = _STATE_CHANGE

    def to_json_body(self) -> dict[str, str | int | float]:
        return {
            "message": self.message,
            "state": self.to_state,
            "from_state": self.from_state,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class BufferAlertPayload:
    """Payload for the MagicMirror ``buffer_alert`` template.

    The vendored template body references ``{{buffer}}``, ``{{level}}``,
    ``{{capacity}}``, and ``{{message}}``. ``threshold`` rides along for
    auditability.
    """

    message: str
    buffer_name: str
    current_level: int
    capacity: int
    threshold: int
    timestamp: datetime

    template_name: ClassVar[str] = _BUFFER_ALERT

    def to_json_body(self) -> dict[str, str | int | float]:
        return {
            "message": self.message,
            "buffer": self.buffer_name,
            "level": self.current_level,
            "capacity": self.capacity,
            "threshold": self.threshold,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class MissedCheckinPayload:
    """Payload for the MagicMirror ``missed_checkin`` template."""

    message: str
    checkin_type: str
    due_at: datetime
    detected_at: datetime

    template_name: ClassVar[str] = _MISSED_CHECKIN

    def to_json_body(self) -> dict[str, str | int | float]:
        return {
            "message": self.message,
            "checkin_type": self.checkin_type,
            "due_at": self.due_at.isoformat(),
            "detected_at": self.detected_at.isoformat(),
        }


WebhookPayload = StateChangePayload | BufferAlertPayload | MissedCheckinPayload


@dataclass(frozen=True)
class SendResult:
    ok: bool
    status_code: int | None
    error: str | None
    template_name: str


def validate_local_url(url: str) -> None:
    """Raise ``ValueError`` unless ``url`` targets a loopback host."""
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname
    if not host:
        raise ValueError(
            f"URL {url!r} has no host. {_LOOPBACK_HINT}"
        )
    if host.lower() == _LOOPBACK_HOSTNAME:
        return
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise ValueError(
            f"{_LOOPBACK_HINT} Rejected host: {host!r}."
        ) from None
    if not address.is_loopback:
        raise ValueError(
            f"{_LOOPBACK_HINT} Rejected host: {host!r}."
        )


def _build_alert_url(base_url: str, template_name: str) -> str:
    base = base_url.rstrip("/")
    query = urllib.parse.urlencode({"templateName": template_name})
    return f"{base}/webhook?{query}"


def send_alert_sync(
    payload: WebhookPayload,
    base_url: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> SendResult:
    """POST ``payload`` to ``base_url``; return a structured result.

    Never raises for transport, timeout, or HTTP-error failures — each path
    surfaces as ``ok=False`` with context in ``error``. Raises only when
    ``base_url`` fails :func:`validate_local_url` (caller bug).
    """
    validate_local_url(base_url)
    url = _build_alert_url(base_url, payload.template_name)
    body = json.dumps(payload.to_json_body()).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(response.status)
    except urllib.error.HTTPError as err:
        log.warning(
            "MagicMirror webhook %s returned HTTP %d: %s",
            payload.template_name, err.code, err.reason,
        )
        return SendResult(
            ok=False,
            status_code=int(err.code),
            error=f"HTTP {err.code}: {err.reason}",
            template_name=payload.template_name,
        )
    except socket.timeout as err:
        log.warning(
            "MagicMirror webhook %s timed out after %.1fs",
            payload.template_name, timeout,
        )
        return SendResult(
            ok=False,
            status_code=None,
            error=f"Timeout after {timeout:.1f}s: {err}",
            template_name=payload.template_name,
        )
    except urllib.error.URLError as err:
        log.warning(
            "MagicMirror webhook %s URL error: %s",
            payload.template_name, err.reason,
        )
        return SendResult(
            ok=False,
            status_code=None,
            error=f"URL error: {err.reason}",
            template_name=payload.template_name,
        )
    if 200 <= status < 300:
        return SendResult(
            ok=True,
            status_code=status,
            error=None,
            template_name=payload.template_name,
        )
    log.warning(
        "MagicMirror webhook %s returned non-2xx status %d",
        payload.template_name, status,
    )
    return SendResult(
        ok=False,
        status_code=status,
        error=f"Non-2xx status: {status}",
        template_name=payload.template_name,
    )


_pool_lock = Lock()
_pool: ThreadPoolExecutor | None = None
_atexit_registered: bool = False


def _get_or_create_pool() -> ThreadPoolExecutor:
    global _pool, _atexit_registered
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(
                max_workers=_POOL_MAX_WORKERS,
                thread_name_prefix="mm-webhook",
            )
            if not _atexit_registered:
                atexit.register(shutdown_webhook_pool)
                _atexit_registered = True
        return _pool


def send_alert_async(
    payload: WebhookPayload,
    base_url: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> "Future[SendResult]":
    """Submit :func:`send_alert_sync` to the module-level thread pool."""
    pool = _get_or_create_pool()
    return pool.submit(send_alert_sync, payload, base_url, timeout)


def shutdown_webhook_pool() -> None:
    """Shut down the module-level executor. Safe to call multiple times."""
    global _pool
    with _pool_lock:
        pool = _pool
        _pool = None
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)
