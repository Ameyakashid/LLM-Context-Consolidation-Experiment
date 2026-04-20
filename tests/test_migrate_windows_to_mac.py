"""End-to-end tests for the Windows → macOS data migration script.

Covers dry-run vs apply, idempotency on re-run, reversibility (source
sha256 unchanged), the exit-code contract (0 / 2 / 3 / 4), and the
per-run summary log.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR.parent))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import migrate_windows_to_mac as migration  # noqa: E402


def tree_sha256(root: Path, *, skip_name: str | None = None) -> str:
    """Stable hash over file contents + relative paths under ``root``.
    ``skip_name`` drops files by basename (used for the append-only log)."""
    hasher = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if skip_name is not None and path.name == skip_name:
            continue
        hasher.update(str(path.relative_to(root)).encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


@pytest.fixture()
def fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    data_dir = repo / "workspace" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "checkins.json").write_text('{"checkins": []}', encoding="utf-8")
    (data_dir / "buffers.json").write_text('{"buffers": {}}', encoding="utf-8")
    (data_dir / "dream_last_run.json").write_text(
        '{"last_run": "2026-04-19T03:00:00+00:00"}', encoding="utf-8",
    )
    (data_dir / "dream_sessions.jsonl").write_text(
        '{"session_id": "s1"}\n', encoding="utf-8",
    )
    tw_dir = data_dir / "taskwarrior"
    tw_dir.mkdir()
    (tw_dir / "pending.data").write_text(
        'description:"sample"\nstatus:pending\n', encoding="utf-8",
    )
    (tw_dir / "completed.data").write_text("", encoding="utf-8")
    (repo / "gcp-oauth.keys.json").write_text(
        '{"installed": {"client_id": "stub"}}', encoding="utf-8",
    )
    return repo


@pytest.fixture()
def target_base(tmp_path: Path) -> Path:
    return tmp_path / "mac-target"


def _args(fake_repo: Path, target_base: Path, *extra: str) -> list[str]:
    return [
        "--source-repo", str(fake_repo),
        "--target-base", str(target_base),
        *extra,
    ]


class TestDryRun:
    def test_default_does_not_touch_disk(
        self, fake_repo: Path, target_base: Path,
    ) -> None:
        assert migration.main(_args(fake_repo, target_base)) == migration.EXIT_OK
        assert not target_base.exists()

    def test_explicit_dry_run_flag_also_exits_clean(
        self, fake_repo: Path, target_base: Path,
    ) -> None:
        exit_code = migration.main(_args(fake_repo, target_base, "--dry-run"))
        assert exit_code == migration.EXIT_OK
        assert not target_base.exists()


class TestApplyCopy:
    def test_apply_copies_data_directory(
        self, fake_repo: Path, target_base: Path,
    ) -> None:
        exit_code = migration.main(_args(fake_repo, target_base, "--apply"))
        assert exit_code == migration.EXIT_OK
        assert (target_base / "data" / "checkins.json").is_file()
        assert (target_base / "data" / "dream_last_run.json").is_file()
        assert (target_base / "data" / "dream_sessions.jsonl").is_file()

    def test_apply_copies_taskwarrior_dir_parallel_to_data(
        self, fake_repo: Path, target_base: Path,
    ) -> None:
        migration.main(_args(fake_repo, target_base, "--apply"))
        assert (target_base / "taskwarrior" / "pending.data").is_file()

    def test_apply_copies_oauth_file_under_oauth_subdir(
        self, fake_repo: Path, target_base: Path,
    ) -> None:
        migration.main(_args(fake_repo, target_base, "--apply"))
        assert (target_base / "oauth" / "gcp-oauth.keys.json").is_file()

    def test_apply_preserves_byte_content(
        self, fake_repo: Path, target_base: Path,
    ) -> None:
        migration.main(_args(fake_repo, target_base, "--apply"))
        source_file = fake_repo / "workspace" / "data" / "dream_sessions.jsonl"
        target_file = target_base / "data" / "dream_sessions.jsonl"
        assert (
            hashlib.sha256(source_file.read_bytes()).hexdigest()
            == hashlib.sha256(target_file.read_bytes()).hexdigest()
        )


class TestIdempotency:
    def test_second_apply_reports_skipped_and_exits_zero(
        self,
        fake_repo: Path,
        target_base: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        first = migration.main(_args(fake_repo, target_base, "--apply"))
        assert first == migration.EXIT_OK
        hash_after_first = tree_sha256(target_base, skip_name=migration.LOG_FILENAME)

        with caplog.at_level("INFO", logger=migration.log.name):
            second = migration.main(_args(fake_repo, target_base, "--apply"))
        assert second == migration.EXIT_OK
        assert tree_sha256(target_base, skip_name=migration.LOG_FILENAME) == hash_after_first
        assert "Skip (target non-empty)" in caplog.text


class TestReversibility:
    def test_source_tree_sha256_unchanged_after_apply(
        self, fake_repo: Path, target_base: Path,
    ) -> None:
        before = tree_sha256(fake_repo)
        migration.main(_args(fake_repo, target_base, "--apply"))
        assert tree_sha256(fake_repo) == before


class TestForceOverwrite:
    def test_force_overwrites_existing_target(
        self, fake_repo: Path, target_base: Path,
    ) -> None:
        preexisting = target_base / "taskwarrior"
        preexisting.mkdir(parents=True)
        (preexisting / "stale.data").write_text("old", encoding="utf-8")

        exit_code = migration.main(
            _args(fake_repo, target_base, "--apply", "--force"),
        )
        assert exit_code == migration.EXIT_OK
        assert not (preexisting / "stale.data").exists()
        assert (preexisting / "pending.data").is_file()


class TestSummaryLog:
    def test_log_written_with_timestamped_header(
        self, fake_repo: Path, target_base: Path,
    ) -> None:
        migration.main(_args(fake_repo, target_base, "--apply"))
        content = (target_base / migration.LOG_FILENAME).read_text(
            encoding="utf-8",
        )
        assert "migrate_windows_to_mac apply=True" in content
        assert migration.STATUS_COPIED in content

    def test_log_appends_across_runs(
        self, fake_repo: Path, target_base: Path,
    ) -> None:
        migration.main(_args(fake_repo, target_base, "--apply"))
        migration.main(_args(fake_repo, target_base, "--apply"))
        content = (target_base / migration.LOG_FILENAME).read_text(
            encoding="utf-8",
        )
        assert content.count("migrate_windows_to_mac apply=True") == 2

    def test_dry_run_does_not_write_log(
        self, fake_repo: Path, target_base: Path,
    ) -> None:
        migration.main(_args(fake_repo, target_base))
        assert not (target_base / migration.LOG_FILENAME).exists()


class TestExitCodes:
    def test_missing_source_repo_returns_exit_two(self, tmp_path: Path) -> None:
        exit_code = migration.main([
            "--source-repo", str(tmp_path / "does-not-exist"),
            "--target-base", str(tmp_path / "tgt"),
            "--apply",
        ])
        assert exit_code == migration.EXIT_MISSING_SOURCE

    def test_non_empty_fresh_target_without_force_returns_three(
        self, fake_repo: Path, target_base: Path,
    ) -> None:
        (target_base / "data").mkdir(parents=True)
        (target_base / "data" / "someone_elses.json").write_text(
            '{"other": true}', encoding="utf-8",
        )
        exit_code = migration.main(_args(fake_repo, target_base, "--apply"))
        assert exit_code == migration.EXIT_TARGET_CONFLICT

    def test_non_empty_target_with_force_returns_zero(
        self, fake_repo: Path, target_base: Path,
    ) -> None:
        (target_base / "data").mkdir(parents=True)
        (target_base / "data" / "someone_elses.json").write_text(
            '{"other": true}', encoding="utf-8",
        )
        exit_code = migration.main(
            _args(fake_repo, target_base, "--apply", "--force"),
        )
        assert exit_code == migration.EXIT_OK

    def test_permission_error_during_copy_returns_four(
        self,
        fake_repo: Path,
        target_base: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def raise_permission(*_args: object, **_kwargs: object) -> None:
            raise PermissionError("simulated read-only target")

        monkeypatch.setattr(shutil, "copytree", raise_permission)
        exit_code = migration.main(_args(fake_repo, target_base, "--apply"))
        assert exit_code == migration.EXIT_PERMISSION


class TestMutuallyExclusiveFlags:
    def test_apply_and_dry_run_together_errors(
        self, fake_repo: Path, target_base: Path,
    ) -> None:
        with pytest.raises(SystemExit):
            migration.main(
                _args(fake_repo, target_base, "--apply", "--dry-run"),
            )


class TestMissingOptionalSource:
    def test_absent_oauth_file_skipped_cleanly(
        self, fake_repo: Path, target_base: Path,
    ) -> None:
        (fake_repo / "gcp-oauth.keys.json").unlink()
        exit_code = migration.main(_args(fake_repo, target_base, "--apply"))
        assert exit_code == migration.EXIT_OK
        assert not (target_base / "oauth").exists()


class TestCliSurface:
    def test_script_defines_main_guard_and_argparse(self) -> None:
        source = (
            Path(__file__).resolve().parent.parent
            / "scripts" / "migrate_windows_to_mac.py"
        ).read_text(encoding="utf-8")
        assert 'if __name__ == "__main__":' in source
        assert "argparse.ArgumentParser" in source

    def test_default_is_dry_run(self) -> None:
        assert migration.parse_args([]).apply is False

    def test_apply_flag_flips_default(self) -> None:
        assert migration.parse_args(["--apply"]).apply is True
