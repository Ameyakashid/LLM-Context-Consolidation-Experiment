# Prior-Run Intel Request

> Paste this into the other place where Stagiron already ran end-to-end and did everything. Answer as many as you can. Skip anything you don't know — don't guess. The goal is to ground the upgrade work (per-run backend switcher + end-of-pipeline bug sweep) in what **actually happened**, not what the templates describe.
>
> For every answer where you have files: paste the **actual content / paths / snippets**, not a summary. If a path worked, give the path. If a JSON structure was emitted, paste the JSON. If a bug report had specific wording, quote it.

---

## Section A — Setup & paths

A1. **What was the top-level directory** for that run? Absolute path if possible. Was the repo the project (repo-as-project) or did `_build/` sit in a sibling/parent? Which of `run-all.sh`'s six `PROJECT_ROOT` fallbacks actually fired?

A2. **Did any of `SB_PROJECT_ROOT`, `SB_BUILD_DIR`, `SB_TEMPLATES_DIR`, `SB_RULES_FILE` env vars get used?** If yes, what values.

A3. **OS + shell environment** the run happened on. Windows + Git Bash? macOS + zsh? Linux? Did `uname -s` return what you expected?

A4. **Where was `_build/index.md` physically written?** Paste its final path. And — critical — did anything write to it that *wasn't* a Verify agent? (The design says only Verify appends, but I want to know if that held up in practice.)

A5. **Did `rules/project-claude.md` exist and get appended to every `claude -p` call?** Any phase skip it? Any `--append-system-prompt-file` errors in the logs?

A6. **Pre-run setup steps a human did manually** that the launcher in the upgrade should automate: cloning references, creating `_build/`, setting env vars, installing CLIs, logging into Claude/Codex/Gemini, anything else.

---

## Section B — Dispatch and switching (the big one)

B1. **Was any backend used besides `claude`?** If yes — which, how, and was it wired via `run_claude` or through some side path (like `run_codex_review`)?

B2. **If Codex ran** (`CODEX_ENABLED=true`):
- What command did it actually execute? Paste the exact line from the log.
- What did `codex-review.md` look like? Paste a full real example if possible — header, sections, severity tags, verdict format.
- Did `codex review --adversarial --base main` work cleanly, or did it error / hang / time out?
- Did the gate agent actually read it and weight it? Any evidence in `gate-report.md` that Codex's findings moved the verdict?

B3. **Did anyone try `claude -p` through OpenRouter** (or any Anthropic-compatible third-party endpoint) by setting `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN`? If yes:
- What base URL worked?
- Any request-format differences from native Anthropic (tool use, system-prompt handling, streaming, ultrathink)?
- Did rate-limit detection still fire correctly, or did the "5-hour limit" text patterns stop matching?
- Model string that worked end-to-end?

B4. **Any per-phase model tweaks** beyond the defaults in `run-all.sh` / `run-subtasks.sh`? Did anyone set RESEARCH to sonnet, or VERIFY to opus+ultrathink, etc? If yes — what mix, and did it produce better or worse output?

B5. **Ultrathink behavior**: the system prepends the literal word `ultrathink\n\n` to the prompt. Did that actually trigger deeper reasoning in practice, or did it just eat tokens? Any phase where ultrathink demonstrably changed output quality?

B6. **Environment-variable handling**: how did the run get its secrets/keys (`NTFY_TOPIC`, any API keys, login tokens)? Shell export? `.env` file? Some wrapper? Was anything brittle?

---

## Section C — Bug reports (drives the sweep design)

C1. **Final count of `DONE-WITH-ISSUES` entries in `_build/index.md`** after the run? Paste one complete real entry (the exact block).

C2. **How many v.md files flagged issues?** Of the total subtasks, roughly what fraction had CRITICAL / HIGH / MEDIUM / LOW issues?

C3. **Paste one complete real v.md** "Issues found" section — a full issue with severity, file:line, description, suggested fix. Exact structure matters because the bug-sweep has to parse it.

C4. **Paste one complete real `gate-report.md`** (or at least its issues-grouped-by-severity section and its final `VERDICT:` line). Again exact structure.

C5. **Did the same bug ever appear in multiple places** (e.g. the same issue flagged in both `v.md` and `gate-report.md`, or surfaced by both Claude verify and Codex review)? If yes — the bug-sweep needs dedup logic.

C6. **Issue severity labels actually used** — did verify agents stick to `CRITICAL/HIGH/MEDIUM/LOW`, or did they invent other ones (`blocker`, `warn`, etc)? Any issues with no severity tag?

C7. **Integration / cross-subtask bugs** that only `gate-report.md` caught (not any individual `v.md`)? How were they worded? How would the sweep detect them without a per-subtask tag?

C8. **Did any STOP verdict fire?** If yes, at which task, why, and what was the re-run workflow.

C9. **Did any bug get silently missed** and then surface at human gate (in guided mode) or later? How did you notice?

C10. **Five known field bugs** mentioned in the spec (path handling, resume logic, WSL, Git Bash PATH, 500 handling) — how did each manifest in this run? Do any of them show up as index entries or are they tracked separately? If separately — where?

---

## Section D — Pipeline behavior

D1. **Total wall-clock duration** of the run. How many tasks, how many subtasks total, how many `claude -p` calls.

D2. **Did rate limits hit?** How many times, which limit type (5-hour usage cap vs 429 throttle), how long did each pause last, did the detection + resume actually work?

D3. **Did `parse_reset_wait` extract the right timestamp?** Any case where it over-waited or under-waited (so the retry hit the same limit immediately)?

D4. **Resume: did you ever kill the run mid-phase and restart?** Did `.done` sentinels correctly skip completed phases? Any case where a partial output file got re-used when it shouldn't have?

D5. **Notifications** — did Windows toast / macOS osascript / Linux notify-send / ntfy.sh all work? Which ones.

D6. **Time distribution across phases** — roughly what percentage of the wall clock went to Research vs Implement vs Verify vs Index vs Gate? (For the preset-routing discussion even though we're not doing presets in v1.)

D7. **Token / call cost** observed. What did the `MODEL USAGE SUMMARY` at the end of `run-all.sh` actually print? (Opus calls, Sonnet calls, Codex calls.)

D8. **Any `claude -p` call that exited 0 but produced garbage / empty / partial output**, which `.done` then incorrectly marked? (Known possible failure mode — want to know if it happened.)

D9. **Supervisor output quality in headless mode** — did `run_main_supervisor` produce a plan comparable to an interactive `start.md` session, or notably worse?

---

## Section E — Interactive flow

E1. **Guided-mode gate verification** (`gate-verify-prompt.md`, the 5-phase Socratic) — did it actually extract useful GE insight, or did it feel like theatre? Any concrete example of the human catching something the automated verify missed?

E2. **Humanise flow** — did the IDE connector files actually engage the IDE into being a helpful catch-up agent, or did users go back to `claude -p` / asking plain Claude?

---

## Section F — For the switcher upgrade specifically

F1. **If you were to add a "which CLI should run each phase" switch today**, where's the minimum-invasive seam? Just `run_claude`? Both `run_claude` + `run_codex_review`? Something else surfaces?

F2. **Any phase that has implicit Claude-specific assumptions** baked into the template (mentions of ultrathink in the prompt text, references to `claude -p`, tool-use conventions)? If we point a phase at Gemini or a generic OpenRouter model, what breaks first?

F3. **`--append-system-prompt-file` equivalents** — does Gemini CLI have one? Codex CLI? If not, the non-Claude runners will need to inline `rules/project-claude.md` at the top of the user prompt. Has anyone already tried this and seen how agents behave when rules are user-prompt vs system-prompt?

F4. **Thinking-mode translation** — for Codex specifically: what is the actual reasoning/o1-mode flag or prompt prefix in the CLI today? Paste the exact invocation that worked.

F5. **Config persistence** — did the prior run have any config file the pipeline read? Any JSON/YAML/INI? If yes, where did it live and what keys.

---

## Section G — For the bug-sweep upgrade specifically

G1. **At what exact point** should the sweep trigger? After the last task's gate writes `VERDICT: GO`/`CAUTION`? After `run-all.sh`'s final summary? Before the final notification?

G2. **One subtask per bug: what counts as "one bug"?** Your answer said "bugs reported from running the pipeline" — but in the real output, is one CRITICAL entry in a v.md one bug, or is one whole v.md (even with 3 bugs inside) one bug? What granularity matches how you'd actually want to fix them?

G3. **Dedup**: if the same underlying issue was flagged in v.md and gate-report.md and codex-review.md (three places), should the sweep produce one subtask or three?

G4. **Pre-existing known-bugs** outside this run's outputs — do those get fed into the sweep via some bootstrap file, or strictly this run's findings only?

G5. **If the bug-sweep's own subtasks** produce their own bug reports (the fix introduces new issues) — does a second bug-sweep run after this one, or does it end and those get deferred to the next pipeline run?

G6. **Subtask chain for bug fixes**: the prior run used the full 4-phase R/I/V/X chain. The user's latest message said "the 3 stages like research, implement and verify" — was X (index report) skipped intentionally for bug fixes, or is it still run? If it was ever skipped anywhere, where, and did it cause problems?

---

## Section H — Anything else

H1. **Surprises**. Anything that didn't match the README / CLAUDE.md / design-decisions.md in the actual behavior?

H2. **Load-bearing hacks** in the code that the templates don't tell you about (e.g. the `</dev/null 2>&1` + `fd 3` trick in `run-all.sh` that keeps the outer while-loop from being eaten by `claude -p` reading stdin)?

H3. **Things the prior run didn't do but probably should have** — anything a future version would ideally capture (e.g. structured bug IDs, per-bug JSON, a `bugs.jsonl` log, timing per phase, etc.)?

H4. **Anything in `references/` (Ralph, Planning-with-files, Conductor) that actually got looked at** during research phases, and was it useful?

H5. **If the upgrade builds the launcher + bug-sweep on top of this run's artifacts** (i.e. the build system generating its own upgrade), any landmine you'd warn about? (E.g. a task editing `run_claude` in a file that the very same pipeline is using to call `run_claude`.)

---

**Format for paste-back:** reply inline, section by section, with exact file contents / paths / outputs where possible. If an answer is "N/A" or "didn't happen," say so explicitly rather than leaving blank.
