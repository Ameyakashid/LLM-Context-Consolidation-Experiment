# ADHD Assistant — Master Plan

## Project Overview

A personal AI assistant for someone with AUDHD that runs 24/7 on a Mac Air M2, communicates via Telegram, adapts its tone and approach to the user's cognitive/emotional state, and eventually speaks with Disco Elysium-inspired personalities. Built on nanobot-ai v0.1.5. Development happens on Windows PC, deployment on Mac.

## Constraints (User-Decided)

- Incremental standalone pieces — each task produces something usable on its own
- Easiest-first build order
- Stitch existing tools, don't build from scratch
- nanobot-ai v0.1.5 (never earlier — supply chain risk)
- Manual task CRUD only — assistant does not auto-create/complete tasks
- Dynamic scheduling — adapts to user state, not rigid
- Monthly LLM budget ceiling ~$7
- Primary interface: Telegram
- Always-on host: Mac Air M2
- Secondary compute: Windows PC (GTX 1080 Ti) for local inference
- Voice output via Kokoro TTS
- Fire Tablet as always-on display

## Task Breakdown

### Task 01 — Foundation
**What:** A working nanobot-ai workspace with a bot that responds to messages via Telegram. The bot runs, connects, and replies. Nothing fancy — just proof of life.
**Depends on:** Nothing.
**Produces:** A runnable bot that downstream tasks build features on top of.

### Task 02 — Personality Core
**What:** The bot's personality definition (SOUL.md), 6-state cognitive model for tone adaptation, and neuroaffirming language patterns. The bot should feel like talking to something designed for ADHD, not a generic chatbot.
**Depends on:** Task 01 (running bot).
**Produces:** Personality configuration that all future features use for tone. State detection that scheduling and check-ins depend on.

### Task 03 — Task Management
**What:** Manual CRUD for tasks via the bot interface. The user creates, lists, updates, and completes tasks. Persistent storage survives restarts.
**Depends on:** Task 01 (bot interface).
**Produces:** A task store that scheduling, buffer system, and check-ins query.

### Task 04 — Memory
**What:** Short-term conversation buffer and long-term memory consolidation. The bot remembers context within a conversation and persists important information across restarts.
**Depends on:** Task 01 (bot infrastructure).
**Produces:** Memory system that personality, scheduling, and all future features use for context.

### Task 05 — Scheduling & Check-Ins
**What:** Dynamic scheduling that adapts to user state. Proactive check-ins (morning motivation, morning plan, afternoon check, evening review) on configurable schedules.
**Depends on:** Task 02 (state detection), Task 03 (task store), Task 04 (memory).
**Produces:** A proactive assistant that reaches out rather than just responding.

### Task 06 — Buffer System
**What:** The buffer pattern for recurring obligations. Pre-load N units, auto-decrement on due dates, refill asynchronously. Persistent structured storage for buffer states.
**Depends on:** Task 03 (task/obligation storage), Task 05 (scheduling for reminders).
**Produces:** Buffer tracking that eliminates deadline pressure for recurring obligations.

### Task 07 — Voice Output
**What:** Text-to-speech via Kokoro TTS so the bot can speak responses aloud. Triggered by the bot, played on the user's devices.
**Depends on:** Task 01 (bot infrastructure).
**Produces:** Spoken responses for check-ins and important messages.

### Task 08 — Dashboard
**What:** An always-on display on the Fire Tablet showing current state, upcoming tasks, buffer levels, and recent activity.
**Depends on:** Task 03 (tasks), Task 05 (schedule), Task 06 (buffers).
**Produces:** A passive awareness surface — the user glances at it without interacting.

## Build Order Rationale

Tasks 01-04 can be built somewhat in parallel (01 first, then 02/03/04 in any order since they all depend only on 01). Task 05 is the first integration point — it needs state detection, tasks, and memory. Tasks 06-08 extend the system with specialized features.

The order is easiest-first: getting a bot running (01) is the simplest. Personality (02) and task CRUD (03) are medium complexity. Memory (04) is moderate. Scheduling (05) is the first complex integration. Buffer (06), voice (07), and dashboard (08) are independent extensions.

---

## Phase 1.5 — Out-of-Plan Tasks (added retroactively)

After Tasks 01-08 shipped, three corrective/additive tasks were added to fix integration gaps and add the Disco voice layer. These are documented in `_build/index.md`:

- **Task 09 — Custom Gateway:** stock nanobot gateway didn't register the hooks/tools from Tasks 02-07. Custom gateway closes that gap. Without this, none of Tasks 02-07's behavior was actually live.
- **Task 10 — Bug Fixes:** test suite health pass, async test fixes, oversized test file splits.
- **Task 11 — Disco Flavor:** 4-voice Disco Elysium-inspired inner-voice commentary layer activated for emotional cognitive states.

After Task 09, the bot ran cleanly (5h log on 2026-04-16, zero tracebacks). Tasks 09-11 are gated for the headless pipeline via stub `gate-report.md` files; the canonical record of what shipped is in `_build/index.md`.

---

## Phase 2 — Integration & Mac Deployment (added 2026-04-18)

The 2026-04-17 audit (`bugs and issues with project/`) surfaced two distinct workstreams: stabilization fixes and the integration of reference repos that were promised in `PROJECT_BRIEF.md` but silently dropped during original planning. Phase 2 closes both gaps and migrates the bot from the Windows dev host to the Mac (its permanent deployment home).

### Phase 2 Constraints

In addition to the original constraints from Phase 1:

- **Lift code, don't re-implement.** All new integrations must lift actual code from the cloned repos in `references/`. Pattern-mining from research reports (which is what Task 11's Disco layer did) is no longer acceptable. The user's correction on 2026-04-18 is a hard rule.
- **Skip:** memU (replaced by Taskwarrior), ProactiveAgent (both leomariga and thunlp — scheduling covered by TEMM1E Pulse, ML reward model is overkill for this scale).
- **Build for Mac.** Mac is the deployment target. Windows is dev only. New code must be platform-neutral (`pathlib`, env vars for OS-specific paths, no `os.name == 'nt'` hardcodes for new code). Mac-only paths gated by env var, not by `sys.platform`.
- **MagicMirror² replaces the Task 08 dashboard role for the Fire Tablet.** The Task 08 web dashboard stays running as a fallback until MagicMirror is verified solid in Task 18.
- **Taskwarrior replaces the JSON task store as the canonical task ledger.** syncall handles bidirectional sync with Google Calendar.
- **The 2026-04-16 5-hour clean-run baseline must not regress.** Any task that touches existing working code (specifically Task 17, which rewrites the scheduler) must keep the old path runnable until the new one is verified.

### Phase 2 Tasks

#### Task 12 — Stabilization

**What:** Resolve the audit's bugs and gaps. Test suite collects clean, workspace deploys with all seed files (including the missing `MEMORY.md`), canonical model pinned, code-rules contradiction fixed, working-tree cruft cleared.
**Depends on:** Nothing structurally (touches code from Tasks 01-11).
**Produces:** Clean baseline for the integration tasks.

#### Task 13 — Natural Language Time Parsing

**What:** Lift NL time parsing from `references/ReminderBot` so the user can write "remind me to X tomorrow at 6pm" and have the due date parsed.
**Depends on:** Task 12.
**Produces:** NL-aware task creation. Independent of other Phase 2 tasks.

#### Task 14 — Google Calendar via MCP

**What:** Lift the MCP server from `references/google-calendar-mcp` so the bot can read the user's calendar for awareness. Read-only; writable sync is Task 16.
**Depends on:** Task 12.
**Produces:** Calendar-aware bot. Used by Task 18 verification.

#### Task 15 — MagicMirror Display

**What:** Stand up MagicMirror² for the Fire Tablet display. Lift code from `references/MagicMirror`, `references/MMM-WebHookAlerts`, `references/MMM-Markdown`, and `references/MMM-pages`. Bot pushes alerts via webhook; Fire Tablet hits MagicMirror over local wifi.
**Depends on:** Task 12.
**Produces:** Visible Fire Tablet display. Initially reads existing `task_store` JSON; data source switches to Taskwarrior in Task 16.

#### Task 16 — Taskwarrior + syncall Migration

**What:** Lift `references/tasklib` to replace the JSON `task_store.py` with Taskwarrior as the canonical task ledger. Lift `references/syncall` to bidirectionally sync Taskwarrior with Google Calendar. MagicMirror data source updates.
**Depends on:** Tasks 14, 15.
**Produces:** Canonical Taskwarrior store; bidirectional Calendar sync; MagicMirror displays Taskwarrior data.

#### Task 17 — TEMM1E Pulse + Dream State

**What:** Lift `references/temm1e`'s Pulse engine to replace the bespoke check-in scheduler. Lift Dream State for long-term memory consolidation at quiet hours.
**Depends on:** Task 12. Touches scheduling and memory layers from Tasks 04-05.
**Produces:** Robust scheduling + long-term memory consolidation. Highest implementation risk in Phase 2 (rewrites working code).

#### Task 18 — Mac Deployment & Port

**What:** Migrate the working repo from Windows to Mac. Smoke test, audio defaults, LaunchAgent, MagicMirror auto-launch, Mac-specific bug fixes. From this task onward, Mac is the canonical host.
**Depends on:** Tasks 12-17.
**Produces:** Bot running permanently on Mac. Documentation for the non-technical user.

#### Task 19 — Whisper Voice INPUT

**What:** Lift `references/adha_bot`'s Whisper voice-input pipeline. User speaks; mic captures; Whisper transcribes; bot processes as a normal message. Closes the voice loop alongside Task 07's TTS output.
**Depends on:** Task 18 (needs the mic on the Mac).
**Produces:** Two-way voice interaction.

### Phase 2 Run Strategy

Tasks 12-17 are platform-neutral and run via the headless pipeline on Windows (the current dev host). After Task 17 completes and gates with GO/CAUTION, the user physically moves the repo to the Mac and re-runs the headless pipeline; resume logic skips everything already done and picks up at Task 18. Tasks 18-19 run on Mac.
