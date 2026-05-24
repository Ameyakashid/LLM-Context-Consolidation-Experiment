# Prior-Run Intel Request — Follow-up (Classic/Custom + N+1 scope)

> Paste this into the other place where Stagiron ran end-to-end. This is a focused follow-up to `PRIOR-RUN-INTEL-REQUEST.md` — only the bits that are load-bearing for the narrower scope the user has now confirmed:
>
> - Startup gives the user **two choices**: Classic (today's defaults unchanged) or Custom (pick a backend per phase).
> - Custom routes are **hard-coded deterministic** — each selection maps through a fixed case branch, no probabilistic logic.
> - Bug sweep is literally **N+1** — the existing "iterate tasks, run supervisor on each" loop runs one extra time. The extra supervisor's only job is to scan bug reports and make one subtask per bug.
>
> Every question below has a reason. Answer with **actual values / actual snippets / actual file contents** where possible. "Don't know" is a valid answer — guessing is not.

---

## Section 1 — What "Classic" literally is

The Classic preset is whatever worked in the prior run. I need the exact values so the Classic branch in the switcher is a byte-for-byte replay of what you already validated.

1.1. **Paste the final values** of these bash vars from the version of `run-all.sh` that ran end-to-end:
```
MODEL_MAIN_SUPERVISOR=
MODEL_TASK_SUPERVISOR=
MODEL_RESEARCH=
MODEL_IMPLEMENT=
MODEL_VERIFY=
MODEL_INDEX=
MODEL_GATE=
ULTRATHINK_MAIN_SUPERVISOR=
ULTRATHINK_IMPLEMENT=
CODEX_ENABLED=
CODEX_REVIEW_TYPE=
USAGE_LIMIT_SLEEP=
RATE_LIMIT_SLEEP=
```
And the same block from `run-subtasks.sh` if it differed.

1.2. **Any vars not listed above** that you set or tuned in either script and that affected behaviour? Paste them.

1.3. **Were any phases ever run on a model that isn't `opus` or `sonnet`?** If yes — which phase, what model, what happened.

1.4. **Did `ULTRATHINK_IMPLEMENT=true` actually move the needle** in observed output quality, vs runs with it off? Rough impression is fine; side-by-side memory is better.

1.5. **Codex adversarial review** — in the runs where `CODEX_ENABLED=true`, did it meaningfully catch things Claude's verify missed? Any concrete case?

---

## Section 2 — Custom per-phase, what actually works

Under Custom mode the user picks, per phase, from {`claude` native, `claude` via OpenRouter env vars, `gemini` CLI, `codex` CLI}. For this to be safe-by-default, I need to know which combinations have ever been field-tested and which are terra incognita.

2.1. **Per phase, which non-Claude backends have you ever pointed at it, and what was the outcome?** A table is ideal:

| Phase | Ever tried on `codex`? Outcome | Ever tried on `gemini`? Outcome | Ever tried on Claude-via-OpenRouter? Outcome |
|---|---|---|---|
| main-supervisor | | | |
| task-supervisor | | | |
| research | | | |
| implement | | | |
| verify | | | |
| index-report | | | |
| task-index | | | |
| gate-review | | | |

"Never tried" is a valid cell. That's itself useful — it tells me which custom combinations need a runtime warning.

2.2. **If any phase was tried on Gemini or Codex CLI**, were the phase's Markdown templates (research.md, implement.md, etc.) written in a Claude-specific way that confused the other model? Specifically — are there mentions of `ultrathink`, references to Claude's system prompt, Claude-specific tool-use conventions, or anything else that a non-Claude agent would misread?

2.3. **`--append-system-prompt-file` is Claude-specific.** Has anyone solved "get `rules/project-claude.md` into a Gemini-CLI call's context" or "into a Codex-CLI call's context"? If yes — how? (User-prompt preamble? CLI flag? Wrapped prompt? Paste the exact approach.)

2.4. **Claude via OpenRouter env vars** (`ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN`) — has this specific combination been run through the existing `claude -p` invocation? Any surprises:
- Tool-use compatibility?
- The existing rate-limit detection still firing correctly, or does OpenRouter emit different error text?
- The `ultrathink` prompt prefix still working?
- Specific OpenRouter model strings that worked end-to-end via the Anthropic-compatible endpoint?

2.5. **Codex CLI's thinking/reasoning-mode equivalent** — what is the exact flag or invocation pattern today? Paste the command line that turned it on.

2.6. **Gemini CLI** — does it have a thinking/reasoning mode as of the prior run's date? If yes, how is it invoked.

---

## Section 3 — Reliability machinery under non-Claude backends

The retry loop, rate-limit detection, usage-limit detection, reset-time parsing, and `.done` sentinels were all built against Claude CLI output patterns. Under Custom mode they need to stay functional for whichever backend a phase uses.

3.1. **Codex CLI error surface** — paste sample stderr/stdout from at least one Codex rate-limit or failure. What strings does Codex emit that the `detect_rate_limit` / `detect_usage_limit` regexes would match, or miss?

3.2. **Gemini CLI error surface** — same question.

3.3. **OpenRouter-routed Claude** — same question. Does OpenRouter pass through Anthropic's rate-limit JSON, or does it emit its own error format?

3.4. **Has any backend ever exited 0 with a garbage/empty response** in the prior run? If yes — the existing `mark_phase_done` logic checks for `-s` (non-empty file) but not content validity. Under Custom mode with new backends this failure mode may resurface.

---

## Section 4 — The N+1 bug-sweep mechanics

The user's framing: the existing loop iterates N task supervisors; add one more iteration whose supervisor reads bugs. I need to make sure the N+1 pattern has no hidden traps.

4.1. **`discover_tasks` ordering.** It uses `find ... | sort`. Confirm that a folder named `99-bug-sweep/` sorts after `03-whatever/` under the shell/locale the prior run used. Any locale quirks I should worry about?

4.2. **Resume behaviour with an added task.** If a user's pipeline completed tasks 01 and 02, then a `99-bug-sweep/` folder appears, then the user re-runs `run-all.sh` — does the existing resume logic (`gate-report.md.done` check) correctly skip 01 and 02 and just run 99? Or does adding a task mid-build confuse resume?

4.3. **Supervisor prompt template.** The headless supervisor in `run-all.sh` instructs the agent to "break Task ${task_num} into subtasks ... plan the SHAPE of the solution, not the solution itself." For the bug-sweep task, the supervisor's job is different — it has no "solution" to shape, it's harvesting a fixed list. Did the prior run ever use the existing supervisor template for a harvesting/mechanical task like this? If yes, did the "plan the shape" framing get in the way?

4.4. **Bug-report parseability.** For the bug-sweep supervisor to make one subtask per bug, it needs to extract a list of bugs from:
- `DONE-WITH-ISSUES` entries in `_build/index.md`
- `v.md` "Issues found" sections
- `gate-report.md` issues-grouped-by-severity sections
- `codex-review.md`

Paste **one real full example** of each of those four sources from the prior run so I can see the actual shape the supervisor will parse. Template examples won't do — I need actual output.

4.5. **Dedup signal.** When the same bug appeared in more than one of the four sources in the prior run, what did the duplicates look like? Did they share a file:line signature, a verbatim text fragment, both, neither?

4.6. **Empty-bug case.** In a run where all subtasks passed clean (no `DONE-WITH-ISSUES`, all gates GO, no Codex findings) — did that ever happen? If yes: confirm the four bug sources were truly empty. If no: what's the typical minimum number of soft bugs per full run?

---

## Section 5 — Self-host collision during the build

Task 02 (the dispatcher extension) modifies the exact code the running pipeline is using. I need to know the prior run's experience with this risk.

5.1. **Did the prior run ever modify `run-all.sh` or `run-subtasks.sh` while those scripts were running?** If yes — how was it staged? Did bash's line-by-line reading bite you?

5.2. **Has the prior run ever produced a task whose implement phase wrote new files in `templates/` that the currently-running pipeline was about to source?** Any pattern you settled on for "don't break the live run"?

---

## Section 6 — Anything that breaks the N+1 or Classic/Custom framing

Open-ended. Catch-all for things that would invalidate the user's mental model.

6.1. **Is there any phase in the pipeline that can't meaningfully be chosen per-phase** because it's not actually a single prompt? (E.g. Codex review is currently a one-off `codex review --adversarial --base main` command, not a `claude -p` call. It doesn't fit the per-phase-backend model cleanly.)

6.2. **Is there any phase whose output shape a non-Claude backend would likely corrupt** — e.g. the index entry format is strict; will a generic model reliably produce the exact block structure `### [tag]` / `> description` / `- Status: ...`?

6.3. **Is there any existing flow the user has been using that a naive Classic/Custom fork would break?** Anything operational the prior run relied on that the switcher would need to preserve that isn't obvious from the repo.

---

**Format for paste-back:** inline, section by section, concrete values and snippets. "N/A" or "not tried" are valid — just say so explicitly.
