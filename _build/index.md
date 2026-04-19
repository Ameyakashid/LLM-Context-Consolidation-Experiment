# Project Index

> This file is the LLM-readable registry of everything built in this project. It follows the llms.txt standard. An LLM should read THIS FILE FIRST to understand what exists, then follow links to detail files for specifics.

## How To Use This Index

If you are an LLM agent in any IDE (Antigravity, Cursor, Claude Code, etc.) and you need to understand this project:
1. Read this file to find the component you need
2. Each entry has a semantic tag, a one-line summary, and a link to the full index report
3. Read the linked `x.md` file for file paths, exports, dependencies, and decisions
4. Read the linked source files if you need actual code

## Component Registry

(Entries appended by Verify agents after each subtask)

### Entry Format

```
### [semantic-tag]
> One-line description
- Status: DONE | DONE-WITH-ISSUES
- Task: NN/sub-NN
- Files: file1.py, file2.py, ...
- Depends on: [other-semantic-tag], [another-tag]
- Detail: _build/tasks/TASK_ID/sub-NN/NN-NNx.md
```

---

### [foundation-complete]
> Working nanobot-ai v0.1.5 workspace: build pipeline, Telegram bot config, multi-provider LLM (OpenRouter+Ollama), portable deployment, 39 passing tests
- Status: DONE-WITH-ISSUES
- Task: 01 (01-foundation)
- Subtasks: [build-scaffolding], [nanobot-workspace-setup], [bot-smoke-tests]
- Produces: Configured nanobot-ai workspace deployable to ~/.nanobot/, Telegram bot entry point, multi-provider LLM config (OpenRouter primary, Ollama fallback), build pipeline scaffolding (_build/ with plan, index, code-rules, 8 task specs). Downstream tasks 02-08 can now build on a running bot.
- Issues: (1) task-verify.md was not generated — no task-level cross-subtask verification exists. (2) code-rules.md has contradictory default parameter rule (lines 12 vs 58). (3) No mypy/pyright enforcement in dev dependencies. All LOW severity.
- Detail: _build/tasks/01-foundation/sub-03/01-03x.md (latest subtask; no task-verify.md)

### [build-scaffolding]
> Pipeline scaffolding: plan.md, index.md, code-rules.md, all 8 task specs, subtask descriptions — bootstrapped from PROJECT_BRIEF.md
- Status: DONE
- Task: 01/sub-01
- Files: _build/plan.md, _build/index.md, _build/code-rules.md, _build/tasks/01-foundation/spec.md, _build/tasks/01-foundation/sub-01/description.md, _build/tasks/01-foundation/sub-02/description.md, _build/tasks/02-personality/spec.md, _build/tasks/03-task-crud/spec.md, _build/tasks/04-memory/spec.md, _build/tasks/05-scheduling/spec.md, _build/tasks/06-buffer/spec.md, _build/tasks/07-voice/spec.md, _build/tasks/08-dashboard/spec.md
- Depends on: none
- Detail: _build/tasks/01-foundation/sub-01/01-01x.md

### [nanobot-workspace-setup]
> nanobot-ai v0.1.5 workspace with Telegram bot config, OpenRouter+Ollama multi-provider LLM, and portable deployment script
- Status: DONE
- Task: 01/sub-02
- Files: requirements.txt, setup_workspace.py, .env.example, .gitignore, workspace/SOUL.md, workspace/USER.md, workspace/HEARTBEAT.md, workspace/config.json.template, tests/test_setup_workspace.py
- Depends on: [build-scaffolding]
- Detail: _build/tasks/01-foundation/sub-02/01-02x.md

### [bot-smoke-tests]
> 18 smoke tests proving nanobot-ai config loads, provider resolves, and bot can start — validates sub-02 workspace setup
- Status: DONE
- Task: 01/sub-03
- Files: tests/test_bot_smoke.py
- Depends on: [nanobot-workspace-setup]
- Detail: _build/tasks/01-foundation/sub-03/01-03x.md

### [personality-core-complete]
> ADHD-native personality system: neuroaffirming SOUL.md, 6-state cognitive model (Baseline/Focus/Hyperfocus/Avoidance/Overwhelm/RSD) with Markov transitions, and nanobot-ai hook wiring state detection into per-message response adaptation — 212 tests passing
- Status: DONE-WITH-ISSUES
- Task: 02 (02-personality)
- Subtasks: [neuroaffirming-personality], [cognitive-state-detection], [state-response-integration]
- Produces: Complete personality layer for downstream tasks 03-08. SOUL.md loaded by nanobot-ai runtime with state-aware adaptation rules. StateResponseHook detects cognitive state per message and injects indicator into system prompt. States defined in editable YAML config. ICNU motivation framework and banned-phrase guardrails active. Disco Elysium personality voice stub ready for future milestone.
- Issues: (1) MEDIUM: normalize_llm_response substring fallback matches "focus" before "hyperfocus" — fix by sorting by length descending (state_detection.py:200-202). (2) task-verify.md was not generated — no task-level cross-subtask verification exists.
- Detail: _build/tasks/02-personality/sub-03/02-03x.md (latest subtask; no task-verify.md)

### [neuroaffirming-personality]
> SOUL.md personality definition with neuroaffirming rules, ICNU motivation framework, banned-phrase list, and AUDHD USER.md profile — plus 40 validation tests
- Status: DONE
- Task: 02/sub-01
- Files: workspace/SOUL.md, workspace/USER.md, tests/test_personality.py
- Depends on: [nanobot-workspace-setup], [bot-smoke-tests]
- Detail: _build/tasks/02-personality/sub-01/02-01x.md

### [cognitive-state-detection]
> 6-state cognitive model (Baseline/Focus/Hyperfocus/Avoidance/Overwhelm/RSD) with YAML config, LLM classification prompt, Markov transition enforcement, and StateName-typed function signatures — 132 tests across 4 files
- Status: DONE
- Task: 02/sub-02
- Files: workspace/states.yaml, state_detection.py, tests/test_state_config.py, tests/test_state_detection.py
- Depends on: [nanobot-workspace-setup], [neuroaffirming-personality]
- Issues: (1) MEDIUM: normalize_llm_response substring fallback matches "focus" before "hyperfocus" — fix by sorting by length descending. Low probability due to exact-match fast path.
- Detail: _build/tasks/02-personality/sub-02/02-02x.md

### [state-response-integration]
> Nanobot-ai hook detecting cognitive state per message, injecting indicator into system prompt, activating per-state SOUL.md response rules — 3 pure functions + StateResponseHook class, 40 tests
- Status: DONE
- Task: 02/sub-03
- Files: state_response_integration.py, workspace/SOUL.md, tests/test_state_response_pure.py, tests/test_state_response_hook.py
- Depends on: [neuroaffirming-personality], [cognitive-state-detection]
- Detail: _build/tasks/02-personality/sub-03/02-03x.md

### [task-crud-complete]
> Full task management pipeline: Pydantic data model + JSON-persisted TaskStore, 5 LLM-callable nanobot-ai Tool wrappers (create/list/get/update/complete), ADHD-friendly SOUL.md task guidance with 6-state cognitive awareness — 102 tests passing
- Status: DONE-WITH-ISSUES
- Task: 03 (03-task-crud)
- Subtasks: [task-data-model-store], [nanobot-task-tools], [soul-task-instructions]
- Produces: TaskStore CRUD API (task_store.py) and 5 registered Tool subclasses (task_tools.py) for downstream tasks 04-08. SOUL.md now includes Task Management section with state-aware presentation rules. Scheduling (task-05) and buffer system (task-06) can build on the Task model and store. Tools require programmatic registration via register_task_tools() at nanobot startup — config.json wiring not yet connected.
- Issues: (1) task-verify.md was not generated — no task-level cross-subtask verification exists. (2) LOW: apply_updates mixes JSON-mode and Python-mode dicts (task_store.py:95-98). (3) LOW: No file locking for concurrent TaskStore access (acceptable for single-user). (4) LOW: test helper `run()` missing type annotations (test_task_integration.py:58). (5) Tools not yet wired into nanobot startup — register_task_tools() call deferred to future integration.
- Detail: _build/tasks/03-task-crud/sub-03/03-03x.md (latest subtask; no task-verify.md)

### [task-data-model-store]
> Task Pydantic model + JSON-persisted TaskStore with full CRUD, atomic writes, pure helper functions — 39 tests
- Status: DONE
- Task: 03/sub-01
- Files: task_store.py, tests/test_task_model.py, tests/test_task_store.py
- Depends on: [nanobot-workspace-setup]
- Detail: _build/tasks/03-task-crud/sub-01/03-01x.md

### [nanobot-task-tools]
> Five LLM-callable nanobot-ai Tool subclasses wrapping TaskStore CRUD — create, list, get, update, complete — with JSON parameter schemas, programmatic registry, 34 tests
- Status: DONE
- Task: 03/sub-02
- Files: task_tools.py, tests/test_task_tools.py
- Depends on: [task-data-model-store], [nanobot-workspace-setup]
- Detail: _build/tasks/03-task-crud/sub-02/03-02x.md

### [soul-task-instructions]
> SOUL.md task management guidance (ADHD-friendly presentation, state-aware behavior) + 29 integration tests verifying full CRUD pipeline and persistence
- Status: DONE
- Task: 03/sub-03
- Files: workspace/SOUL.md, tests/test_task_integration.py
- Depends on: [neuroaffirming-personality], [task-data-model-store], [nanobot-task-tools], [cognitive-state-detection]
- Detail: _build/tasks/03-task-crud/sub-03/03-03x.md

### [memory-system-complete]
> Full memory pipeline: 5-category structured store, 3 LLM-callable tools (save/list/dismiss), context injection hook, SOUL.md memory guidance, MEMORY.md Dream seed — 90 tests across 6 files
- Status: DONE-WITH-ISSUES
- Task: 04 (04-memory)
- Subtasks: [memory-entry-store], [nanobot-memory-tools], [memory-context-injection]
- Produces: Complete memory layer for downstream tasks 05-08. MemoryEntryStore persists structured entries (JSON). Three nanobot-ai Tool subclasses expose CRUD to LLM. MemoryContextHook injects active entries into system prompt each message. SOUL.md teaches the bot when/how to use memory tools across 5 categories. MEMORY.md seeded for Dream's Phase 2 editor.
- Issues: (1) LOW: Double sort in MemoryContextHook._inject + format_memory_entries (redundant, not a bug). (2) LOW: HookContext protocol duplicated in memory_context.py and state_response_integration.py. (3) task-verify.md was not generated — no task-level cross-subtask verification exists.
- Detail: _build/tasks/04-memory/sub-03/04-03x.md (latest subtask; no task-verify.md)

### [memory-entry-store]
> JSON-persisted structured memory store — 5 categories (commitment/deadline/blocker/energy_state/context_switch), Pydantic model, soft-delete resolve, atomic writes — 43 tests
- Status: DONE
- Task: 04/sub-01
- Files: memory_store.py, tests/test_memory_model.py, tests/test_memory_store.py
- Depends on: [nanobot-workspace-setup]
- Detail: _build/tasks/04-memory/sub-01/04-01x.md

### [nanobot-memory-tools]
> Three LLM-callable nanobot-ai Tool subclasses wrapping MemoryEntryStore CRUD — save, list, dismiss — with JSON parameter schemas, ToolRegistry registration, 26 tests
- Status: DONE
- Task: 04/sub-02
- Files: memory_tools.py, tests/test_memory_tools.py
- Depends on: [memory-entry-store], [nanobot-workspace-setup]
- Detail: _build/tasks/04-memory/sub-02/04-02x.md

### [memory-context-injection]
> MemoryContextHook injecting active structured memories into system prompt + SOUL.md memory instructions for all 5 categories + MEMORY.md seed — 21 tests
- Status: DONE
- Task: 04/sub-03
- Files: memory_context.py, workspace/SOUL.md, workspace/memory/MEMORY.md, tests/test_memory_context.py, tests/test_memory_integration.py
- Depends on: [memory-entry-store], [state-response-integration]
- Detail: _build/tasks/04-memory/sub-03/04-03x.md

### [scheduling-complete]
> State-adaptive check-in scheduling: 4 check-in types, 6×4 cognitive-state evaluation matrix (fire/defer/modify/suppress), heartbeat hook integration, shared HookContext extraction, SOUL.md+HEARTBEAT.md guidance — 124 tests, hyperfocus substring bug fixed
- Status: DONE-WITH-ISSUES
- Task: 05 (05-scheduling)
- Subtasks: [checkin-schedule-engine], [state-aware-scheduling-logic], [scheduling-heartbeat-integration]
- Produces: Complete scheduling layer for downstream tasks 06-08. CheckInScheduleStore persists 4 configurable check-in types (morning_motivation, morning_plan, afternoon_check, evening_review) with staleness-guarded due detection. schedule_engine.py maps (check-in type × cognitive state) to actions via pure evaluate_checkin(). SchedulingHook reads enriched system prompt after StateResponseHook and MemoryContextHook, injects formatted check-in blocks into heartbeat sessions. hook_context.py provides shared HookContext Protocol for all 3 hooks. SOUL.md has per-type tone/content guidance. HEARTBEAT.md expanded to all 4 types. Hyperfocus substring ordering bug fixed in state_detection.py.
- Issues: (1) MEDIUM: test_schedule_engine.py (371 lines) and test_scheduling_hook.py (494 lines) both exceed 300-line limit — split recommended. (2) LOW: RSD handled as implicit else in evaluate_checkin — could add explicit check. (3) LOW: Unused timezone import in checkin_schedule.py. (4) task-verify.md was not generated — no task-level cross-subtask verification exists.
- Detail: _build/tasks/05-scheduling/sub-03/05-03x.md (latest subtask; no task-verify.md)

### [buffer-system-complete]
> Full buffer system for recurring obligations: Pydantic model + JSON-persisted BufferStore, 5 LLM-callable nanobot-ai tools (create/list/get/refill/decrement), auto-decrement heartbeat hook with low-level alert injection, ADHD-friendly SOUL.md+HEARTBEAT.md guidance — 147 tests passing
- Status: DONE-WITH-ISSUES
- Task: 06 (06-buffer)
- Subtasks: [buffer-data-model-store], [nanobot-buffer-tools], [buffer-heartbeat-hook]
- Produces: Complete buffer layer for downstream tasks 07-08. BufferStore persists pre-loaded units of recurring obligations (JSON). Five Tool subclasses expose CRUD+refill+decrement to LLM. BufferHook auto-decrements due buffers in heartbeat sessions and injects factual alerts (no guilt language) into system prompt when levels hit threshold. SOUL.md has 6-state cognitive-aware buffer guidance. HEARTBEAT.md has buffer monitoring section. Hook chain is now 4 deep: StateResponseHook → MemoryContextHook → SchedulingHook → BufferHook. Tools require programmatic registration via register_buffer_tools() at nanobot startup — config.json wiring not yet connected.
- Issues: (1) MEDIUM: test_buffer_model.py at 348 lines exceeds 300-line limit — split recommended. (2) LOW: apply_buffer_updates mixes JSON/Python-mode dicts (consistent with task_store.py). (3) LOW: BufferUpdate lacks Field constraints (caught at Buffer revalidation). (4) task-verify.md was not generated — no task-level cross-subtask verification exists.
- Detail: _build/tasks/06-buffer/sub-03/06-03x.md (latest subtask; no task-verify.md)

### [buffer-data-model-store]
> Buffer Pydantic model + JSON-persisted BufferStore with CRUD, decrement (level-1 + advance due date), refill (capped at capacity), atomic writes — 72 tests, verified PASS
- Status: DONE
- Task: 06/sub-01
- Files: buffer_store.py (285 lines), tests/test_buffer_model.py (348 lines), tests/test_buffer_store.py (266 lines)
- Depends on: [nanobot-workspace-setup]
- Issues: (1) MEDIUM: test_buffer_model.py at 348 lines exceeds 300-line limit — split recommended after TestBuildBuffer. (2) LOW: apply_buffer_updates mixes JSON/Python-mode dicts (same as task_store.py). (3) LOW: BufferUpdate lacks Field constraints (consistent with TaskUpdate).
- Detail: _build/tasks/06-buffer/sub-01/06-01x.md

### [checkin-schedule-engine]
> Check-in schedule data model (4 types), JSON-persisted store, pure due-check engine with staleness guard, + hyperfocus substring bug fix — 44 tests
- Status: DONE
- Task: 05/sub-01
- Files: checkin_schedule.py, tests/test_checkin_schedule.py, state_detection.py, tests/test_state_detection.py
- Depends on: [nanobot-workspace-setup], [cognitive-state-detection]
- Detail: _build/tasks/05-scheduling/sub-01/05-01x.md

### [state-aware-scheduling-logic]
> Pure decision layer: 6×4 state×check-in evaluation matrix (fire/defer/modify/suppress) + context assembly from TaskStore/MemoryEntryStore — 44 tests
- Status: DONE
- Task: 05/sub-02
- Files: schedule_engine.py, tests/test_schedule_engine.py
- Depends on: [checkin-schedule-engine], [cognitive-state-detection], [task-data-model-store], [memory-entry-store]
- Detail: _build/tasks/05-scheduling/sub-02/05-02x.md

### [scheduling-heartbeat-integration]
> Nanobot-ai hook wiring scheduling engine into heartbeat sessions — proactive check-in delivery with state-aware gating, SOUL.md guidance, shared HookContext extraction — 36 tests
- Status: DONE
- Task: 05/sub-03
- Files: hook_context.py, scheduling_hook.py, state_response_integration.py, memory_context.py, workspace/SOUL.md, workspace/HEARTBEAT.md, tests/test_scheduling_hook.py
- Depends on: [checkin-schedule-engine], [state-aware-scheduling-logic], [state-response-integration], [memory-context-injection], [task-data-model-store], [memory-entry-store]
- Detail: _build/tasks/05-scheduling/sub-03/05-03x.md

### [nanobot-buffer-tools]
> Five LLM-callable nanobot-ai Tool subclasses wrapping BufferStore (create/list/get/refill/decrement) + SOUL.md ADHD-friendly buffer guidance with 6-state cognitive awareness — 37 tests
- Status: DONE
- Task: 06/sub-02
- Files: buffer_tools.py, tests/test_buffer_tools.py, tests/test_buffer_format.py, workspace/SOUL.md
- Depends on: [buffer-data-model-store], [neuroaffirming-personality], [cognitive-state-detection]
- Detail: _build/tasks/06-buffer/sub-02/06-02x.md

### [buffer-heartbeat-hook]
> Auto-decrement hook for due buffers with low-level alert injection into system prompt — staleness guard via due-date advancement, ADHD-friendly factual alerts, HEARTBEAT.md buffer monitoring section — 38 tests
- Status: DONE
- Task: 06/sub-03
- Files: buffer_hook.py, tests/test_buffer_hook.py, tests/test_buffer_hook_lifecycle.py, hook_context.py, workspace/HEARTBEAT.md
- Depends on: [buffer-data-model-store], [nanobot-buffer-tools], [scheduling-heartbeat-integration]
- Detail: _build/tasks/06-buffer/sub-03/06-03x.md

### [voice-system-complete]
> Full voice output pipeline: Kokoro TTS engine (kokoro-onnx), WAV-to-OGG/Opus delivery via SpeakTool, state-aware auto-voice hook detecting check-in/buffer-alert triggers — 5-hook chain complete, env var toggle, SOUL.md+HEARTBEAT.md voice guidance — 116 tests
- Status: DONE-WITH-ISSUES
- Task: 07 (07-voice)
- Subtasks: [kokoro-tts-engine], [voice-delivery-speak-tool], [voice-trigger-hook]
- Produces: Complete voice layer for downstream task 08. tts_engine.py synthesizes text→WAV via kokoro-onnx ONNX Runtime. voice_delivery.py converts WAV→OGG/Opus via PyAV. SpeakTool wraps the full TTS→convert→Telegram send pipeline as an LLM-callable nanobot-ai Tool with MessageTool delegation for chat routing. VoiceHook (5th position in hook chain: StateResponse→MemoryContext→Scheduling→Buffer→Voice) detects check-in and buffer-alert headings in system prompt, evaluates a 6-state×2-trigger matrix, and injects Voice Delivery instruction blocks for the LLM. Voice is auto-triggered in baseline+avoidance for check-ins, baseline-only for buffer alerts; suppressed in focus/hyperfocus/overwhelm/RSD. User-initiated voice ("say that aloud") taught via SOUL.md direct SpeakTool invocation. VOICE_AUTO_ENABLED env var toggles auto-voice at runtime without restart. setup_workspace.py extended with portable model download (kokoro-v1.0.onnx + voices-v1.0.bin).
- Issues: (1) MEDIUM: test_voice_trigger_hook.py at 404 lines exceeds 300-line limit — split recommended. (2) LOW: task-verify.md was not generated — no task-level cross-subtask verification exists. (3) LOW: Tools require programmatic registration via register_voice_tools() at nanobot startup — config.json wiring not yet connected.
- Detail: _build/tasks/07-voice/sub-03/07-03x.md (latest subtask; no task-verify.md)

### [kokoro-tts-engine]
> Kokoro TTS wrapper (kokoro-onnx): synthesize_speech() takes text → returns WAV bytes, with portable model download in setup_workspace.py and lazy-loaded singleton — 35 tests
- Status: DONE
- Task: 07/sub-01
- Files: tts_engine.py, setup_workspace.py, requirements.txt, tests/test_tts_engine.py, tests/test_model_download.py
- Depends on: [nanobot-workspace-setup]
- Detail: _build/tasks/07-voice/sub-01/07-01x.md

### [voice-delivery-speak-tool]
> WAV-to-OGG/Opus conversion via PyAV + SpeakTool nanobot-ai Tool wrapping TTS→convert→Telegram send pipeline, with MessageTool delegation for routing — 31 tests
- Status: DONE
- Task: 07/sub-02
- Files: voice_delivery.py, voice_tools.py, tests/test_voice_delivery.py, tests/test_voice_tools.py, requirements.txt
- Depends on: [kokoro-tts-engine], [nanobot-workspace-setup]
- Detail: _build/tasks/07-voice/sub-02/07-02x.md

### [voice-trigger-hook]
> State-aware auto-voice hook: detects check-in/buffer-alert headings in system prompt, evaluates 6-state x 2-trigger matrix, injects Voice Delivery instruction block for LLM to use SpeakTool — env var toggle, SOUL.md+HEARTBEAT.md voice guidance — 50 tests
- Status: DONE
- Task: 07/sub-03
- Files: voice_trigger_hook.py, tests/test_voice_trigger_hook.py, workspace/SOUL.md, workspace/HEARTBEAT.md, .env.example
- Depends on: [scheduling-heartbeat-integration], [buffer-heartbeat-hook], [cognitive-state-detection], [voice-delivery-speak-tool]
- Detail: _build/tasks/07-voice/sub-03/07-03x.md

### [dashboard-complete]
> Always-on Fire Tablet dashboard: stdlib HTTP API (5 data endpoints + /config), dark-theme HTML/CSS/JS frontend (auto-refresh 30s), cognitive state persistence, Python launcher (start.py) — glanceable passive display for state, tasks, buffers, schedule, activity
- Status: DONE-WITH-ISSUES
- Task: 08 (08-dashboard)
- Subtasks: [dashboard-data-api], [dashboard-frontend], [dashboard-startup-integration]
- Produces: Complete dashboard surface for Fire Tablet. start.py is the single entry point launching nanobot gateway + dashboard server in parallel. dashboard_api.py serves 6 endpoints (state/tasks/buffers/schedule/activity/config) from existing stores with CORS. Frontend auto-refreshes at server-configured interval. cognitive_state_writer.py persists state from StateResponseHook to disk for dashboard consumption. SOUL.md teaches bot dashboard awareness. DASHBOARD.md documents Fire Tablet Silk browser setup. setup_workspace.py creates data/ dir. This is the final task — all 8 tasks complete.
- Issues: (1) MEDIUM: resolve_static_file path traversal — str.startswith bypassed by sibling dirs, fix with Path.is_relative_to(). (2) MEDIUM: read_cognitive_state() doesn't handle corrupt JSON — will crash /state endpoint. (3) LOW: fetchJSON doesn't check response.ok. (4) task-verify.md was not generated — no task-level cross-subtask verification exists.
- Detail: _build/tasks/08-dashboard/sub-03/08-03x.md (latest subtask; no task-verify.md)

### [dashboard-data-api]
> Read-only HTTP API (stdlib http.server) serving cognitive state, tasks, buffers, schedule, and activity feed as JSON — plus cognitive state persistence from StateResponseHook to disk
- Status: DONE-WITH-ISSUES
- Task: 08/sub-01
- Files: dashboard_api.py, cognitive_state_writer.py, state_response_integration.py, tests/test_dashboard_api.py, tests/test_cognitive_state_writer.py, .env.example
- Depends on: [task-data-model-store], [buffer-data-model-store], [checkin-schedule-engine], [memory-entry-store], [cognitive-state-detection], [state-response-integration]
- Issues: (1) MEDIUM: resolve_static_file path traversal — str.startswith prefix check bypassed by sibling dirs, fix with Path.is_relative_to(). (2) MEDIUM: read_cognitive_state() doesn't handle corrupt JSON, will 500 on /state. (3) MEDIUM: ROUTES dict dead code. (4) LOW: 5 unused imports in dashboard_api.py. (5) LOW: DASHBOARD_STATIC_DIR missing from .env.example.
- Detail: _build/tasks/08-dashboard/sub-01/08-01x.md

### [dashboard-frontend]
> Fire Tablet dark-theme dashboard: cognitive state banner, buffer gauges, tasks, schedule, activity feed — auto-refreshes 30s, static serving in dashboard_api.py, 39 tests passing
- Status: DONE
- Task: 08/sub-02
- Files: dashboard/index.html, dashboard/style.css, dashboard/app.js, dashboard_api.py, tests/test_dashboard_static.py, tests/test_dashboard_api.py
- Depends on: [dashboard-data-api], [cognitive-state-detection], [task-data-model-store], [buffer-data-model-store], [checkin-schedule-engine]
- Issues: (1) MEDIUM (pre-existing): str.startswith path traversal bypass in resolve_static_file — use is_relative_to(). (2) LOW: ROUTES dict + unused imports dead code. (3) LOW: fetchJSON doesn't check response.ok.
- Detail: _build/tasks/08-dashboard/sub-02/08-02x.md

### [dashboard-startup-integration]
> Dashboard config endpoint, Python launcher (start.py), SOUL.md awareness, Fire Tablet docs, setup_workspace.py data dir — wires dashboard into project startup
- Status: DONE
- Task: 08/sub-03
- Files: start.py, dashboard_api.py, dashboard/app.js, .env.example, workspace/SOUL.md, workspace/DASHBOARD.md, setup_workspace.py, tests/test_dashboard_integration.py
- Depends on: [dashboard-data-api], [dashboard-frontend], [nanobot-workspace-setup]
- Detail: _build/tasks/08-dashboard/sub-03/08-03x.md

### [bug-fixes-test-health-complete]
> Full bug fix and test suite health pass: verified 2 prior bug fixes, fixed 38 async test failures, split 3 oversized test files — 867 tests passing, 0 failures
- Status: DONE
- Task: 10 (10-bug-fixes)
- Subtasks: [state-detection-bugs-verified], [async-test-fixes], [test-file-splits]
- Produces: Clean test suite (867 pass, 0 fail), all test files under 300 lines, no dead code. Downstream tasks can trust test results.
- Detail: _build/tasks/10-bug-fixes/task-verify.md

### [async-test-fixes]
> Fixed 38 async test failures by replacing deprecated asyncio.get_event_loop().run_until_complete() with asyncio.run() in 4 test files
- Status: DONE
- Task: 10/sub-02
- Files: tests/test_memory_context.py, tests/test_memory_integration.py, tests/test_voice_tools.py, tests/test_voice_trigger_hook.py
- Depends on: [voice-trigger-hook], [memory-context-injection]
- Detail: _build/tasks/10-bug-fixes/sub-02/10-02x.md

### [custom-gateway-core]
> Custom nanobot gateway module: initializes all stores, creates 5 hooks in chain order, registers 14 tools, replicates stock gateway with hook/tool injection
- Status: DONE-WITH-ISSUES
- Task: 09/sub-01
- Files: custom_gateway.py, gateway_runner.py, hook_adapter.py, tests/test_custom_gateway.py
- Depends on: [state-response-integration], [memory-context-injection], [scheduling-heartbeat-integration], [buffer-heartbeat-hook], [voice-trigger-hook], [nanobot-task-tools], [nanobot-buffer-tools], [nanobot-memory-tools], [voice-delivery-speak-tool]
- Detail: _build/tasks/09-custom-gateway/sub-01/09-01x.md

### [test-file-splits]
> Split 3 oversized test files into 7 files (all under 300 lines), removed unused imports — no behavior changes
- Status: DONE
- Task: 10/sub-03
- Files: tests/test_schedule_engine.py, tests/test_schedule_engine_filters.py, tests/test_scheduling_hook.py, tests/test_scheduling_hook_pure.py, tests/test_scheduling_hook_content.py, tests/test_voice_trigger_hook.py, tests/test_voice_trigger_pure.py
- Depends on: [async-test-fixes]
- Detail: _build/tasks/10-bug-fixes/sub-03/10-03x.md

### [start-py-integration]
> Updated start.py to use custom gateway directly instead of subprocess — dashboard thread unchanged, clean shutdown preserved
- Status: DONE
- Task: 09/sub-02
- Files: start.py, gateway_runner.py
- Depends on: [custom-gateway-core]
- Detail: _build/tasks/09-custom-gateway/sub-02/09-02x.md

### [config-hardening]
> Hardened config template: sendProgress false, maxToolIterations 10, env-var timezone — prevents thinking leaks, runaway costs, timezone bugs
- Status: DONE
- Task: 09/sub-03
- Files: workspace/config.json.template, .env.example, setup_workspace.py, tests/test_bot_smoke.py, tests/test_setup_workspace.py
- Depends on: [nanobot-workspace-setup], [custom-gateway-core]
- Detail: _build/tasks/09-custom-gateway/sub-03/09-03x.md

### [custom-gateway-complete]
> Custom gateway with all hooks and tools wired: 5 hooks in chain order, 14 tools registered, subprocess replaced with direct call, config hardened — the ROOT CAUSE fix for personality/scheduling/buffers/voice not working
- Status: DONE-WITH-ISSUES
- Task: 09 (09-custom-gateway)
- Subtasks: [custom-gateway-core], [start-py-integration], [config-hardening]
- Produces: Working custom gateway that registers all hooks and tools built in tasks 02-07. start.py launches it directly. Config prevents thinking leaks, runaway costs, and timezone bugs. Downstream: Task 11 (Disco) can now add its hook to the chain.
- Issues: (1) MEDIUM: gateway_runner.py relies on 3 private nanobot APIs. (2) LOW: E2E testing requires nanobot installed.
- Detail: _build/tasks/09-custom-gateway/task-verify.md

### [disco-config-voices]
> Disco Elysium voice config: 4 voices (Volition/Empathy/Logic/Inland Empire), YAML definitions, state-conditional activation, env var toggle — cost-controlled at ~$0.18/month
- Status: DONE
- Task: 11/sub-01
- Files: disco_config.py, workspace/disco_voices.yaml, tests/test_disco_config.py
- Depends on: [cognitive-state-detection]
- Detail: _build/tasks/11-disco-flavor/sub-01/11-01x.md

### [disco-daisy-chain]
> 3-voice daisy chain engine: Volition first, each voice selects next, graceful partial results on error, injectable LLM callable — 31 tests
- Status: DONE
- Task: 11/sub-02
- Files: disco_engine.py, tests/test_disco_engine.py, tests/test_disco_chain.py
- Depends on: [disco-config-voices]
- Detail: _build/tasks/11-disco-flavor/sub-02/11-02x.md

### [disco-hook-integration]
> DiscoHook (6th in chain) using finalize_content to prepend inner voice commentary, conditional activation, SOUL.md disco awareness section
- Status: DONE
- Task: 11/sub-03
- Files: disco_hook.py, custom_gateway.py, workspace/SOUL.md, tests/test_disco_hook.py, tests/test_disco_hook_activation.py
- Depends on: [disco-daisy-chain], [disco-config-voices], [custom-gateway-core]
- Detail: _build/tasks/11-disco-flavor/sub-03/11-03x.md

### [disco-flavor-complete]
> Disco Elysium inner voice system: 4 voices, 3-voice daisy chain, state-conditional activation, finalize_content hook — adds personality commentary in avoidance/overwhelm/rsd states
- Status: DONE
- Task: 11 (11-disco-flavor)
- Subtasks: [disco-config-voices], [disco-daisy-chain], [disco-hook-integration]
- Produces: Complete inner voice layer. DiscoHook (6th in chain) runs 3-voice commentary chain after main response. Volition always speaks first, selects next voice. Only activates for emotional states (avoidance/overwhelm/rsd). Cost: ~$0.54/month. Configurable via YAML + env vars. SOUL.md teaches the LLM about the voices.
- Issues: (1) LOW: Tests can't run locally without nanobot installed. (2) LOW: No intent classification system yet for skip_intents.
- Detail: _build/tasks/11-disco-flavor/task-verify.md

### [pytest-collection-stabilization]
> Pytest now collects and passes the full suite from .venv: pytest.ini pins testpaths/pythonpath/norecursedirs, root conftest guards nanobot import with actionable error, requirements-dev.txt inherits runtime deps and adds pytest — 996 collected, 994 passed, 2 skipped, 0 errors
- Status: DONE
- Task: 12/sub-01
- Files: pytest.ini, conftest.py, requirements-dev.txt, tests/test_pytest_setup.py, README.md
- Depends on: [nanobot-workspace-setup], [async-test-fixes]
- Detail: _build/tasks/12-stabilization/sub-01/12-01x.md

### [workspace-deploy-memory-seed-and-model-pin]
> setup_workspace.py now deploys workspace/memory/MEMORY.md to ~/.nanobot/workspace/memory/ via pathlib subpath entries, and config.json.template pins the active model to x-ai/grok-4.1-fast (from openai/gpt-oss-120b) — byte-identical deploy verified, 997 passed / 2 skipped, zero runtime-path code changed
- Status: DONE
- Task: 12/sub-02
- Files: setup_workspace.py, workspace/config.json.template, tests/test_setup_workspace.py, tests/test_bot_smoke.py
- Depends on: [pytest-collection-stabilization], [nanobot-workspace-setup], [config-hardening], [memory-context-injection]
- Detail: _build/tasks/12-stabilization/sub-02/12-02x.md

### [nl-time-phrase-parser]
> Pure tz-aware natural-language time parser lifted from ReminderBot: parse_time_phrase(text, now) -> ParseResult | None with frozen dataclass (when/remaining_text/is_precise), required tz-aware now (ValueError on naive), mypy --strict clean, 33 tests (15 ported + 18 new), 1030 suite passing
- Status: DONE
- Task: 13/sub-01
- Files: nl_time_parser.py, tests/test_nl_time_parser.py, requirements.txt
- Depends on: [config-hardening]
- Detail: _build/tasks/13-nl-time-parsing/sub-01/13-01x.md

### [nl-time-task-tool-wiring]
> CreateTaskTool and UpdateTaskTool now accept ISO 8601 OR natural-language due_date via resolve_due_date(value, now) in task_time_helpers.py — ISO-first, NL-fallback, tz-aware via NANOBOT_TIMEZONE (defaults to UTC). Contract error `"could not parse time phrase '<value>'. Expected ISO 8601 … or natural-language phrase …"` is the terminal message for unrecognised input. SOUL.md teaches the LLM to pass phrases verbatim. task_tools.py split under the 300-line cap. 23 new tests, 1053 suite passing, mypy --strict clean on the new helper.
- Status: DONE-WITH-ISSUES
- Task: 13/sub-02
- Files: task_time_helpers.py, task_tools.py, tests/test_task_tools_nl_time.py, tests/test_task_tools.py, workspace/SOUL.md
- Depends on: [nl-time-phrase-parser], [nanobot-task-tools], [config-hardening]
- Issues: (1) MEDIUM: commit bundles unrelated SOUL.md Personality Voices → Disco Flavor Layer replacement (Task 11/sub-03 uncommitted work swept in) — violates AC #9's "no other sections modified" literally, zero behavioural impact. (2) LOW: tests/test_task_tools_registry.py holds the 3 registry-wiring tests moved out of test_task_tools.py but remains untracked in git. (3) LOW: .env.example documents `America/New_York` while code default is `UTC` when env var is unset — intentional asymmetry.
- Detail: _build/tasks/13-nl-time-parsing/sub-02/13-02x.md

### [nl-time-integration-clarification-lock]
> 13-test end-to-end integration suite locking the CreateTaskTool/UpdateTaskTool → resolve_due_date → parse_time_phrase path against frozen-`now` scenarios (happy-path NL, ISO regression, mixed sequence, update flow, self-correcting input, unparseable/empty clarification triggers, Friday-on-Friday ambiguity) + SOUL.md `### When Time Parsing Fails` subsection teaching the LLM to ask for restatement on parse failure (never silently drop due_date). 289-line test file, mypy --strict clean, 1053 → 1066 suite passing, zero regressions, frozen files (nl_time_parser.py, task_tools.py, task_time_helpers.py, task_store.py) untouched.
- Status: DONE
- Task: 13/sub-03
- Files: tests/test_task_tools_nl_integration.py, workspace/SOUL.md
- Depends on: [nl-time-phrase-parser], [nl-time-task-tool-wiring]
- Detail: _build/tasks/13-nl-time-parsing/sub-03/13-03x.md

### [code-hygiene-gateway-rules]
> Custom-gateway code-drift cleanup + code-rules mutable-default rule consolidation. `register_all_tools` returns a computed sum of four per-registrar counts (each registrar now returns `int`) instead of the hardcoded literal 13; `create_hooks` docstring now accurately describes "5 base hooks plus an optional DiscoHook"; `hook_adapter.py` carries a WHY comment explaining the log-and-swallow pattern; code-rules.md collapses the two overlapping mutable-default bullets into a single Universal Rules statement. Zero runtime behaviour change (same hooks, same tool counts, same log messages — now %d-formatted against computed counts). Test count-contract assertions locked at the per-registrar level so future regressions are caught where the drift would occur. 1066 passed, 2 skipped.
- Status: DONE
- Task: 12/sub-03
- Files: custom_gateway.py, hook_adapter.py, task_tools.py, buffer_tools.py, memory_tools.py, voice_tools.py, _build/code-rules.md, tests/test_custom_gateway.py, tests/test_task_tools_registry.py, tests/test_buffer_tools.py, tests/test_memory_tools.py, tests/test_voice_tools.py
- Depends on: [pytest-collection-stabilization], [custom-gateway-core], [disco-hook-integration], [nanobot-task-tools], [nanobot-buffer-tools], [nanobot-memory-tools], [voice-delivery-speak-tool]
- Detail: _build/tasks/12-stabilization/sub-03/12-03x.md

### [gcal-mcp-server-wiring]
> Vendor google-calendar-mcp TypeScript server at commit 0f2c9c5d (v2.6.1) under mcp/google-calendar/, wire into workspace/config.json.template as tools.mcpServers.google-calendar with ${ADHD_REPO_ROOT}/${GOOGLE_OAUTH_CREDENTIALS}/${GOOGLE_CALENDAR_MCP_TOKEN_PATH} placeholders, add gcal_setup.py (is_gcal_enabled, strip_gcal_mcp_server, build_google_calendar_mcp) for feature-flag-gated npm install/run build + 0700 token dir, extend setup_workspace.py to short-circuit when GOOGLE_CALENDAR_ENABLED=false and strip the MCP entry from the resolved config, .env.example gains 4 new entries (flag + 3 paths), .gitignore blocks node_modules/build/real-oauth-keys with gcp-oauth.keys.example.json negation. 39 new tests (28 build+vendor+gitignore+env, 11 template-shape+flag+secrets), 1105 passed / 2 skipped, mypy --strict clean on gcal_setup.py, setup_workspace.py, and both test files. package.json byte-identical to references/ drop (sha256 match). Upstream .git/.github/.claude dirs stripped.
- Status: DONE
- Task: 14/sub-01
- Files: gcal_setup.py, setup_workspace.py, workspace/config.json.template, .env.example, .gitignore, mcp/google-calendar/ (vendored tree, frozen), mcp/google-calendar/.vendor-source.md, tests/test_setup_workspace_gcal.py, tests/test_config_template_gcal.py
- Depends on: [nanobot-workspace-setup], [config-hardening], [workspace-deploy-memory-seed-and-model-pin], [pytest-collection-stabilization]
- Detail: _build/tasks/14-google-calendar-mcp/sub-01/14-01x.md

### [gcal-python-tool-wrappers]
> Three read-only Python Tool wrappers (`get_upcoming_events`, `list_events_in_window`, `check_free_busy`) over the vendored google-calendar MCP server: 60s TTL+FIFO `CalendarCache` keyed by canonical-JSON of input args (not derived timestamps), `CalendarMCPClient` that lazily resolves `mcp_google-calendar_<tool>` wrappers in the live ToolRegistry and returns `{"error": "calendar_unavailable"|"calendar_mcp_failure", "detail": ...}` JSON envelopes instead of raising, `register_calendar_tools(registry, cache, client) -> 3` wired into `custom_gateway.register_all_tools` behind `is_gcal_enabled(os.environ)`. Defense-in-depth read-only enforcement: `enabledTools: ["list-events", "get-freebusy"]` in workspace/config.json.template hides the 5 write-capable upstream tools at the nanobot layer; SOUL.md `## Calendar` section (between Dashboard and Disco Flavor Layer, +38 lines, surgical diff) teaches the LLM the read-only constraint and offers `create_task`/`save_memory` as the closest write alternative. Cache key uses inputs (hours_ahead, calendar_id, sorted calendar_ids) so identical-intent calls coalesce within the TTL window. mypy --strict clean on the 3 source files; 57 new tests (cache TTL/FIFO/eviction, client dispatch + envelope coercion, per-tool dispatch shapes + cache-key order insensitivity, registry wiring + write-name absence, env-flag matrix); pytest 1162 passed / 2 skipped.
- Status: DONE
- Task: 14/sub-02
- Files: calendar_cache.py, calendar_mcp_client.py, calendar_tools.py, custom_gateway.py, workspace/config.json.template, workspace/SOUL.md, tests/test_calendar_cache.py, tests/test_calendar_mcp_client.py, tests/test_calendar_tools.py, tests/test_calendar_tools_registry.py, tests/test_custom_gateway_gcal.py
- Depends on: [gcal-mcp-server-wiring], [custom-gateway-core], [code-hygiene-gateway-rules], [neuroaffirming-personality]
- Detail: _build/tasks/14-google-calendar-mcp/sub-02/14-02x.md

### [calendar-context-hook]
> Morning-only calendar-context injection closing Task 14: `CalendarContextHook` (chain position 4, after `SchedulingHook`, before `BufferHook`) detects `## Active Check-In: Morning Motivation|Morning Plan` headings in the system prompt and appends `### Today's Calendar` with up to 8 short event lines (24h times, location suffix, "nothing scheduled — free day" fallback). State-gated via `ALLOWED_STATES = {baseline, focus, avoidance, rsd}` — hyperfocus/overwhelm skip injection. Shares a `CalendarCache`/`CalendarMCPClient` instance with the sub-02 tools; `CalendarMCPClient.__init__(registry=None)` + `set_registry()` added for deferred wiring so the hook is constructable before `AgentLoop` builds its `ToolRegistry`. Structured error envelopes (`calendar_unavailable`, `calendar_mcp_failure`) and malformed payloads collapse to an `[Calendar unavailable — ... /calendar_auth or CALENDAR.md]` marker that the LLM voices per SOUL.md's new "When Calendar Is Unavailable" sub-subsection. WARNING logs rate-limited 1/hr per hook instance. New `workspace/CALENDAR.md` (127 lines) ships via `setup_workspace.TEMPLATE_FILES`. HEARTBEAT.md gets "Morning Check-Ins See Today's Calendar" section. Feature-flag OFF path costs zero (no cache, no client, hook not in chain). 71 new tests (43 pure-function, 16 hook-lifecycle, 5 chain-integration, 4 deploy, 3 gateway chain-order), 1233 passed / 2 skipped, mypy --strict clean on `calendar_hook.py` and the 4 new test files.
- Status: DONE-WITH-ISSUES
- Task: 14/sub-03
- Files: calendar_hook.py, custom_gateway.py, gateway_runner.py, calendar_mcp_client.py, setup_workspace.py, workspace/SOUL.md, workspace/HEARTBEAT.md, workspace/CALENDAR.md, tests/test_calendar_hook.py, tests/test_calendar_hook_format.py, tests/test_calendar_integration.py, tests/test_setup_workspace_calendar_md.py, tests/test_custom_gateway.py
- Depends on: [gcal-python-tool-wrappers], [gcal-mcp-server-wiring], [scheduling-heartbeat-integration], [buffer-heartbeat-hook], [voice-trigger-hook], [neuroaffirming-personality], [custom-gateway-core]
- Issues: (1) MEDIUM: tests/test_custom_gateway.py grew from 289 → 358 lines, breaking the 300-line cap (`code-rules.md:27`). Split out the three new calendar-chain tests or lift `TestRegisterAllTools` into its own file. (2) LOW: `UNAVAILABLE_LINE` hard-codes "authorization has expired" for all failure envelopes — misleads the user on non-OAuth failures (`calendar_mcp_failure`, parser errors). (3) LOW: `UNAVAILABLE_LINE` references `/calendar_auth` which has no slash-command handler wired (spec non-goal #3) — align with `CALENDAR.md`'s actual `npm run auth` flow. (4) LOW: broad `except Exception` in `before_iteration` swallows silently — matches hook-adapter convention but warrants a one-line WHY comment.
- Detail: _build/tasks/14-google-calendar-mcp/sub-03/14-03x.md

### [stabilization-cleanup]
> Final Task 12 cleanup: audit folder `bugs and issues with project/` moved on-disk to `_build/audits/2026-04-17/` (6 files), `.gitignore` gains `*.log` + `logs/` so `bot.log` and `logs/adhd_assistant.log` stop appearing as untracked (files remain on disk — `bot.log` is the 2026-04-16 runtime baseline), `REVERT_RESULTS.md` deleted (stale 2026-04-15 provider-switch scratch; content superseded by committed config.json.template + pinned memory). Regression gate: pytest 1066 passed / 2 skipped, AST-parse over 9 gateway/dashboard/start files clean, config.json.template JSON round-trip clean, setup_workspace.py deploys `memory/MEMORY.md` to throwaway HOME. Phase 2 baseline: test suite green, deploy complete, model pinned, code-rules reconciled, drift cleaned, audit archived, working tree clean. Only `.gitignore` entered git history (archive lives under gitignored `_build/`, by design — reversible with one `git add -f`).
- Status: DONE
- Task: 12/sub-04
- Files: .gitignore, _build/audits/2026-04-17/00-SUMMARY.md, _build/audits/2026-04-17/01-task09-gateway-audit.md, _build/audits/2026-04-17/02-task10-test-health.md, _build/audits/2026-04-17/03-task11-disco-audit.md, _build/audits/2026-04-17/04-missing-integrations.md, _build/audits/2026-04-17/05-smoke-test.md
- Depends on: [pytest-collection-stabilization], [workspace-deploy-memory-seed-and-model-pin], [code-hygiene-gateway-rules]
- Detail: _build/tasks/12-stabilization/sub-04/12-04x.md

### [magicmirror-vendor-and-config]
> Vendor MagicMirror² core (v2.35.0) + MMM-WebHookAlerts (v1.1.0) + MMM-Markdown (v1.0.0) + MMM-pages (v1.4.0) under `magicmirror/`; hand-authored `config/config.js.template` wires a 3-page class-based layout (`page0`=tasks, `page1`=state_buffers, `page2`=schedule, rotating 20s) with three webhook templates (`state_change`, `buffer_alert`, `missed_checkin`) in `fullscreen_above` and a fixed `clock`; `magicmirror_setup.py` exports `is_magicmirror_enabled`, `detect_node_npm`, `build_magicmirror`, `render_magicmirror_config`, `MAGICMIRROR_WEBHOOK_TEMPLATE_NAMES`, `MODULE_NAMES`, `MAGICMIRROR_CONFIG_VARS`; core `npm install` passes `--ignore-scripts` (defuses upstream `postinstall` `git clean -df`), module installs do not; freshness check compares `node_modules/` mtime to `package-lock.json` mtime; `render_magicmirror_config` substitutes 3 `${MAGICMIRROR_*}` placeholders with env→default fallback and writes gitignored `config.js`. `setup_workspace()` invokes `build_magicmirror` + `render_magicmirror_config` after the gcal flow, flag-gated by `MAGICMIRROR_ENABLED=false`. `.env.example` gains 6 entries (flag + host + port + ipWhitelist JSON + webhook host/port); `.gitignore` blocks `magicmirror/node_modules/`, `magicmirror/modules/MMM-*/node_modules/`, `magicmirror/config/config.js`. 4 `.vendor-source.md` pins with commit + version + stripped-dirs list. 63 new tests (21 setup + 42 template/vendor/gitignore/env), pytest 1296 passed / 2 skipped, mypy --strict clean. Flag-off default path costs zero (no npm, no filesystem work). Security gap documented: MMM-WebHookAlerts has no source-IP check; `ipWhitelist` widening to RFC1918 makes the webhook LAN-reachable rather than loopback-only — mitigation deferred to sub-03.
- Status: DONE-WITH-ISSUES
- Task: 15/sub-01
- Files: magicmirror_setup.py, setup_workspace.py, magicmirror/ (vendored tree), magicmirror/.vendor-source.md, magicmirror/modules/MMM-WebHookAlerts/ (vendored) + .vendor-source.md, magicmirror/modules/MMM-Markdown/ (vendored) + .vendor-source.md, magicmirror/modules/MMM-pages/ (vendored) + .vendor-source.md, magicmirror/config/config.js.template, .env.example, .gitignore, tests/test_magicmirror_setup.py, tests/test_magicmirror_config_template.py
- Depends on: [nanobot-workspace-setup], [config-hardening], [gcal-mcp-server-wiring], [pytest-collection-stabilization]
- Issues: (1) MEDIUM: `ipWhitelist` widened to RFC1918 LAN ranges exposes `POST /webhook` to any LAN device — spec says "reject requests not from the local machine." MMM-WebHookAlerts performs no source-IP check (delegates to MM Express `ipWhitelist`). Documented in module `.vendor-source.md`; mitigation deferred (would require patching the vendored module and breaking byte-identity, or a reverse-proxy rule in sub-03). (2) LOW: `strip_magicmirror_config` reserve-hook from description §2 omitted — MM config is not in `workspace/config.json.template`, so the hook would be empty (anti-slop rule #1). (3) LOW: `render_magicmirror_config` does not validate `MAGICMIRROR_PORT` is numeric — a typo produces invalid JS. (4) LOW: `_is_install_fresh` treats a missing `package-lock.json` as "fresh" — rare corner case, inverts to an unnecessary skip.
- Detail: _build/tasks/15-magicmirror-display/sub-01/15-01x.md

### [magicmirror-webhook-client-and-feeds]
> Pure-Python MagicMirror² feeders: `magicmirror_webhook.py` exports three frozen dataclass payloads (`StateChangePayload`, `BufferAlertPayload`, `MissedCheckinPayload`) whose `template_name` ClassVar is unpacked from `MAGICMIRROR_WEBHOOK_TEMPLATE_NAMES` (zero literal duplication, locked by source-grep test); each `to_json_body()` re-keys richer Python fields to the flat Mustache placeholders the vendored `config.js.template` actually renders (`{{state}}`, `{{buffer}}`, `{{level}}`, `{{capacity}}`, `{{checkin_type}}`), with a parametrized test that scrapes the template for every `{{key}}` and asserts body coverage — future template edits break the test instantly. `validate_local_url` accepts loopback (`127.0.0.0/8`, `localhost`, `::1`, `[::1]`) and rejects RFC1918 + public IPs + hostnames + URLs without host, message naming the rejected host. `send_alert_sync(payload, base_url, timeout=3.0) -> SendResult` POSTs via stdlib `urllib.request.urlopen` (no `httpx` dep) and folds three exception branches (`HTTPError`, `socket.timeout`, `URLError`) into a frozen `SendResult(ok, status_code, error, template_name)` — never raises on transport. `send_alert_async` submits to a module-level `ThreadPoolExecutor(max_workers=2)` lazy-initialized under a `Lock`, with `atexit.register(shutdown_webhook_pool)` (registered on first pool creation, not at import time, to keep imports side-effect-free); `shutdown_webhook_pool` swaps the global under the lock then calls `pool.shutdown(wait=False, cancel_futures=True)` outside the lock — idempotent and re-creates the pool on next `send_alert_async`. `magicmirror_feeds.py` exports three pure renderers (`render_tasks_markdown` groups active/completed-today/blocked sorted by due-date|updated_at|title with italic `_No …._` placeholders; `render_state_buffers_markdown` emits `## Cognitive state: {state}` + `## Buffers` with `(low)` plain-text marker at-or-below threshold; `render_schedule_markdown` distinguishes done-today/due-in/overdue/missed-today against caller-supplied tz-aware `now` — strips tz before combining with naive `entry.target_time`). Atomic `write_feeds(feed_dir, …)` writes each of the three files via `_atomic_write` (`Path.write_text(..., encoding="utf-8", newline="\n")` to a `.tmp` then `Path.replace` for cross-platform `os.replace` semantics) — interrupted writes leave prior feed files intact. `resolve_feed_dir(repo_root)` is the single source of truth for `magicmirror/modules/MMM-Markdown/markdown/`. "Blocked" task grouping uses `"blocked" in task.tags` (no `Task` model change needed). `render_state_buffers_markdown` accepts and `del`s `now` for caller-side signature symmetry. 6 new files, all under 300 lines (max 276); 63 new tests across 4 test files, full suite 1359 passed / 2 skipped (zero regressions); mypy --strict clean on all 6 new files. Sub-03 still owns: hook wiring, `MAGICMIRROR.md` user docs, gitignoring the three feed `.md` files, source-IP hardening on the webhook receiver (sub-01's MEDIUM M1 carries forward), and the implicit contract that callers pass `now` in `NANOBOT_TIMEZONE`.
- Status: DONE
- Task: 15/sub-02
- Files: magicmirror_webhook.py, magicmirror_feeds.py, tests/test_magicmirror_webhook_payloads.py, tests/test_magicmirror_webhook_client.py, tests/test_magicmirror_feeds_render.py, tests/test_magicmirror_feeds_write.py
- Depends on: [magicmirror-vendor-and-config], [task-data-model-store], [buffer-data-model-store], [checkin-schedule-engine], [cognitive-state-detection]
- Issues: (1) LOW: `_clean_webhook_pool` autouse fixture in `tests/test_magicmirror_webhook_client.py:76` is annotated `-> Any` instead of `-> Iterator[None]` — semantic-typing nit. (2) LOW: `render_schedule_markdown` strips `tzinfo` from `now` before combining with naive `entry.target_time`; renders correctly only when caller passes `now = datetime.now(ZoneInfo(NANOBOT_TIMEZONE))`. Contract is implicit; sub-03 should document or add an explicit `tzinfo` parameter. (3) LOW: `BufferAlertPayload.to_json_body()` emits `threshold` and `timestamp` not referenced by the current Mustache template — intentional auditability surface, not a bug.
- Detail: _build/tasks/15-magicmirror-display/sub-02/15-02x.md

### [magicmirror-hook-integration-and-docs]
> Closes Task 15 by wiring sub-02's webhook client + feed renderer into the live agent: `MagicMirrorHook` is slotted between `VoiceHook` and any `DiscoHook` via a new conditional branch in `hook_factory.create_hooks(repo_root, env)`. `before_iteration` gates on `is_scheduled_session()` (heartbeat-only, zero cost in chat turns) and runs four steps — `_dispatch_state_change`, `_dispatch_buffer_alerts`, `_dispatch_missed_checkins`, `_refresh_feeds` — each wrapped in per-step try/except with a rate-limited WARN (1/hr per hook instance via pure `should_log_error` predicate) so a broken webhook or disk-full cannot crash the agent loop. Dedup is in-memory (`_last_dispatched_state: StateName|None`, `_buffer_dispatched: set[(str, date)]`, `_missed_dispatched: set[(str, date)]`) — first heartbeat after restart primes state without dispatching; per-day keys mean a single duplicate after restart is the accepted tradeoff for avoiding disk-backed dedup. Buffer-alert source chose structured `buffer_store.list_active_buffers()` over prompt scraping (decouples from BufferHook's prompt format). Missed-check-in detection lives in a new pure predicate `is_checkin_missed(entry, current_date, current_datetime)` — inverse of `checkin_schedule.is_checkin_due`, strips tz from `current_datetime` before combining with naive `entry.target_time`. Feed refresh is per-heartbeat (unconditional) — calls the three sub-02 renderers + `write_feeds` (atomic tmp+rename). Webhook sends route through `send_alert_async` (fire-and-forget pool from sub-02). State-transition dispatch deviates from description: reads current state via closure from `StateResponseHook.current_state`, not from `cognitive_state_writer.read_cognitive_state()` — first-post-restart tick won't fire a state_change even if state differs across the restart. Hook-chain refactor fell out of the 300-line cap: `custom_gateway.py` (358 → 137 lines) re-exports `HOOK_CHAIN_ORDER`, `DISCO_HOOK_NAME`, `LLMCallableWrapper`, `SessionFlag`, `create_hooks` from the new `hook_factory.py` (260 lines) for back-compat. `tests/test_custom_gateway.py` split into that file (145 lines) + `tests/test_hook_factory.py` (175 lines). `workspace/MAGICMIRROR.md` (97 lines, 8 parts: TL;DR → Env Vars → How Alerts Work → Pages → When It Breaks → Turning It Off) ships via `setup_workspace.TEMPLATE_FILES`; byte-identical deploy test added. `workspace/SOUL.md` gains a surgical `## Fire Tablet Display` block between `## Dashboard` and `## Calendar` — four read-only bullets teaching the LLM to reference the mirror as a glanceable surface without prompting refreshes. `.gitignore` blocks `magicmirror/modules/MMM-Markdown/markdown/*.md` with a `!examples.md` negation for the vendored sample. `gateway_runner.py` now passes `repo_root=Path(__file__).resolve().parent` and `env=dict(os.environ)` to `create_hooks`. 51 new tests across 5 files (20 pure-helper + 11 hook-lifecycle + 5 chain-integration + 4 deploy + 11 moved hook-factory), full suite 1393 passed / 2 skipped, dashboard regression 52 passed, mypy --strict clean on `magicmirror_hook.py` (pre-existing `state_detection.py` errors unchanged). Flag-off path (`MAGICMIRROR_ENABLED≠true` or `repo_root` unset) allocates no hook, starts no thread pool, writes no feed files.
- Status: DONE-WITH-ISSUES
- Task: 15/sub-03
- Files: magicmirror_hook.py, hook_factory.py, custom_gateway.py, gateway_runner.py, setup_workspace.py, workspace/MAGICMIRROR.md, workspace/SOUL.md, .gitignore, tests/test_magicmirror_hook_pure.py, tests/test_magicmirror_hook.py, tests/test_magicmirror_integration.py, tests/test_magicmirror_docs_deploy.py, tests/test_hook_factory.py, tests/test_custom_gateway.py
- Depends on: [magicmirror-vendor-and-config], [magicmirror-webhook-client-and-feeds], [scheduling-heartbeat-integration], [buffer-heartbeat-hook], [voice-trigger-hook], [state-response-integration], [custom-gateway-core], [calendar-context-hook], [disco-hook-integration]
- Issues: (1) LOW: `gateway_runner.py` at 304 lines exceeds the 300-line cap (`code-rules.md:27`). File existed on disk at this size before this subtask but was untracked; commit 22cd4c6 committed+modified it. Fix: extract `_setup_cron_callback` (57 lines) into its own module. (2) LOW: Commit 22cd4c6 bundles Task 14/sub-03's uncommitted SOUL.md Calendar section (~43 lines) into the task-15-03 commit because it was in the working tree — the Fire Tablet Display insertion itself is surgical; the commit is not task-15-only. Mirrors Task 13/sub-02 bundling. Zero behavioural impact. (3) LOW: `_dispatch_state_change` primes `_last_dispatched_state` on first tick with no disk read — a state transition across a restart is silently absorbed. Description asked for `cognitive_state_writer.read_cognitive_state()` bootstrap; impl report documents the deviation as a deliberate tradeoff. (4) LOW: `MagicMirrorHook.before_iteration` has an outer `try/except` that duplicates `HookAdapter`'s built-in swallow+log; justified by WHY comment as enabling rate-limited context-aware logging. (5) LOW: 8 required ctor kwargs on `MagicMirrorHook` — matches `SchedulingHook` convention and has a single call site; a config dataclass is not warranted.
- Detail: _build/tasks/15-magicmirror-display/sub-03/15-03x.md

### [taskwarrior-store-backend]
> Drop-in Taskwarrior-CLI backend for `TaskStore`'s public API — vendored tasklib 2.5.1 + `TaskwarriorStore` class with full signature parity (8 methods), Option-A `+started`-tag status mapping, description-as-first-annotation field layout, `taskrc_location="/"` user-taskrc sandboxing, per-platform install-hint RuntimeError when `task` binary missing. Flag-gated via `TASKWARRIOR_ENABLED` (default false, no-op in sub-01) with optional `TASKWARRIOR_DATA_DIR` override; `setup_workspace.build_taskwarrior` creates `workspace/data/taskwarrior/` only when enabled, logs WARN with platform-specific install command when enabled-but-missing. Extracted to `taskwarrior_setup.py` (55 lines) so `setup_workspace.py` stays at 283/300. TW UUID adopted as `Task.id` (36-char form accepted by `Task.id: str` without model change; `build_task` hex discarded per U1 research decision). 68 platform-independent tests (23 pure-mapping + 19 signature-parity + 18 setup + 8 vendor-sanity) always run; 19 real-binary CRUD-parity tests mirror every `test_task_store.py` case and skip cleanly when `shutil.which("task")` is None. Full suite 1461 pass / 3 skip (+68 from Task 15/sub-03 baseline 1393); `mypy --strict` clean on both modules; `task_store.py` and `task_tools.py` unmodified. `.env.example` + `.gitignore` extended; `requirements.txt` path-installs `./vendor/tasklib`. Four LOW issues noted: (L1) `get_task` after `delete_task` returns the soft-deleted row instead of KeyError — parity gap, no current consumer; (L2) `tw_task_to_our_task` modified-fallback chain has redundant None check; (L3) `build_task` UUID generated then discarded in `create_task`; (L4) `reload()` docstring is WHAT not WHY; (L5) `taskrc_location="/"` has no explicit Windows real-binary test (dev box skips, Mac works by construction). None block; sub-02 can proceed.
- Status: DONE
- Task: 16/sub-01
- Files: taskwarrior_store.py, taskwarrior_setup.py, setup_workspace.py, requirements.txt, .env.example, .gitignore, vendor/tasklib/ (vendored tree), vendor/tasklib/.vendor-source.md, tests/test_taskwarrior_store.py, tests/test_taskwarrior_store_contract.py, tests/test_taskwarrior_store_mapping.py, tests/test_taskwarrior_store_setup.py, tests/test_tasklib_vendored.py
- Depends on: [task-data-model-store], [gcal-mcp-server-wiring], [magicmirror-vendor-and-config], [pytest-collection-stabilization]
- Detail: _build/tasks/16-taskwarrior-syncall/sub-01/16-01x.md

### [task-store-factory-and-migration]
> `TaskStoreProtocol` (`@runtime_checkable`, 8 methods) appended to `task_store.py` as the shared contract for JSON + Taskwarrior backends. `task_store_factory.build_task_store(env, repo_root) -> TaskStoreProtocol` is the single pinch-point: `TASKWARRIOR_ENABLED=true` ⇒ lazy-import `TaskwarriorStore` (JSON-only deploys pay zero `tasklib` cost, guarded by subprocess-based `sys.modules` regression test), else `TaskStore(storage_path=repo_root/workspace/data/tasks.json)`. No silent fallback when `task` CLI is missing — `RuntimeError` propagates. `TASKWARRIOR_DATA_DIR` absolute-path override honoured; `~` expanded. Consumers re-wired: `custom_gateway.create_stores(data_dir, repo_root=None, env=None)` (back-compat defaults so existing tests pass unchanged), `gateway_runner.py` threads `repo_root=Path(__file__).resolve().parent` + `env=os.environ`, `dashboard_api.handle_tasks` + `_build_activity_feed` route through the factory via new `_repo_root()` module helper, `hook_factory.create_hooks` narrows its `stores["task"]` cast to `TaskStoreProtocol`, `magicmirror_hook.MagicMirrorHook.__init__` + all 5 `task_tools.py` tool ctors + `register_task_tools` annotated with the Protocol (zero runtime change). `taskwarrior_setup.taskwarrior_data_dir_is_empty` + `warn_if_migration_needed(enabled, json_path, tw_data_dir) -> bool` emit a setup-time WARNING when flag-on ∧ `tasks.json` exists ∧ TW dir empty (missing/empty/zero-byte `pending.data` all count as empty). `setup_workspace.py` calls the warner after `build_taskwarrior`. `scripts/migrate_json_to_taskwarrior.py` (268 lines, `argparse` CLI) ships the one-shot reversible import: `--source` (JSON path), `--data-dir` (TW data dir), `--dry-run`, `--force`; idempotency marker is a `migrated_<first-8-hex>` tag (second run is a no-op); source JSON opened read-only and never modified; per-task round-trip diff on `{title, description, status, priority, tags, due_date}` (excludes `{id, created_at, updated_at}` by sub-01's UUID+tasklib-timestamp policy); `--force` required only when the target has unrelated non-migrated tasks; exit codes `0|2|3|4`; per-run summary appended to `<data-dir>/taskwarrior_migration.log`; rollback instructions printed on stdout on success. 52 new tests across 6 files (10 factory + 29 protocol-parity + 10 migration e2e + 3 gateway + 3 dashboard + 8 setup-warn), full suite 1512 passed / 8 skipped (Taskwarrior-CLI-gated files skip at collection time). `mypy --strict` clean on `task_store_factory.py` + `scripts/migrate_json_to_taskwarrior.py`. **Production note:** the factory's path resolution moves the canonical `tasks.json` location from `~/.nanobot/data/tasks.json` to `<repo>/workspace/data/tasks.json` — gateway + dashboard agree, but pre-existing installs need a one-time file move; flagged as MEDIUM in the verify report for deployment follow-up.
- Status: DONE
- Task: 16/sub-02
- Files: task_store.py, task_store_factory.py, task_tools.py, custom_gateway.py, gateway_runner.py, dashboard_api.py, hook_factory.py, magicmirror_hook.py, taskwarrior_setup.py, setup_workspace.py, scripts/migrate_json_to_taskwarrior.py, tests/test_task_store_factory.py, tests/test_task_store_protocol.py, tests/test_custom_gateway_taskwarrior.py, tests/test_dashboard_api_taskwarrior.py, tests/test_migrate_json_to_taskwarrior.py, tests/test_taskwarrior_store_setup.py, tests/test_custom_gateway.py, tests/test_dashboard_api.py, tests/test_dashboard_integration.py
- Depends on: [taskwarrior-store-backend], [custom-gateway-core], [dashboard-data-api], [magicmirror-hook-integration-and-docs], [task-crud-complete]
- Issues: (1) MEDIUM: canonical `tasks.json` location moved from `~/.nanobot/data/tasks.json` (ADHD_DATA_DIR/DASHBOARD_DATA_DIR) to `<repo>/workspace/data/tasks.json` — `dashboard_api.handle_tasks` now accepts but ignores its `data_dir` kwarg (factory uses `_repo_root()` instead). Existing deployments need a one-time file move; migration-warn logic does not announce this. (2) LOW: migration round-trip diff relaxes acceptance criterion 6 by excluding `{id, created_at, updated_at}` — driven by sub-01's UUID+tasklib-timestamp policy, linkage preserved via `migrated_<prefix>` tag. (3) LOW: migration run-log path deviates from description (`<data-dir>/taskwarrior_migration.log` vs `workspace/data/taskwarrior_migration.log`) — deliberate co-location. (4) LOW (informational): `task_tools.py` (303) and `gateway_runner.py` (303) sit at the 300-line cap — pre-existing violations, not introduced by sub-02.
- Detail: _build/tasks/16-taskwarrior-syncall/sub-02/16-02x.md

### [syncall-gcal-daemon]
> Flag-gated long-running daemon bidirectionally syncing Taskwarrior ↔ a named Google Calendar via the vendored `references/syncall` tree (commit `14a2615`, frozen under `vendor/syncall/`). Install strategy deviates from the usual "vendor + pip install" pattern: syncall's upstream `pyproject.toml` uses `poetry-dynamic-versioning` (no git history in a vendored subtree ⇒ build failure) and pins PyYAML `~5.3.1` which conflicts with the repo's `pyyaml>=6.0`; instead, `conftest.py` + the daemon both prepend `vendor/syncall/` to `sys.path` and `requirements.txt` pins 10 transitive deps individually (`taskw-ng`, `xdg`, `google-api-python-client`, `google-auth-oauthlib`, `bidict`, `click`, `loguru`, `rfc3339`, `item-synchronizer`, `bubop`). Code split: `syncall_args.py` (182 lines, 100% pure — `SyncallArgsConfig` dataclass, `read_syncall_args_config(env)`, `build_syncall_args(config)`, `resolve_resolution_strategy` dual-accepting friendly aliases and upstream class names, `resolve_verbosity_tokens`); `syncall_setup.py` (152 lines — `is_syncall_enabled`, `resolve_syncall_paths`, `build_syncall`, `write_repo_scoped_taskrc` — writes repo-scoped taskrc at `workspace/data/syncall_cache/taskrc` so `~/.taskrc` is never touched); `syncall_daemon.py` (289 lines — preflight → signal-handled while-loop → per-tick `subprocess.run([sys.executable, "-m", "syncall.scripts.tw_gcal_sync", ...])` with layered env `TASKRC`+`TASKDATA`+`XDG_CONFIG_HOME`+`PYTHONPATH`, `SIGINT`/`SIGTERM`/`SIGBREAK` handlers flip a threading.Event, sleep is 1-second-sliced when `sleep_fn is time.sleep` so shutdown is prompt). Conflict resolution: `SYNCALL_RESOLUTION_STRATEGY=tw_wins` (default) → `--resolution-strategy AlwaysSecondRS` (Taskwarrior canonical, per spec's Phase-2 rationale); aliases `tw_wins | gcal_wins | most_recent | least_recent` map to the four upstream `*RS` class names. Poll cadence: 600s default, 60s minimum, env-configurable via `SYNCALL_POLL_SECONDS`. Additive `SYNCALL_TW_FILTER` env var mitigates sub-02's `migrated_<hex>`-tag flood risk (example `"-migrated"` documented in SYNCALL.md). `start.py` restructured: gateway now runs in-process via `gateway_runner.run_gateway()` (replacing the prior `subprocess.Popen([python, "-m", "nanobot", "gateway"])`), syncall daemon spawned as a child `subprocess.Popen` when `is_syncall_enabled(os.environ)`, shutdown via `proc.terminate()` → `wait(15s)` → `kill()`. Popen constructor is an injectable parameter so `test_start_py_syncall.py` uses a `_StubPopen` without real forks. OAuth pickle location accepted as upstream's hardcoded `~/.gcal_credentials.pickle` (no flag/env redirect exists; patching the vendor would break byte-identity); belt-and-braces `.gitignore` pattern added. 74 new tests across 7 files (17 pure args + 16 setup + 17 daemon + 5 vendor + 7 env + 6 start.py + 7 setup_workspace), full suite 1586 passed / 11 skipped (zero regressions from sub-02 baseline 1512); mypy --strict clean on all three new source files. Flag-off default path is zero-cost (no subprocess, no filesystem work). `workspace/SYNCALL.md` (152 lines) deployed via `TEMPLATE_FILES` — covers TL;DR, prerequisites, one-time OAuth ritual, conflict policy, new-event-in-GCal implicit-creation behaviour, poll cadence, healthy-log examples, troubleshooting (including the `SYNCALL_TW_FILTER="-migrated"` mitigation and the home-dir pickle explanation).
- Status: DONE-WITH-ISSUES
- Task: 16/sub-03
- Files: syncall_args.py, syncall_setup.py, syncall_daemon.py, start.py, setup_workspace.py, conftest.py, requirements.txt, .env.example, .gitignore, workspace/SYNCALL.md, vendor/syncall/ (vendored tree), vendor/syncall/.vendor-source.md, tests/test_syncall_args.py, tests/test_syncall_setup.py, tests/test_syncall_daemon.py, tests/test_syncall_vendored.py, tests/test_syncall_env_example.py, tests/test_start_py_syncall.py, tests/test_setup_workspace_syncall.py
- Depends on: [taskwarrior-store-backend], [task-store-factory-and-migration], [gcal-mcp-server-wiring], [magicmirror-vendor-and-config], [custom-gateway-core]
- Issues: (1) MEDIUM: `syncall_daemon._preflight` only imports the `syncall` namespace, not `syncall.scripts.tw_gcal_sync`. If transitive deps (`bubop`, etc.) are missing, the daemon boots past preflight and logs `sync FAILED code=1` every poll interval instead of exiting 2 as acceptance criterion #4 promises. Fix: add `import syncall.scripts.tw_gcal_sync` to the preflight, or run `--help` in a subprocess with timeout. (2) MEDIUM: Windows shutdown is a hard kill — `start.py:stop_syncall_daemon` uses `proc.terminate()` which maps to `TerminateProcess` on Windows (SIGKILL equivalent), bypassing the daemon's SIGTERM/SIGBREAK handlers. On macOS (deployment target) the path is clean; on Windows, sub-04's integration test should verify graceful shutdown via `CTRL_BREAK_EVENT` + `CREATE_NEW_PROCESS_GROUP`. (3) LOW: `install_signals: bool = True` on `main()` is a flag parameter — code-rules forbids them. Defensible for testability but cleaner extracted to a wrapper. (4) LOW: `tests/test_syncall_daemon.py:165` has a dead `patch("syncall_daemon.importlib", create=True)` — the daemon never touches `importlib`. (5) LOW: `start.py` also swapped the gateway from `subprocess.Popen([python, "-m", "nanobot", "gateway"])` to in-process `run_gateway(None, None)` — a behavioural change outside the subtask description. All pre-existing tests still pass but it deserves a separate commit / review.
- Detail: _build/tasks/16-taskwarrior-syncall/sub-03/16-03x.md

### [taskwarrior-migration-finalization]
> Closes Task 16 by proving, documenting, and rollback-locking the Taskwarrior backend swap. Cross-consumer integration suite (`tests/test_task16_integration.py`, 10 tests, module-skipped when `task` CLI absent) exercises the three production seams end-to-end against a real Taskwarrior binary: (a) `ToolRegistry.execute(create_task|list_tasks|get_task|update_task|complete_task)` via `register_task_tools(registry, tw_store)`, (b) `dashboard_api.handle_tasks` with `_repo_root` monkey-patched to the tmp repo and `TASKWARRIOR_ENABLED=true`+`TASKWARRIOR_DATA_DIR` env-set, (c) `MagicMirrorHook.before_iteration(ctx)` with the feed byte-matching `render_tasks_markdown(tw_store.list_tasks(), fixed_now)`. Cross-path coherence test proves a single tool-registry `create_task` is visible through both the dashboard endpoint and the MagicMirror `tasks.md` feed. `tests/test_task_store_rollback.py` (5 tests + 1 CLI-gated skip) locks AC #11 — with `TASKWARRIOR_ENABLED` missing or explicitly `"false"`, `build_task_store(env, repo_root)` returns a `TaskStore` instance; `workspace/data/tasks.json` remains readable post-migration; flag-on with CLI available returns `TaskwarriorStore`. `tests/test_magicmirror_hook_taskwarrior.py` (2 CLI-gated tests) isolates the MagicMirror data-source switch: tasks.md output equals `render_tasks_markdown(tw_store.list_tasks(), FIXED_NOW)` byte-for-byte, and newly-added rows appear on the next tick. `workspace/TASKWARRIOR.md` (138 lines) is the user-facing doc — 9 ordered sections (TL;DR → Why → Prerequisites → First-time setup → Operation → Migration script → Rollback → Interaction with syncall → Troubleshooting); carries a triple-redundant divergence warning ("Divergence warning." bold sub-heading + "Do not flip-flop the flag" + "Pick a backend and stay there") that `tests/test_taskwarrior_md_deploy.py` asserts by grep. Ships via `setup_workspace.TEMPLATE_FILES` (entry index 6, byte-identical after `copy_workspace_files`). `workspace/SOUL.md` gains a surgical `## Task Ledger` subsection (9 body lines) between the existing `## Fire Tablet Display` and `## Calendar` headings — placement deviates from the description's literal wording ("between Calendar and Fire Tablet Display") because the live file order is FTD→Calendar; the impl chose the non-regressing adjacency-preserving slot and documented the deviation. Section tells the LLM: backend may be TW or JSON, tool behaviour is identical, do not surface the switch unless asked, point users at TASKWARRIOR.md / SYNCALL.md, recognise the `Taskwarrior CLI` RuntimeError and direct users to the install doc. `task_store.py` gets a 6-line WHY prologue prepended to the module docstring ("JSON backend — fallback when `TASKWARRIOR_ENABLED=false`. Post-Task-16 the canonical task backend is `taskwarrior_store.TaskwarriorStore`...") — zero behavioural change, 249 → 255 lines. `_build/tasks/16-taskwarrior-syncall/task-verify.md` stub records the four-subtask closure, canonical-backend identity, sync daemon status, rollback procedure, divergence warning, and Phase-2 baseline lock. 29 new tests total (6 deploy + 5 SOUL + 6 rollback + 2 MM+TW + 10 integration), full suite 1602 passed / 14 skipped / 0 regressions from sub-03 baseline of 1586. `mypy --strict` clean on every sub-04-touched file (`task_store.py`, `setup_workspace.py`, all 5 new test files); pre-existing `task_tools.py` / `dashboard_api.py` / `state_detection.py` errors are sub-02/earlier LOWs, not sub-04 regressions. Scope discipline intact: no edits to `taskwarrior_store.py`, `task_store_factory.py`, `syncall_*.py`. Phase-2 constraint (2026-04-16 clean-run baseline with both flags off) is byte-identically preserved.
- Status: DONE
- Task: 16/sub-04
- Files: workspace/TASKWARRIOR.md, workspace/SOUL.md, task_store.py, setup_workspace.py, tests/test_task16_integration.py, tests/test_taskwarrior_md_deploy.py, tests/test_soul_task_ledger_section.py, tests/test_task_store_rollback.py, tests/test_magicmirror_hook_taskwarrior.py, _build/tasks/16-taskwarrior-syncall/task-verify.md
- Depends on: [taskwarrior-store-backend], [task-store-factory-and-migration], [syncall-gcal-daemon], [magicmirror-hook-integration-and-docs], [task-crud-complete], [dashboard-data-api]
- Issues: (1) LOW: `tests/test_task_store_rollback.py:55-56` — test method `test_syncall_defaults_off` actually asserts `is_taskwarrior_enabled({}) is False`; name misleads, assertion is correct. Rename to `test_taskwarrior_defaults_off`. (2) LOW: `workspace/SOUL.md:279` placement is between `## Fire Tablet Display` and `## Calendar`; description text says "between Calendar and Fire Tablet Display" but live file ordering is FTD→Calendar. Impl decision is correct (non-regressing); description wording is wrong, not sub-04. (3) LOW: `tests/test_task16_integration.py:54-65` — `tw_env` fixture both returns a dict and monkeypatches env; the returned dict is redundant for fixtures consuming it only indirectly. (4) LOW: impl report's line-count table is slightly stale (claims 247 lines for integration test vs actual 290; 11 tests vs actual 10). Cosmetic. All under caps.
- Detail: _build/tasks/16-taskwarrior-syncall/sub-04/16-04x.md

### [pulse-engine-core]
> TEMM1E Pulse async timer engine + Schedule data model ported verbatim from `references/temm1e/crates/temm1e-perpetuum/src/pulse.rs` + `types.rs` into pure Python. Produces `pulse_schedule.py` (159 lines: Pydantic-discriminated `Schedule` union over `ScheduleAt` / `ScheduleEvery` / `ScheduleCron`, internally-tagged `kind` field; `PulseEvent(kind="concern_due", concern_id)`; pure functions `next_fire_time(schedule, tz)` and `next_fire_after(schedule, after, tz)` with `croniter` for 5-field cron parsing and `zoneinfo.ZoneInfo` for DST-aware wall-clock → UTC conversion; naive-datetime guard on `next_fire_after.after`; invalid cron → `None`) and `pulse_engine.py` (182 lines: `Pulse.create(store, cancel) → (Pulse, Queue[PulseEvent])` classmethod mirroring Rust's `Pulse::new` tuple return; `run()` loop races three tasks via `asyncio.wait(FIRST_COMPLETED)` over `cancel.wait()` / `_sleep_until_next()` / `_schedule_changed.wait()`, cancels losers, re-raises non-CancelledError task exceptions; `_query_next_fire_time` wraps `store.next_fire_time()` in `asyncio.wait_for(timeout=STORE_QUERY_TIMEOUT_S=10.0)` and returns None on timeout; `_fire_due_concerns` logs-and-continues on `claim_due_concerns` exceptions; `IDLE_POLL_SECONDS=60.0` when no concerns scheduled; `CHANNEL_MAX_SIZE=64`; `schedule_notifier() → asyncio.Event` stable identity). `PulseStoreProtocol` (structural, not `@runtime_checkable`) is the sole contract for sub-02 — two awaitable methods `next_fire_time() → datetime | None` and `claim_due_concerns(now) → list[ConcernId]`. 29 new tests (20 pure + 9 async using `asyncio.run`/`wait_for` not pytest-asyncio, with `FakePulseStore` / `RaisingStore` conforming structurally): ports all three Rust `mod tests` cases, adds DST spring-forward (2026-03-08 02:00 PST → 03:00 PDT via `next_fire_after(ScheduleCron("0 2 * * *"), 01:30 PST, LA)` asserting `10:00 UTC`), JSON round-trip per variant, frozen-instance enforcement, `every_seconds > 0` validation, async cancel-before-run (< 1s), cancel-mid-run, idle-poll cadence (monkeypatched `IDLE_POLL_SECONDS=0.02`), due-concern emission, schedule-change wake (verifies re-query without fire), store-timeout survival, store-exception swallow for `claim_due_concerns`, notifier identity stability, queue-maxsize. `requirements.txt` pins `croniter==6.2.2` (was transitive). Full suite 1631 passed / 14 skipped (baseline + 29 new, zero regressions); `mypy --strict` clean on all 4 files. Deviations from Rust documented in impl §4 (D1 JSON internally-tagged vs externally-tagged serde; D2 `cron5_to_cron7` omitted — croniter accepts 5-field natively; D3 `_query_next_fire_time` extracted for readability; D4 no channel-close detection — `asyncio.Queue.shutdown` needs 3.13, project is 3.12; D5 generic `Exception` in `_fire_due_concerns` swallow — narrow type comes from sub-02's store adapter; D6 `Pulse.create` classmethod replaces Rust's tuple-returning `new`; D7 explicit `ValueError` on naive `after` datetime). Engine is **inert** — importable but no caller outside `tests/`; `checkin_schedule.py` / `schedule_engine.py` / `scheduling_hook.py` / `custom_gateway.py` / `hook_factory.py` byte-identical to pre-subtask. Feeds sub-02 (Pulse store adapter conforming to `PulseStoreProtocol`) and sub-03 (hook/gateway cutover).
- Status: DONE-WITH-ISSUES
- Task: 17/sub-01
- Files: pulse_schedule.py, pulse_engine.py, tests/test_pulse_schedule.py, tests/test_pulse_engine.py, requirements.txt
- Depends on: [scheduling-complete]
- Issues: (1) MEDIUM: `pulse_engine.py:123-135` `_query_next_fire_time` catches only `asyncio.TimeoutError`; Rust `pulse.rs:70-73` uses `.unwrap_or(Ok(None)).unwrap_or(None)` which swallows store-side `Result::Err` as well. If sub-02's store raises a non-timeout exception from `next_fire_time()`, it propagates through `_sleep_until_next` → `_reraise_task_errors` → kills `Pulse.run`. Rust equivalent logs-and-continues. Not documented as deviation D8. Fix: broaden except or add deviation note. (2) MEDIUM: `pulse_schedule.py:40-46, 113-114` `ScheduleAt.at_utc` accepts naive `datetime` silently; `next_fire_time` then hits `TypeError: can't compare offset-naive and offset-aware datetimes` at call time. Asymmetric with `next_fire_after`'s explicit naive-guard (line 135-139). Fix: add Pydantic field-validator rejecting naive `at_utc`. (3) LOW: `ScheduleEvery.every_seconds = Field(gt=0)` tightens Rust's `Duration::from_secs(0)` legality; sensible but undocumented deviation. (4) LOW: `_cron_next_strictly_after` catches only `(CroniterBadCronError, ValueError)` — other croniter exception types (e.g. `CroniterNotAlphaError`) would escape instead of returning None.
- Detail: _build/tasks/17-temm1e-pulse-dream/sub-01/17-01x.md
