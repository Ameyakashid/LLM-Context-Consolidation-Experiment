# TEMM1E Pulse + Dream State

## TL;DR

Pulse is a background async timer ported from TEMM1E that fires scheduled
check-ins and system concerns on exact wall-clock slots. Dream State is a
quiet-hours consolidation pass that reads the last 24 hours of memory,
task, and session context and writes summary `MemoryEntry` rows tagged
`metadata.source = "dream_state"`. Both ship behind feature flags and
default OFF.

- `PULSE_ENGINE_ENABLED=false` — the legacy `SchedulingHook` heartbeat
  polling path still fires all four check-ins. No Pulse task starts.
- `DREAM_STATE_ENABLED=false` — no Dream run ever fires. Nanobot's own
  Dream (which edits free-form markdown via tool calls) runs independently.

Both flags can be flipped independently; Dream requires Pulse.

## Why TEMM1E

The TEMM1E engine (`references/temm1e/crates/temm1e-perpetuum/src/`) is a
battle-tested Rust implementation of the `Pulse` + `ConscienceState::Dream`
pattern we need: a single async race loop that sleeps until the next
scheduled slot, fires all due concerns, and resumes. Porting it gives us

- **deterministic fires.** No "did the heartbeat wake up in time?"
  polling. Pulse sleeps for exactly `fire_at - now` seconds.
- **one place to add concerns.** New concern types (future: buffer
  alerts, bedtime nudges) plug into the same store protocol that the
  check-ins and Dream share.
- **clean shutdown.** A single `asyncio.Event` cancels the loop and the
  consumer in lockstep; the 5 s drain budget guarantees no hung tasks.

Dream State is where the neuroaffirming story pays off. Overnight the
engine reads the day's activity and writes `commitment` / `deadline` /
`blocker` / `energy_state` / `context_switch` rows so the morning
check-in lands with yesterday's context already in the system prompt —
the LLM does not have to reconstruct it turn by turn.

## Feature flags

Both flags use the project's canonical truthy convention: the literal
string `"true"` enables the feature (case-insensitive, whitespace
stripped). `"1"`, `"yes"`, and `"on"` all resolve to **disabled**.

| Var                   | Default | Enables                                 |
|-----------------------|---------|-----------------------------------------|
| `PULSE_ENGINE_ENABLED`| `false` | Pulse timer + Pulse-mode check-in path. |
| `DREAM_STATE_ENABLED` | `false` | DreamEngine on `DREAM_STATE_CRON`.      |
| `DREAM_STATE_CRON`    | `0 3 * * *` | 5-field cron, evaluated in `NANOBOT_TIMEZONE`. |

**Dream requires Pulse.** If `DREAM_STATE_ENABLED=true` but
`PULSE_ENGINE_ENABLED` is not `"true"`, the gateway logs a WARN and
Dream is disabled. The bot still boots and check-ins still fire on the
legacy path.

## Rollback

Flip either flag and restart. No data is discarded; the
`CheckInScheduleStore` and `MemoryEntryStore` are unchanged by the
flag state.

```bash
# Minimal rollback — both features off
printf 'PULSE_ENGINE_ENABLED=false\nDREAM_STATE_ENABLED=false\n' >> .env
python start.py
```

Confirm the rollback by watching the logs for `pulse.stop
reason=cancelled` on the previous run and the absence of `pulse.start`
on the next boot. If the previous run never set the flag, neither line
is expected — absence of `pulse.start` alone is the confirmation.

## Dream State explained

A single Dream run is a three-step pure pipeline:

1. **Gather.** `dream_helpers.gather_consolidation_context` reads the
   memory store (active + recently resolved), the task store
   (updated_at within the window), a session-log JSONL file, and the
   current `energy_state`. Output is a `DreamInputBundle` — no writes.
2. **Consolidate.** `DreamEngine.run()` builds a prompt from
   `workspace/templates/DREAM.md`, calls the LLM once with
   `max_tokens=800`, and parses the JSON response into validated
   `CandidateInsight` rows. Cost is bounded: ≤$0.01 per run, ≤$0.30 per
   month at the default daily cadence.
3. **Apply.** Each new insight is written via
   `MemoryEntryStore.create_entry` with metadata
   `{"source": "dream_state", "run_at": "<iso>", "supersedes": "..."}`.
   Dedup is `(category, content)` across active entries — a duplicate
   insight is dropped, not rewritten.

Reading Dream-authored memories: `MemoryContextHook.before_iteration`
injects all active memories (including Dream's) under `## Active
Memories` in the system prompt on every agent tick. You do not need to
call a tool to surface them; the LLM sees them inline.

The prompt template, the five allowed categories, and the cost math are
all surfaced in `workspace/templates/DREAM.md` — edit the template on
disk to tune tone or emphasis without touching code.

## Divergence warning

**Do not flip-flop flags. Pulse↔legacy divergence is not tested. Pick a
mode and stay.** The two code paths are byte-identical for the fire
event itself, but the `last_run_date` bookkeeping diverges the moment
one path fires and the other does not. Flipping back means the other
path sees a stale "already fired today" record and skips the next
concern until midnight. Pick a backend and stay there.

## Troubleshooting

**Pulse doesn't start.** Check for the `pulse.start` INFO line at boot.
If absent, the flag isn't `"true"` — check whitespace and case. If
`pulse.start` is present but no check-ins fire, look for
`pulse.dispatch` INFO lines on the slot times.

**Flag-mismatch log.** `DREAM_STATE_ENABLED=true` with Pulse OFF logs:

> `DREAM_STATE_ENABLED=true but PULSE_ENGINE_ENABLED is not true; Dream requires Pulse. Dream disabled.`

Set `PULSE_ENGINE_ENABLED=true` and restart.

**Dream keeps skipping.** Check `workspace/data/dream_last_run.json`.
If the `last_run_utc` timestamp is inside the 12-hour skip window,
Dream refuses to re-fire on startup. Delete the file to reset:

```bash
rm workspace/data/dream_last_run.json
```

The next boot will treat Dream as "never ran" and fire on the next
cron slot (or immediately, if a slot has already passed).

**Force a one-shot Dream run.** There is no CLI shortcut today — the
engine is only driven by Pulse. To trigger a run out-of-band, set the
cron to a slot a minute out, reset `dream_last_run.json`, and wait.

**nanobot's own Dream still runs.** That is expected. Nanobot's Dream
edits free-form markdown files (MEMORY.md, SOUL.md, USER.md); ours
writes structured `MemoryEntry` rows. They operate on different
surfaces and do not interfere. Both share the same LLM provider —
monthly spend is additive.
