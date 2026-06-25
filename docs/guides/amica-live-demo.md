# Amica as a Live-Demo AI Avatar

Run a 3D VRM avatar (Amica) during a presentation, powered by Claude Code Max —
no API key, no separate billing. The audience talks to the avatar; Claude processes
it and responds through TTS animation in real time.

First used: **XKE Session 15 — "Write Your Next Blog" (Xebia, June 2026)**.

---

## Architecture

```
Audience voice → Amica UI (localhost:3001)
                    │  OpenAI-format POST /v1/chat/completions
                    ▼
            amica-bridge.py (localhost:8101)
                    │  drops Amica's built-in character prompt
                    │  injects your session system prompt
                    │  spawns subprocess:
                    │      claude --dangerously-skip-permissions
                    │             --model claude-sonnet-4-6
                    │             --allowedTools Read,Write,Edit
                    │             -p "<prompt>"
                    ▼
            Claude Code Max (local auth, no API key)
                    │  can Read/Write/Edit files (e.g. live blog draft)
                    ▼
            response text → Amica TTS → avatar lip-sync + emotion animation
```

**Key insight:** Amica's `system` role message (its built-in character) is silently
dropped by the bridge. The bridge's own `_SYSTEM` env var is the only system
instruction Claude sees.

---

## Prerequisites

| What | Where |
|---|---|
| Claude Code Max plan (logged in) | `claude --version` must work |
| Amica repo checked out | this repo |
| `uv` (Python runner) | `uv --version` |
| `code-server` (optional, for live file panel) | `brew install code-server` |
| `jq` (for settings merge in start-demo.sh) | `brew install jq` |

---

## Quick start (Session 15 defaults)

```bash
bash scripts/start-demo.sh
```

Opens:
- Amica avatar → http://localhost:3001
- Bridge health → http://localhost:8101/health
- code-server (VS Code) → http://localhost:3002
- Draft file: `~/Desktop/github/xebia-blog/posts/blog-draft.md`

Stop everything: `Ctrl+C` (cleanup trap kills all processes).

---

## Adapting to a new session

**Three things to change, nothing else:**

### 1. System prompt (`_SYSTEM` in `amica-bridge.py`)
Replace the writing-coach instructions with your session's persona and flow.
Rules that should carry over to every session:
- 1–2 sentence speech limit (TTS reads everything; longer = bad live UX)
- Silent tool use (`Write`/`Edit` run without narration)
- Start engaged (no "how can I help you today?")

Override at runtime without editing code:
```bash
export AMICA_SYSTEM_PROMPT="You are ... [your session persona]"
bash scripts/start-demo.sh
```

### 2. VRM file
Swap the avatar model in Amica's settings UI → Character → VRM file.
The blue-braid-glasses model used for Session 15 is in `public/vrm/`.

### 3. Working folder in `start-demo.sh`
Change the `code-server` path and the `NEXT_PUBLIC_OPENAI_URL` env if you need
a different file as the live "live panel" in the slide.

---

## Amica UI configuration

After `start-demo.sh`, open http://localhost:3001 → ⚙️ Settings:

| Section | Key setting |
|---|---|
| AI backend | OpenAI-compatible, URL: `http://localhost:8101`, model: `claude-local`, key: `local-bridge` |
| TTS | SpeechT5 (bundled, no account needed) — or ElevenLabs/OpenAI TTS for better voice |
| Character / System Prompt | Paste the session system prompt (see below) |

### Session 15 system prompt for Amica UI

The bridge ignores this (it drops the `system` role), but having the correct prompt
in the UI is good practice and acts as a fallback reference:

```
You are Claudia, an AI writing coach at a live demo (XKE Session 15, Xebia, June 2026).
Your job is to help colleagues write their first blog post — or finally finish the one
they've been putting off.

CRITICAL RULES:
1. Every spoken reply is 1-2 sentences MAXIMUM. TTS reads everything aloud.
2. When you write or edit a draft, do it silently. Never narrate tool use.
   Just say "Draft is in VS Code." and move on.
3. After any draft, ask ONE coaching question from this list:
   - "What real example from your work proves this point?"
   - "When did this go badly — give me the war story."
   - "What opinion here would you defend under pressure?"
   - "Who is the one person you're writing this for?"
   - "What would you cut if you had to ship it tonight?"

EMOTION TAGS — one per reply, drives facial animation:
[serious] coaching questions / challenges
[happy]   good example or concrete story
[surprised] unexpected angle worth exploring
[neutral]  confirmations / transitions
[victory]  angle clicks or draft is ready
[shy]      asking for something personal
[relaxed]  slowing pace after something intense

Start engaged. You already know we're live.
```

---

## Priming message (say this in Amica before the session starts)

> "We're about to go live in front of a room of engineers. We're running XKE Session 15
> on writing with an AI coach. The audience will share topics and examples; your job is to
> sharpen their angle, draft the post from their words, and keep every response short
> enough for TTS. Ready?"

---

## Model and token controls

| Env var | Default | Purpose |
|---|---|---|
| `AMICA_MODEL` | `claude-sonnet-4-6` | Model for every subprocess call |
| `AMICA_TIMEOUT` | `120` | Seconds before a stuck call is killed |
| `AMICA_ALLOWED_TOOLS` | `Read,Write,Edit` | No Bash, no WebFetch — prevents shell exec and egress via voice |
| `AMICA_SYSTEM_PROMPT` | (writing coach) | Override without editing code |

Use Sonnet for demos. Opus burns tokens; each turn is a cold `claude -p` subprocess.

---

## Latency note

Each turn cold-starts a `claude` subprocess (~3–5 s overhead). In live demos this
reads as "thinking" — which is realistic for a writing coach. Frame it that way if
someone in the audience comments on the pause.

---

## Slide integration (Slidev)

Embed Amica and a live file panel side-by-side with 50% CSS zoom
(cross-origin iframes can't be zoomed any other way):

```html
<div style="display:grid; grid-template-columns:1fr 1fr; gap:0.75rem; height:calc(100vh - 7rem)">
  <!-- Amica avatar -->
  <div style="position:relative; overflow:hidden; border-radius:0.75rem; width:100%; height:100%;">
    <iframe
      src="http://localhost:3001"
      allow="microphone; camera; autoplay"
      style="position:absolute; top:0; left:0; width:200%; height:200%;
             transform:scale(0.5); transform-origin:top left; border:0;"
    ></iframe>
  </div>
  <!-- Live VS Code panel -->
  <div style="position:relative; overflow:hidden; border-radius:0.75rem; width:100%; height:100%;">
    <iframe
      src="http://localhost:3002/?folder=/path/to/repo&openFile=posts/blog-draft.md"
      style="position:absolute; top:0; left:0; width:200%; height:200%;
             transform:scale(0.5); transform-origin:top left; border:0;"
    ></iframe>
  </div>
</div>
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Avatar replies in a sassy/feisty character | Bridge is using old code; restart: `kill $(lsof -ti :8101) 2>/dev/null; uv run scripts/amica-bridge.py &` |
| "claude CLI not found" in chat | `which claude` must return a path; re-login to Claude Code |
| No TTS / silent avatar | Check Amica settings → TTS backend; SpeechT5 needs the speaker embedding URL set |
| Bridge 500 errors | Check `AMICA_ALLOWED_TOOLS` — tool names are comma-separated, no spaces |
| Microphone blocked in iframe | `allow="microphone; camera; autoplay"` must be on the iframe element |
| Slow responses in demo | Normal — cold subprocess start. Frame it as "thinking." |
