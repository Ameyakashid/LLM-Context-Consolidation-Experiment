"""Idempotent, reversible tasks.json → Taskwarrior migration.

Each migrated task carries a ``migrated_<source_id_first_8>`` tag so a
second run is a no-op; the source JSON is never modified. Rollback: set
``TASKWARRIOR_ENABLED=false``.

Exit codes: 0 success; 2 pre-flight; 3 round-trip diff mismatch; 4
``--force`` refused (target has unrelated tasks).

Diff excludes ``id`` (TW assigns its own UUID) and ``created_at`` /
``updated_at`` (tasklib sets both at save time; sub-01 does not
preserve source values). See ``_build/tasks/16-taskwarrior-syncall/sub-02/16-02r.md``.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from task_store import Task, deserialize_tasks  # noqa: E402
from taskwarrior_store import TaskwarriorStore  # noqa: E402

log = logging.getLogger("migrate_json_to_taskwarrior")

DEFAULT_SOURCE = REPO_ROOT / "workspace" / "data" / "tasks.json"
DEFAULT_DATA_DIR = REPO_ROOT / "workspace" / "data" / "taskwarrior"
MIGRATED_TAG_PREFIX = "migrated_"
MIGRATED_ID_HEX_LENGTH = 8
LOG_FILENAME = "taskwarrior_migration.log"

EXIT_OK = 0
EXIT_PREFLIGHT = 2
EXIT_DIFF = 3
EXIT_FORCE_REFUSED = 4

DIFF_EXCLUDED_FIELDS = frozenset({"id", "created_at", "updated_at"})


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="migrate_json_to_taskwarrior",
        description="Import tasks.json into Taskwarrior idempotently.",
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--force", action="store_true",
        help="Proceed when the target has unrelated existing tasks.",
    )
    return parser.parse_args(argv)


def migration_tag_for(source_id: str) -> str:
    """Idempotency tag for a source task ID."""
    return f"{MIGRATED_TAG_PREFIX}{source_id[:MIGRATED_ID_HEX_LENGTH]}"


def load_source_tasks(source_path: Path) -> list[Task]:
    """Parse source JSON into Task objects."""
    raw = source_path.read_text(encoding="utf-8")
    return list(deserialize_tasks(raw).values())


def already_migrated_ids(store: TaskwarriorStore) -> set[str]:
    return {
        tag
        for task in store.list_tasks()
        for tag in task.tags
        if tag.startswith(MIGRATED_TAG_PREFIX)
    }


def unrelated_task_count(store: TaskwarriorStore) -> int:
    return sum(
        1
        for task in store.list_tasks()
        if not any(t.startswith(MIGRATED_TAG_PREFIX) for t in task.tags)
    )


def diff_round_trip(source: Task, written: Task) -> list[str]:
    """Names of fields that differ between source and written (minus the
    migration tag on ``tags`` and the excluded fields)."""
    source_fields = source.model_dump(mode="json")
    written_fields = written.model_dump(mode="json")
    differences: list[str] = []
    marker = migration_tag_for(source.id)
    for field in source_fields:
        if field in DIFF_EXCLUDED_FIELDS:
            continue
        if field == "tags":
            if set(source_fields[field]) != set(written_fields[field]) - {marker}:
                differences.append(field)
            continue
        if source_fields[field] != written_fields[field]:
            differences.append(field)
    return differences


def write_one_task(source: Task, store: TaskwarriorStore) -> Task:
    """Create one task in TW with the migration marker; apply status."""
    from task_store import TaskUpdate
    tags_with_marker = list(source.tags) + [migration_tag_for(source.id)]
    written = store.create_task(
        title=source.title,
        priority=source.priority,
        description=source.description,
        due_date=source.due_date,
        tags=tags_with_marker,
    )
    if source.status == "done":
        return store.mark_complete(written.id)
    if source.status == "in_progress":
        return store.update_task(written.id, TaskUpdate(status="in_progress"))
    return written


def migrate_tasks(
    source_tasks: list[Task],
    store: TaskwarriorStore,
    already_done: set[str],
    dry_run: bool,
) -> tuple[int, int, list[str]]:
    """Run the migration. Returns (migrated, skipped, diff_errors)."""
    migrated = 0
    skipped = 0
    diff_errors: list[str] = []
    for source in source_tasks:
        tag = migration_tag_for(source.id)
        if tag in already_done:
            skipped += 1
            log.info("Skipped %s (already migrated as %s)", source.id[:8], tag)
            continue
        if dry_run:
            log.info("Would migrate %s: %s", source.id[:8], source.title)
            continue
        written = write_one_task(source, store)
        reread = store.get_task(written.id)
        differences = diff_round_trip(source, reread)
        if differences:
            diff_errors.append(
                f"{source.id[:8]} differs on fields: {sorted(differences)}",
            )
            log.error(
                "Round-trip diff FAILED for %s on %s",
                source.id[:8], sorted(differences),
            )
            continue
        migrated += 1
        log.info("Migrated %s: %s", source.id[:8], source.title)
    return migrated, skipped, diff_errors


def write_run_log(
    log_path: Path,
    source_path: Path,
    source_count: int,
    migrated: int,
    skipped: int,
    diff_errors: Iterable[str],
    status: str,
) -> None:
    """Append a timestamped summary to ``taskwarrior_migration.log``."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"[{datetime.now().isoformat(timespec='seconds')}] migration run",
        f"  source: {source_path}",
        f"  source_count: {source_count}",
        f"  migrated: {migrated}",
        f"  skipped: {skipped}",
        f"  status: {status}",
    ]
    lines.extend(f"  diff_error: {err}" for err in diff_errors)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def preflight(args: argparse.Namespace) -> int:
    if not args.source.exists():
        log.error("Source tasks.json not found: %s", args.source)
        return EXIT_PREFLIGHT
    if shutil.which("task") is None:
        log.error(
            "Taskwarrior CLI ('task') not on PATH. Install first "
            "(choco/brew/apt install task).",
        )
        return EXIT_PREFLIGHT
    try:
        load_source_tasks(args.source)
    except (ValueError, json.JSONDecodeError) as exc:
        log.error("Source JSON invalid: %s", exc)
        return EXIT_PREFLIGHT
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args(argv if argv is not None else sys.argv[1:])

    preflight_code = preflight(args)
    if preflight_code != EXIT_OK:
        return preflight_code

    source_tasks = load_source_tasks(args.source)
    store = TaskwarriorStore(data_dir=args.data_dir)
    already_done = already_migrated_ids(store)

    unrelated = unrelated_task_count(store)
    if unrelated > 0 and not args.force:
        log.error(
            "Target has %d unrelated (non-migrated) tasks. Refusing to "
            "proceed. Re-run with --force to override.",
            unrelated,
        )
        return EXIT_FORCE_REFUSED

    migrated, skipped, diff_errors = migrate_tasks(
        source_tasks, store, already_done, args.dry_run,
    )

    log_path = args.data_dir / LOG_FILENAME
    status = (
        "dry_run"
        if args.dry_run
        else ("ok" if not diff_errors else "diff_failure")
    )
    write_run_log(
        log_path, args.source, len(source_tasks),
        migrated, skipped, diff_errors, status,
    )

    if diff_errors:
        log.error(
            "Migration completed with %d diff failures. See %s.",
            len(diff_errors), log_path,
        )
        return EXIT_DIFF

    log.info(
        "Migration %s. migrated=%d skipped=%d source_count=%d",
        status, migrated, skipped, len(source_tasks),
    )
    if not args.dry_run:
        log.info(
            "Source preserved at %s. Rollback: set "
            "TASKWARRIOR_ENABLED=false and restart; source JSON is still "
            "canonical. To discard migrated data, remove tasks tagged "
            "'%s*' from the Taskwarrior data dir.",
            args.source, MIGRATED_TAG_PREFIX,
        )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
