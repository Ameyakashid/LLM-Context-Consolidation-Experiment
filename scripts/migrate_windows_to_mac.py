"""Reversible Windows → macOS data migration for the ADHD Assistant.

Copies runtime state from Windows-side locations into the macOS-conventional
``~/Library/Application Support/adhd-assistant/`` layout. The source tree
is never modified; rollback is ``rm -rf <target-base>``. Idempotent: a
target that already holds data from a prior run is skipped (``--force``
overrides). Dry-run is the default — the actual copy requires ``--apply``.

Exit codes: 0 success; 2 missing source; 3 target conflict on a fresh
target without ``--force``; 4 permission error while copying.

See ``workspace/MAC_PATHS.md`` and
``_build/tasks/18-mac-deployment-port/sub-02/description.md``.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

log = logging.getLogger("migrate_windows_to_mac")

DEFAULT_TARGET_BASE = (
    Path.home() / "Library" / "Application Support" / "adhd-assistant"
)
LOG_FILENAME = "migration_windows_to_mac.log"

EXIT_OK = 0
EXIT_MISSING_SOURCE = 2
EXIT_TARGET_CONFLICT = 3
EXIT_PERMISSION = 4

STATUS_COPIED = "copied"
STATUS_FORCED = "forced_overwrite"
STATUS_WOULD_COPY = "would_copy"
STATUS_SKIPPED_TARGET_EXISTS = "skipped_target_exists"
STATUS_SKIPPED_SOURCE_MISSING = "skipped_source_missing"


@dataclass(frozen=True)
class PathEntry:
    """``relative_source`` is joined onto --source-repo; ``target_subdir``
    onto --target-base. ``is_dir`` picks copytree vs copy2."""

    relative_source: Path
    target_subdir: str
    description: str
    is_dir: bool


@dataclass(frozen=True)
class EntryResult:
    entry: PathEntry
    source_path: Path
    target_path: Path
    status: str


PATH_MAPPING: tuple[PathEntry, ...] = (
    PathEntry(
        Path("workspace") / "data",
        "data",
        "ADHD stores + Dream persistence ($ADHD_DATA_DIR, $DASHBOARD_DATA_DIR)",
        is_dir=True,
    ),
    PathEntry(
        Path("workspace") / "data" / "taskwarrior",
        "taskwarrior",
        "Taskwarrior .data files ($TASKWARRIOR_DATA_DIR; sibling of data/)",
        is_dir=True,
    ),
    PathEntry(
        Path("gcp-oauth.keys.json"),
        "oauth/gcp-oauth.keys.json",
        "Google OAuth client secrets ($GOOGLE_OAUTH_CREDENTIALS)",
        is_dir=False,
    ),
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="migrate_windows_to_mac",
        description=(
            "Copy Windows-side runtime data into the macOS-conventional "
            "layout. Source tree is never modified. Dry-run by default; "
            "pass --apply to perform the copy."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply", action="store_true",
        help="Perform the copy. Without this, the command is a dry-run.",
    )
    mode.add_argument(
        "--dry-run", action="store_true",
        help="Explicit dry-run. Mutually exclusive with --apply.",
    )
    parser.add_argument("--source-repo", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--target-base", type=Path, default=DEFAULT_TARGET_BASE,
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite target entries that already exist and are non-empty.",
    )
    return parser.parse_args(argv)


def expand_path(candidate: Path) -> Path:
    return Path(str(candidate)).expanduser().resolve()


def preflight(source_repo: Path) -> int:
    if not source_repo.exists():
        log.error(
            "Source repo not found: %s. Pass --source-repo to override.",
            source_repo,
        )
        return EXIT_MISSING_SOURCE
    return EXIT_OK


def target_is_nonempty(target_path: Path) -> bool:
    if not target_path.exists():
        return False
    if target_path.is_file():
        return target_path.stat().st_size > 0
    return any(target_path.iterdir())


def remove_target(target_path: Path) -> None:
    if target_path.is_dir():
        shutil.rmtree(target_path)
    elif target_path.exists():
        target_path.unlink()


def copy_entry(source: Path, target: Path, is_dir: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if is_dir:
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)


def process_entry(
    entry: PathEntry,
    source_repo: Path,
    target_base: Path,
    *,
    apply_copy: bool,
    force: bool,
) -> EntryResult:
    source_path = source_repo / entry.relative_source
    target_path = target_base / entry.target_subdir

    if not source_path.exists():
        log.info("Skip (source missing): %s [%s]", source_path, entry.description)
        return EntryResult(
            entry, source_path, target_path, STATUS_SKIPPED_SOURCE_MISSING,
        )

    target_nonempty = target_is_nonempty(target_path)
    if target_nonempty and not force:
        log.info("Skip (target non-empty): %s → %s", source_path, target_path)
        return EntryResult(
            entry, source_path, target_path, STATUS_SKIPPED_TARGET_EXISTS,
        )

    if not apply_copy:
        log.info(
            "Would copy: %s → %s [%s]",
            source_path, target_path, entry.description,
        )
        return EntryResult(
            entry, source_path, target_path, STATUS_WOULD_COPY,
        )

    if target_nonempty:
        remove_target(target_path)
        status = STATUS_FORCED
    else:
        status = STATUS_COPIED

    copy_entry(source_path, target_path, entry.is_dir)
    log.info("Copied: %s → %s", source_path, target_path)
    return EntryResult(entry, source_path, target_path, status)


def write_run_log(
    log_path: Path,
    results: list[EntryResult],
    *,
    apply_copy: bool,
    force: bool,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"[{datetime.now().isoformat(timespec='seconds')}] "
        f"migrate_windows_to_mac apply={apply_copy} force={force}"
    )
    lines = [header]
    for result in results:
        lines.append(
            f"  {result.status}: {result.source_path} -> {result.target_path}"
        )
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def print_banner(target_base: Path, apply_copy: bool) -> None:
    if apply_copy:
        log.info("")
        log.info("Migration complete. Next steps:")
        log.info("  1. Edit .env and uncomment the macOS path block.")
        log.info("  2. Restart the bot so env vars are re-read.")
        log.info("Target base: %s", target_base)
    else:
        log.info("")
        log.info("Dry-run complete. Re-run with --apply to perform the copy.")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args(argv if argv is not None else sys.argv[1:])
    apply_copy = bool(args.apply)
    force = bool(args.force)
    source_repo = expand_path(args.source_repo)
    target_base = expand_path(args.target_base)

    preflight_code = preflight(source_repo)
    if preflight_code != EXIT_OK:
        return preflight_code

    log_path = target_base / LOG_FILENAME
    had_prior_run = log_path.exists()

    results: list[EntryResult] = []
    for entry in PATH_MAPPING:
        try:
            result = process_entry(
                entry, source_repo, target_base,
                apply_copy=apply_copy, force=force,
            )
        except PermissionError as exc:
            log.error(
                "Permission denied on %s → %s: %s. Check directory "
                "permissions or re-run with appropriate access.",
                entry.relative_source, entry.target_subdir, exc,
            )
            return EXIT_PERMISSION
        results.append(result)

    has_conflicts = any(
        r.status == STATUS_SKIPPED_TARGET_EXISTS for r in results
    )
    if apply_copy and has_conflicts and not force and not had_prior_run:
        log.error(
            "Target %s is non-empty but has no prior migration log. "
            "Re-run with --force to overwrite or choose a different "
            "--target-base.",
            target_base,
        )
        return EXIT_TARGET_CONFLICT

    if apply_copy:
        write_run_log(log_path, results, apply_copy=apply_copy, force=force)

    print_banner(target_base, apply_copy)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
