# ADHD Management App

An AI-powered accountability partner that lives in your Telegram. It detects your cognitive state in real-time, manages tasks with ADHD-aware framing, sends proactive check-ins at the right moments, tracks recurring obligations through a buffer system, speaks to you via local TTS, and displays a live dashboard on a Fire Tablet.

Built on [nanobot-ai](https://github.com/palomachain/nanobot-ai) v0.1.5 with OpenRouter (Claude 3.5 Haiku).

---

## What It Does

### Cognitive State Detection
The bot detects 6 cognitive states from your messages and adapts its behavior in real-time:

| State | What It Means | Bot Behavior |
|-------|--------------|--------------|
| **Baseline** | Normal functioning | Standard support, offers structure when asked |
| **Focus** | Engaged in work | Concise responses, doesn't interrupt flow |
| **Hyperfocus** | Deep immersion | Silent unless critical — no tasks, no buffers, no voice |
| **Avoidance** | Stuck on initiation | ICNU motivation framework, smallest possible first step |
| **Overwhelm** | Too much at once | Simplifies to one single thing, no options or lists |
| **RSD** | Rejection sensitivity | Validates emotions first, zero task mentions |

State transitions follow clinical constraints — e.g., you can't jump from crisis (RSD/overwhelm) directly to hyperfocus.

### Task Management
Natural language task CRUD via Telegram:
- *"I need to call the dentist Thursday"* → bot creates a task with due date
- *"What do I have today?"* → shows top 5 pending tasks, sorted by priority
- *"Done with the dentist"* → marks complete with brief acknowledgment

### Proactive Check-Ins
Four daily check-ins, state-aware and suppressible:

| Check-In | Time | Purpose |
|----------|------|---------|
| Morning Motivation | 08:00 | Emotional warm-up, no tasks — just "you chose this" |
| Morning Plan | 09:00 | "What's the one thing that would make today a win?" |
| Afternoon Check | 14:00 | "How's it going?" + in-progress tasks |
| Evening Review | 20:00 | "What went well?" + completions, overdue without judgment |

Each check-in is evaluated against your current state. Hyperfocus suppresses all but evening. RSD suppresses everything except a gentle morning motivation. Overwhelm reduces scope to single items.

### Buffer System
Pre-load recurring obligations to eliminate deadline anxiety:
- *"Create a rent buffer — capacity 4, interval 30 days"*
- Auto-decrements when due dates arrive (via heartbeat)
- Low-buffer alerts surface during check-ins: *"Good time to top up rent — you have 1 left"*
- Always framed as "banked ahead" not "running out"

### Voice Output (Kokoro TTS)
Local text-to-speech via [Kokoro ONNX](https://github.com/thewh1teagle/kokoro-onnx) — no cloud dependency:
- Bot converts responses to OGG/Opus voice messages in Telegram
- Auto-voices check-ins and buffer alerts (configurable)
- State-aware: hyperfocus/overwhelm/RSD = no auto-voice
- User can always request voice: *"read that aloud"*

### Fire Tablet Dashboard
A glanceable web page served locally, optimized for Fire Tablet (1024×600):
- Color-coded cognitive state banner
- Buffer level gauges
- Active task list
- Check-in schedule with fired/upcoming status
- Recent activity feed
- Auto-refreshes every 30 seconds — no interaction needed

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Telegram (User)                       │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│              nanobot-ai Gateway                         │
│         (manages conversation, context, tools)          │
└─────────────────────┬───────────────────────────────────┘
                      │
    ┌─────────────────▼─────────────────────┐
    │          Hook Chain (per message)      │
    │                                       │
    │  1. StateResponseHook                 │
    │     → Detects cognitive state         │
    │     → Writes state.json for dashboard │
    │                                       │
    │  2. MemoryContextHook                 │
    │     → Injects active memories         │
    │                                       │
    │  3. SchedulingHook                    │
    │     → Fires due check-ins             │
    │     → State-aware fire/defer/suppress │
    │                                       │
    │  4. BufferHook                        │
    │     → Auto-decrements due buffers     │
    │     → Surfaces low-buffer alerts      │
    │                                       │
    │  5. VoiceHook                         │
    │     → Decides if response gets voiced │
    └─────────────────┬─────────────────────┘
                      │
    ┌─────────────────▼─────────────────────┐
    │            LLM Tools                  │
    │                                       │
    │  Task: create, list, update, complete │
    │  Memory: save, list, dismiss          │
    │  Buffer: create, list, refill, status │
    │  Voice: speak (send voice message)    │
    └───────────────────────────────────────┘
                      │
    ┌─────────────────▼─────────────────────┐
    │          JSON Persistence             │
    │                                       │
    │  data/tasks.json                      │
    │  data/memories.json                   │
    │  data/buffers.json                    │
    │  data/checkins.json                   │
    │  data/cognitive_state.json            │
    │                                       │
    │  All writes are atomic (.tmp + rename)│
    └───────────────────────────────────────┘

    ┌───────────────────────────────────────┐
    │       Dashboard (separate thread)     │
    │                                       │
    │  HTTP server on port 8085             │
    │  Reads JSON files, serves to browser  │
    │  Fire Tablet polls every 30s          │
    └───────────────────────────────────────┘
```

---

## Quick Start

### Prerequisites
- Python 3.10+
- An [OpenRouter](https://openrouter.ai) API key
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- Your Telegram user ID (from [@userinfobot](https://t.me/userinfobot))

### 1. Clone & Install

```bash
git clone https://github.com/Ameyakashid/ADHD-management-app.git
cd ADHD-management-app

python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows

pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` with your keys:

```env
# Required
OPENROUTER_API_KEY=sk-or-v1-your-key-here
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_USER_ID=123456789

# Optional
VOICE_AUTO_ENABLED=false
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8085
```

### 3. Setup Workspace

```bash
python setup_workspace.py
```

This creates the nanobot workspace at `~/.nanobot/`, downloads Kokoro TTS models (~300MB), and sets up the data directory.

### 4. Run

```bash
python start.py
```

This starts both the nanobot gateway (Telegram bot) and the dashboard server (HTTP on port 8085) in a single process. Open Telegram and message your bot.

### 5. Dashboard (Optional)

Open `http://<your-ip>:8085` on any browser. For Fire Tablet:
- Open Silk browser → navigate to the URL
- See `workspace/DASHBOARD.md` for kiosk mode and stay-awake settings

---

## Testing

The test suite lives in `tests/` and is configured by `pytest.ini` at the repo root. Pytest and its plugins are declared in `requirements-dev.txt`, separate from the runtime dependencies in `requirements.txt`.

### Install dev dependencies

```bash
# Activate the virtualenv first
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate         # Windows

pip install -r requirements-dev.txt
```

`requirements-dev.txt` pulls in `requirements.txt` and adds `pytest`.

### Run the suite

```bash
pytest
```

This collects only from `tests/` (scoped by `pytest.ini`), so cloned reference repos under `references/` and the virtualenv are ignored. Expect ~985 tests, all passing.

### If pytest is invoked from the wrong interpreter

The repo's root `conftest.py` verifies that `nanobot` is importable before collection begins. If you see

```
ImportError: nanobot package not importable from <path>
```

you are running pytest from a Python that does not have `nanobot-ai` installed. Either activate `.venv`, or run pytest through the virtualenv's interpreter directly:

```bash
.venv/bin/python -m pytest         # macOS/Linux
.venv/Scripts/python -m pytest     # Windows
```

---

## Project Structure

```
├── start.py                        # Entry point — starts bot + dashboard
├── setup_workspace.py              # Workspace setup + TTS model download
├── requirements.txt                # Python dependencies
├── .env.example                    # Environment variable template
│
├── state_detection.py              # 6-state cognitive model + Markov transitions
├── state_response_integration.py   # StateResponseHook — detects state per message
├── cognitive_state_writer.py       # Persists state to JSON for dashboard
│
├── task_store.py                   # Task CRUD + JSON persistence
├── task_tools.py                   # 5 LLM-callable task tools
│
├── memory_store.py                 # Structured memory entries (5 categories)
├── memory_tools.py                 # 3 LLM-callable memory tools
├── memory_context.py               # MemoryContextHook — injects active memories
│
├── checkin_schedule.py             # 4 check-in types + due-date detection
├── schedule_engine.py              # State-aware fire/defer/suppress decisions
├── scheduling_hook.py              # SchedulingHook — fires check-ins via heartbeat
│
├── buffer_store.py                 # Buffer model + decrement/refill/persist
├── buffer_tools.py                 # 5 LLM-callable buffer tools
├── buffer_hook.py                  # BufferHook — auto-decrement + alerts
│
├── tts_engine.py                   # Kokoro ONNX wrapper — text → WAV bytes
├── voice_delivery.py               # WAV → OGG/Opus conversion for Telegram
├── voice_tools.py                  # SpeakTool — LLM-callable voice output
├── voice_trigger_hook.py           # VoiceHook — auto-voice check-ins/alerts
│
├── hook_context.py                 # Shared HookContext protocol
├── dashboard_api.py                # HTTP API server for dashboard
│
├── dashboard/                      # Frontend (static HTML/CSS/JS)
│   ├── index.html
│   ├── style.css
│   └── app.js
│
├── workspace/                      # nanobot-ai workspace templates
│   ├── SOUL.md                     # Bot personality & behavior rules
│   ├── HEARTBEAT.md                # Heartbeat scheduling configuration
│   ├── DASHBOARD.md                # Fire Tablet setup instructions
│   └── memory/
│       └── MEMORY.md               # Long-term memory (Dream cycle target)
│
└── tests/                          # 250+ tests
    ├── test_state_detection.py
    ├── test_task_store.py
    ├── test_memory_store.py
    ├── test_checkin_schedule.py
    ├── test_schedule_engine.py
    ├── test_buffer_store.py
    ├── test_buffer_tools.py
    ├── test_voice_trigger.py
    ├── test_dashboard_api.py
    └── ...
```

---

## Customization

### Change the Personality
Edit `workspace/SOUL.md`. The bot's entire personality, tone, and behavioral rules are defined in this single file. The code doesn't care what's in it — it just passes SOUL.md to the LLM as system instructions.

Examples:
- Make it a sarcastic friend — change the Voice and Tone section
- Remove ADHD framing — strip the neuroaffirming rules and state adaptations
- Add roleplay elements — see the "Personality Voices" section (reserved for future use)

### Change the LLM
Edit `config.json.template` in the nanobot workspace. Change the model name to any OpenRouter-supported model:

```json
"model": "nousresearch/hermes-3-llama-3.1-405b"
```

### Adjust Check-In Times
Check-in times are defined in `checkin_schedule.py` as `DEFAULT_SCHEDULE`. Modify the `target_time` values. The staleness window (default 120 minutes) prevents old check-ins from firing on late startup.

### Add a New Buffer
Via Telegram: *"Create a buffer for gym membership — capacity 12, every 30 days, starting January 1"*

Or programmatically via the `BufferStore` API.

### Toggle Voice
Set `VOICE_AUTO_ENABLED=true` in `.env` to auto-voice check-ins and buffer alerts. No restart needed — read fresh on every invocation.

---

## How It Was Built

This project was built using the [Sequential Builder](https://github.com/Ameyakashid/Antigravity-Agent-guided) framework — an AI agent orchestration system that decomposes large projects into context-managed tasks, each executed by a fresh Claude Opus session.

8 tasks were executed sequentially, each following a Research → Implement → Verify → Index cycle with verification gates between tasks:

1. **Foundation** — nanobot-ai workspace, config templates, smoke tests
2. **Personality** — 6-state cognitive model, SOUL.md, state detection
3. **Task CRUD** — Task store, LLM tools, SOUL.md task guidance
4. **Memory** — Structured memory entries, context injection hook
5. **Scheduling** — 4 check-in types, state-aware scheduling engine
6. **Buffers** — Buffer tracking, auto-decrement, LLM tools
7. **Voice** — Kokoro TTS, Telegram voice delivery, auto-voice triggers
8. **Dashboard** — HTTP API, Fire Tablet frontend, startup integration

Total: 250+ tests, all passing. Every task passed its verification gate.

---

## Cost

Designed to run within a **$7/month** budget on OpenRouter with Claude 3.5 Haiku:
- ~$0.25/M input tokens, ~$1.25/M output tokens
- With consolidation and efficient context management, typical daily usage stays well under budget
- TTS runs locally (Kokoro ONNX) — no cloud TTS costs
- Dashboard is local HTTP — no hosting costs

---

## Platform Support

| Platform | Role | Status |
|----------|------|--------|
| **macOS (M2)** | Primary deployment — runs bot + dashboard 24/7 | Supported |
| **Windows** | Development — all tests pass | Supported |
| **Linux** | Should work — no platform-specific code | Untested |
| **Fire Tablet** | Dashboard display via Silk browser | Supported |

---

## License

MIT
