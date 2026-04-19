"""Pure CLI-arg assembly for the ``tw_gcal_sync`` subprocess invocation.

Isolated from ``syncall_daemon.py`` so the 300-line cap holds and arg
assembly stays easy to unit-test without touching subprocess, signals, or
the filesystem.

Contract: every function here is pure — same env dict in, same argv list
out, no I/O, no mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

__all__ = [
    "SYNCALL_VALID_RESOLUTION_STRATEGIES",
    "SYNCALL_RESOLUTION_ALIASES",
    "SyncallArgsConfig",
    "build_syncall_args",
    "read_syncall_args_config",
    "resolve_resolution_strategy",
    "resolve_verbosity_tokens",
]

SYNCALL_VALID_RESOLUTION_STRATEGIES: tuple[str, ...] = (
    "MostRecentRS",
    "LeastRecentRS",
    "AlwaysFirstRS",
    "AlwaysSecondRS",
)

SYNCALL_RESOLUTION_ALIASES: Mapping[str, str] = {
    "tw_wins": "AlwaysSecondRS",
    "gcal_wins": "AlwaysFirstRS",
    "most_recent": "MostRecentRS",
    "least_recent": "LeastRecentRS",
}

DEFAULT_RESOLUTION_STRATEGY = "AlwaysSecondRS"
DEFAULT_COMBINATION_NAME = "adhd-assistant"
DEFAULT_OAUTH_PORT = 8080
DEFAULT_VERBOSE = 1
MAX_VERBOSE = 3


@dataclass(frozen=True)
class SyncallArgsConfig:
    """Resolved env values needed to assemble ``tw_gcal_sync`` CLI args."""

    gcal_calendar: str
    google_secret_path: str
    combination_savename: str
    resolution_strategy: str
    oauth_port: int
    verbose: int
    tw_filter: str


def resolve_resolution_strategy(raw: str) -> str:
    """Map a raw env value to a valid syncall strategy class name.

    Accepts either an upstream class name (``AlwaysSecondRS``) or one of
    the friendly aliases in ``SYNCALL_RESOLUTION_ALIASES`` (``tw_wins``).
    Returns the canonical upstream name.

    Raises ``ValueError`` with context when the input matches neither set.
    """
    cleaned = raw.strip()
    if not cleaned:
        return DEFAULT_RESOLUTION_STRATEGY
    if cleaned in SYNCALL_VALID_RESOLUTION_STRATEGIES:
        return cleaned
    if cleaned in SYNCALL_RESOLUTION_ALIASES:
        return SYNCALL_RESOLUTION_ALIASES[cleaned]
    valid_names = ", ".join(SYNCALL_VALID_RESOLUTION_STRATEGIES)
    valid_aliases = ", ".join(SYNCALL_RESOLUTION_ALIASES.keys())
    raise ValueError(
        f"SYNCALL_RESOLUTION_STRATEGY={cleaned!r} is not a known strategy. "
        f"Valid upstream names: {valid_names}. "
        f"Valid friendly aliases: {valid_aliases}. "
        f"Leave SYNCALL_RESOLUTION_STRATEGY unset to use the default "
        f"{DEFAULT_RESOLUTION_STRATEGY} (Taskwarrior wins on conflict)."
    )


def resolve_verbosity_tokens(verbose: int) -> list[str]:
    """Return ``-v`` tokens for click's ``count=True`` flag.

    ``verbose=0`` -> empty list. ``verbose=2`` -> ``["-v", "-v"]``. Values
    above ``MAX_VERBOSE`` are clamped to ``MAX_VERBOSE`` since no click
    handler in syncall reads past 3.
    """
    if verbose < 0:
        return []
    clamped = min(verbose, MAX_VERBOSE)
    return ["-v"] * clamped


def _parse_int_env(raw: str, default: int, var_name: str) -> int:
    cleaned = raw.strip()
    if not cleaned:
        return default
    try:
        return int(cleaned)
    except ValueError as err:
        raise ValueError(
            f"{var_name}={cleaned!r} is not a valid integer. "
            f"Leave it blank to use the default {default}."
        ) from err


def read_syncall_args_config(env: Mapping[str, str]) -> SyncallArgsConfig:
    """Extract syncall CLI inputs from an env mapping.

    Raises ``ValueError`` when a required value is missing or unparseable.
    Never reads the filesystem, never mutates the mapping.
    """
    gcal_calendar = env.get("SYNCALL_GCAL_CALENDAR", "").strip()
    if not gcal_calendar:
        raise ValueError(
            "SYNCALL_GCAL_CALENDAR is empty. Set it to the name of the "
            "Google Calendar you want Taskwarrior synced to (e.g. "
            "'ADHD-Assistant'). The calendar must already exist in your "
            "Google account; syncall does not create it."
        )
    google_secret_path = env.get("GOOGLE_OAUTH_CREDENTIALS", "").strip()
    if not google_secret_path:
        raise ValueError(
            "GOOGLE_OAUTH_CREDENTIALS is empty. Set it to the absolute "
            "path of the Google OAuth desktop-client JSON (same file "
            "Task 14's GCal MCP uses). syncall needs it to complete the "
            "first-run OAuth flow."
        )
    combination_savename = (
        env.get("SYNCALL_COMBINATION_NAME", "").strip() or DEFAULT_COMBINATION_NAME
    )
    resolution_strategy = resolve_resolution_strategy(
        env.get("SYNCALL_RESOLUTION_STRATEGY", ""),
    )
    oauth_port = _parse_int_env(
        env.get("SYNCALL_OAUTH_PORT", ""),
        DEFAULT_OAUTH_PORT,
        "SYNCALL_OAUTH_PORT",
    )
    verbose = _parse_int_env(
        env.get("SYNCALL_VERBOSE", ""),
        DEFAULT_VERBOSE,
        "SYNCALL_VERBOSE",
    )
    tw_filter = env.get("SYNCALL_TW_FILTER", "").strip()
    return SyncallArgsConfig(
        gcal_calendar=gcal_calendar,
        google_secret_path=google_secret_path,
        combination_savename=combination_savename,
        resolution_strategy=resolution_strategy,
        oauth_port=oauth_port,
        verbose=verbose,
        tw_filter=tw_filter,
    )


def build_syncall_args(config: SyncallArgsConfig) -> list[str]:
    """Assemble the ``tw_gcal_sync`` CLI arg list from resolved config.

    The returned list excludes the executable path — callers prepend
    ``[sys.executable, "-m", "syncall.scripts.tw_gcal_sync"]``. Never
    includes ``--confirm`` (interactive prompts block the daemon).
    """
    args = [
        "--gcal-calendar", config.gcal_calendar,
        "--google-secret", config.google_secret_path,
        "--oauth-port", str(config.oauth_port),
        "--custom-combination-savename", config.combination_savename,
        "--resolution-strategy", config.resolution_strategy,
    ]
    if config.tw_filter:
        args.extend(["--tw-filter", config.tw_filter])
    else:
        args.append("--sync-all-tw-tasks")
    args.extend(resolve_verbosity_tokens(config.verbose))
    return args
