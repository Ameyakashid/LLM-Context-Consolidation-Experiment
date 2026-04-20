# Voice Input Runbook

Voice messages from Telegram are transcribed by Whisper and arrive at
the LLM as `[transcription: ...]` text — the assistant treats them like
any other typed message. This runbook covers turning the feature on,
choosing a backend, and recovering when transcription is wrong, silent,
or too long.

## TL;DR

- Set `VOICE_INPUT_ENABLED=true` in `.env` and pick `TRANSCRIPTION_BACKEND=local|openai|groq`.
- Open Telegram, tap and hold the mic button, release to send.
- The bot replies in normal text within ~1–5 s depending on backend.
- `(low confidence) ` inside the transcript means Whisper was unsure — the bot will read it back to you instead of acting blind.
- Recordings over `MAX_VOICE_DURATION_SECONDS` (default 180 s) are rejected before transcription.

## How It Works

The Telegram channel downloads the voice file to a temp path, calls
`channel.transcribe_audio(path)` (patched at gateway startup by
[`voice_input_integration.setup_voice_input`](../voice_input_integration.py)),
the patched method routes the file through the selected
`TranscriptionBackend` from
[`transcription_backend.py`](../transcription_backend.py), and the
returned text is wrapped by nanobot as `[transcription: <text>]` before
the hook chain runs. Memory injection, state detection, and scheduling
react to the transcript exactly like typed text. The pipeline never
mutates the audio file or stores it after transcription.

## Backends

| `TRANSCRIPTION_BACKEND` | Required env | Cost / minute | Privacy posture | Latency (Mac Air M2) |
|-------------------------|--------------|---------------|-----------------|---------------------|
| `local` | none — `faster-whisper` runs offline | $0 | Audio never leaves the device. | `tiny` model ≈ 0.5× realtime; `base` ≈ realtime. |
| `openai` | `OPENAI_API_KEY` | ~$0.006 | Audio transits api.openai.com; OpenAI documents 30-day retention unless the account opts out (see <https://platform.openai.com/docs/models/whisper>). | 2–5 s per clip. |
| `groq` | `GROQ_API_KEY` | free tier | Audio transits api.groq.com; Groq documents "we do not retain audio submitted to our APIs" (see <https://groq.com/privacy-policy/>). | <1 s per clip ("instant"). |

The local backend is the default. Vendor-policy quotes were retrieved
2026-04-20 — confirm against the linked pages if you are about to ship a
privacy-sensitive deployment.

## Switching Backends

1. Edit `.env` and set `TRANSCRIPTION_BACKEND=<local|openai|groq>`.
2. If switching to a hosted backend, add `OPENAI_API_KEY=...` or
   `GROQ_API_KEY=...` to the same `.env`.
3. Restart the bot. On Mac:
   `launchctl kickstart -k gui/$(id -u)/com.adhdassistant.bot`. On
   Windows dev: stop and restart `python start.py`.
4. Send one voice clip from Telegram. Check
   `~/Library/Logs/adhd-assistant/bot.out.log` (Mac) or the dev console
   (Windows) for `voice_input.ready backend=<name>` on startup.
5. If you see `voice_input.backend_error`, the API key is missing or
   wrong, or the host cannot be reached — see "When It's Silent" below.

## When Transcription Is Wrong

- The `(low confidence) ` prefix INSIDE the transcript (e.g.
  `[transcription: (low confidence) pick up the kids at four]`) is the
  bot's signal to read the text back to you before acting. Confirm or
  correct in your next message.
- Re-send the clip with less background noise or speak slightly slower.
  Whisper handles accents well; it handles overlapping speech poorly.
- Fall back to typing if the same phrase keeps mis-transcribing.
- If a specific phrase fails repeatedly, mention it to the bot — it
  cannot improve the model, but it can record the pattern in memory so
  you have a record when reviewing logs.

## When It's Silent

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Voice messages arrive as `[voice: /path/...]`, not `[transcription: ...]` | `VOICE_INPUT_ENABLED` is unset or not `true` | Set `VOICE_INPUT_ENABLED=true` in `.env`, restart. |
| First voice clip after restart hangs ~30 s, then succeeds | `local` backend downloading the `tiny` faster-whisper model on first use | Wait it out once. Subsequent clips are fast — the model is cached under `~/.cache/huggingface/`. |
| `[transcription: failed to process voice message]` appears every time | API key missing, wrong, or quota exhausted | Check `OPENAI_API_KEY` / `GROQ_API_KEY` in `.env`. The log line `voice_input.backend_error` lists the underlying exception. |
| `[transcription: voice too long — limit 180s]` | Clip exceeded `MAX_VOICE_DURATION_SECONDS` | Send a shorter clip, or raise the cap in `.env` (it is a guardrail against runaway transcription cost, not a hard limit). |
| Voice messages produce no bot reply at all | Telegram channel itself is offline | Check `nanobot.channels.manager` log lines; this is unrelated to voice — fix the channel first. |

## Privacy

- `local` keeps audio on the device. Files are deleted when the gateway
  closes the temp handle (nanobot's behaviour, not ours). Nothing leaves
  the Mac.
- `openai` uploads the audio to `api.openai.com`. OpenAI's documented
  retention is 30 days unless the account has opted out via their data
  controls.
- `groq` uploads to `api.groq.com`. Groq's documented policy is no
  retention of API audio.
- Transcribed text is treated like any other text: it flows into
  memory_store, into the dashboard, into Pulse / Dream summaries. If you
  do not want a sentence remembered, prefix it with the same phrasing
  you would for typed text (the assistant honours `do not save this`
  instructions identically across modalities).

## Cost

This feature ties into the project's `$7/month` ceiling documented in
[`MAC_DEPLOYMENT.md`](MAC_DEPLOYMENT.md):

| Backend | Cost per 100 voice messages (~1 min each) | Adds to monthly ceiling? |
|---------|-------------------------------------------|-------------------------|
| `local` | $0 | No. |
| `openai` | ~$0.60 | Yes — bake into the ceiling if voice usage is regular. |
| `groq` | $0 (free tier; Groq throttles, does not bill, on overflow) | No. |

`local` is the lowest-friction default and the recommended starting
point. Move to `groq` if Mac CPU latency is a problem; move to `openai`
only if you need its specific accent / vocabulary advantages.
