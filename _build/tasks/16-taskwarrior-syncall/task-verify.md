# Task Verification — Task 16: Taskwarrior + Syncall

## Overall Health: HEALTHY (post-sub-04)

All four subtasks complete. Taskwarrior is the canonical task ledger
when `TASKWARRIOR_ENABLED=true`; the legacy JSON backend remains in
place as a reversible rollback. The syncall daemon is vendored and
gated by `SYNCALL_ENABLED=false` by default.

## Subtask Integration

### Sub-01: Taskwarrior-backed task store
- **Result:** `TaskwarriorStore` drop-in for the 8-method `TaskStoreProtocol`; vendored tasklib 2.5.1; setup hook warns when migration is needed.
- **Files:** `taskwarrior_store.py`, `taskwarrior_setup.py`, `vendor/tasklib/`, `tests/test_taskwarrior_store.py`, `tests/test_taskwarrior_setup.py`.

### Sub-02: Task store factory + migration
- **Result:** `build_task_store(env, repo_root)` flips between JSON and Taskwarrior by flag. `scripts/migrate_json_to_taskwarrior.py` imports existing rows once.
- **Files:** `task_store.py` (added `TaskStoreProtocol`), `task_store_factory.py`, `scripts/migrate_json_to_taskwarrior.py`, `custom_gateway.py` (factory wiring), `dashboard_api.py` (factory wiring), `hook_factory.py` (factory wiring).

### Sub-03: Syncall Taskwarrior↔GCal daemon
- **Result:** `syncall_daemon.py` runs the vendored `tw_gcal_sync` in a subprocess loop, flag-gated by `SYNCALL_ENABLED=true`; first-run OAuth is a manual ritual documented in `SYNCALL.md`.
- **Files:** `syncall_setup.py`, `syncall_daemon.py`, `vendor/syncall/`, `tests/test_syncall_*.py`.

### Sub-04: Docs + integration proof
- **Result:** User-facing `workspace/TASKWARRIOR.md`; `## Task Ledger` SOUL.md section for LLM awareness; cross-consumer integration suite proves tool/dashboard/MagicMirror all see the same Taskwarrior rows.
- **Files:** `workspace/TASKWARRIOR.md`, `workspace/SOUL.md` (surgical insert), `setup_workspace.py` (TEMPLATE_FILES), `task_store.py` (docstring WHY comment), `tests/test_task16_integration.py`, `tests/test_taskwarrior_md_deploy.py`, `tests/test_soul_task_ledger_section.py`, `tests/test_task_store_rollback.py`, `tests/test_magicmirror_hook_taskwarrior.py`.

## Cross-Subtask Integration

- Sub-02's factory is the sole construction site for task stores in production code (`custom_gateway.create_stores`, `dashboard_api.handle_tasks`, `dashboard_api._build_activity_feed`, `hook_factory.create_hooks`).
- Sub-01's `TaskwarriorStore` and the legacy `TaskStore` both satisfy sub-02's `TaskStoreProtocol`; the tool registry, dashboard, and MagicMirror hook annotate against that Protocol, so the backend switches transparently.
- Sub-03's daemon shares the same Taskwarrior data dir the bot writes to; syncall does not start when `SYNCALL_ENABLED=false`.

## Canonical backend post-task

- `TASKWARRIOR_ENABLED=true` → `taskwarrior_store.TaskwarriorStore` (data at `workspace/data/taskwarrior/`).
- `TASKWARRIOR_ENABLED=false` or missing → `task_store.TaskStore` (data at `workspace/data/tasks.json`).

## Sync daemon status

- Vendored at `vendor/syncall/` (commit 14a2615).
- Flag-gated: `SYNCALL_ENABLED=false` by default. Does not spawn on bot start unless explicitly enabled.
- First-run OAuth is a manual ritual (`python -m syncall.scripts.tw_gcal_sync ...`) — documented step-by-step in `SYNCALL.md`.
- OAuth token cached at `Path.home() / .gcal_credentials.pickle` (hardcoded upstream; gitignored).

## Rollback

1. Set `TASKWARRIOR_ENABLED=false` in `.env` (or remove the line).
2. Restart (`python start.py`).
3. Verify the dashboard `/tasks` endpoint serves from `workspace/data/tasks.json` again.

## Known divergence warning

Tasks created while Taskwarrior was canonical live only in the Taskwarrior data dir. Flipping back to JSON makes those rows invisible to the bot; flipping forward again leaves two diverged data sets. Policy: pick one backend and stay there post-migration. See `TASKWARRIOR.md` "Rollback" section for the user-facing warning.

## Phase-2 baseline lock

`tests/test_task_store_rollback.py` locks AC #11: with `TASKWARRIOR_ENABLED=false` and `SYNCALL_ENABLED=false` (both defaults), `build_task_store` returns `TaskStore`, `workspace/data/tasks.json` remains readable after migration, and the pre-Task-16 2026-04-16 clean-run baseline is preserved byte-for-byte in the task-store wiring.

## Test Results

- Sub-01: tests in `tests/test_taskwarrior_*` pass (CLI-gated).
- Sub-02: tests in `tests/test_task_store_factory.py`, `tests/test_task_store_protocol.py`, `tests/test_migrate_json_to_taskwarrior.py` pass.
- Sub-03: tests in `tests/test_syncall_*` pass.
- Sub-04: 5 new test files — integration suite (`test_task16_integration.py`), deploy (`test_taskwarrior_md_deploy.py`), SOUL-section (`test_soul_task_ledger_section.py`), rollback (`test_task_store_rollback.py`), MagicMirror+TW (`test_magicmirror_hook_taskwarrior.py`). Taskwarrior-CLI-dependent tests skip cleanly when the `task` binary is absent.

## Gaps

- Integration suite only exercises functional equivalence on the Taskwarrior side; JSON-path parity is covered by the pre-existing `test_task_tools*` suite and not re-proven per-consumer here.
- Windows shutdown of the syncall daemon is a hard kill (sub-03 MEDIUM, out of scope for sub-04).
- Migration CLI `--force` does not prune orphan Taskwarrior rows created after migration (documented, not automated).
