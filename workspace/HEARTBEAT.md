# Heartbeat

Checked every 30 minutes. The scheduling engine evaluates which check-ins are due and applies state-aware decisions before delivery.

## Morning Motivation

- Time: 08:00
- Purpose: Emotional warm-up — Volition quote, ICNU framing
- Does not reference tasks

## Morning Plan

- Time: 09:00
- Purpose: Identify the day's top priority
- Shows top 1-3 pending tasks and nearest deadline

## Afternoon Check

- Time: 14:00
- Purpose: Mid-day energy and progress check
- Shows in-progress tasks and energy context

## Evening Review

- Time: 20:00
- Purpose: Celebrate completions, flag overdue, offer closure
- Shows completed and overdue tasks

## Morning Check-Ins See Today's Calendar

- Purpose: Inject today's events under `### Today's Calendar` in the system prompt during morning check-ins
- Fires only for `morning_motivation` and `morning_plan`; other check-ins skip the injection
- Controlled by the `GOOGLE_CALENDAR_ENABLED` env var — when disabled the hook does not run at all
- Fetches the next 14 hours from the primary calendar, cached 60s so tool calls and the injection share one result
- Cognitive state gates the injection: Baseline, Focus, Avoidance, and RSD permit it; Hyperfocus and Overwhelm skip it to avoid extra load
- When Google authorization has expired the hook injects a `[Calendar unavailable ...]` marker instead of events; see SOUL.md "When Calendar Is Unavailable" for tone
- Refer to CALENDAR.md for setup and re-authorization steps

## Buffer Monitoring

- Purpose: Auto-decrement buffers on due dates, surface low-level alerts
- Fires alongside check-ins during heartbeat cycles
- Does not send a separate message — injects alerts into the active system prompt
- Alerts appear when buffer_level is at or below alert_threshold
- Buffers at level 0 are flagged but not decremented further
- Refer to SOUL.md Buffer System section for tone and framing guidance

## Voice Output

- Purpose: Auto-voice check-ins and buffer alerts during heartbeat sessions
- Controlled by `VOICE_AUTO_ENABLED` env var (set to `true` to enable)
- When enabled, the voice hook injects a `## Voice Delivery` block into the system prompt
- The LLM then uses the speak tool to deliver the indicated items as voice messages
- Cognitive state gates voice: only Baseline and Avoidance allow auto-voiced check-ins; only Baseline allows auto-voiced buffer alerts
- Focus, Hyperfocus, Overwhelm, and RSD suppress all auto-voicing
- Users can always request voice explicitly regardless of auto-voice state
- Refer to SOUL.md Voice Output section for tone and rules

## Voice-Originated Inputs

- Purpose: document how Whisper transcripts feed the heartbeat pipeline so state, memory, and scheduling hooks treat spoken input identically to typed input
- Voice messages can arrive at any time, including during a scheduled check-in window
- The channel layer wraps each transcript as `[transcription: ...]` before hooks run, so state detection, memory injection, and scheduling see it as plain user text
- A `(low confidence) ` prefix inside the wrapper means Whisper was unsure about the words; SOUL.md "Voice Input" governs how the bot should respond
- `VOICE_AUTO_ENABLED` (Task 07) governs whether the bot SPEAKS its reply and is orthogonal to voice INPUT — a session may transcribe spoken input and still answer in text-only when auto-voice is off
- Refer to SOUL.md "Voice Input" section for the full turn-by-turn handling rules
