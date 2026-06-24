# /// script
# requires-python = ">=3.11"
# dependencies = ["fastapi>=0.115", "uvicorn>=0.32"]
# ///
"""Thin bridge: Amica → claude CLI subprocess (ADR-009).

No API key needed. Uses local Claude Code Max plan auth.
Each turn spawns: claude --dangerously-skip-permissions -p "<prompt>"

Usage:
    uv run scripts/amica-bridge.py

Amica .env.local / start-demo.sh overrides:
    NEXT_PUBLIC_CHATBOT_BACKEND=chatgpt
    NEXT_PUBLIC_OPENAI_URL=http://localhost:8101
    NEXT_PUBLIC_OPENAI_MODEL=claude-local
    NEXT_PUBLIC_OPENAI_APIKEY=local-bridge  (any non-empty string)
"""

import asyncio
import json
import os
import time
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

app = FastAPI(title="Amica Bridge", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

_CLAUDE_CMD = os.environ.get("CLAUDE_CMD", "claude")
_CLAUDE_MODEL = os.environ.get("AMICA_MODEL", "claude-sonnet-4-6")
_TIMEOUT = int(os.environ.get("AMICA_TIMEOUT", "120"))
_PORT = int(os.environ.get("AMICA_BRIDGE_PORT", "8101"))
_HOST = os.environ.get("AMICA_BRIDGE_HOST", "127.0.0.1")
# Restrict tool surface: writing tasks need Read/Write/Edit/WebFetch.
# Bash and Computer excluded — no shell execution via voice input.
_ALLOWED_TOOLS = os.environ.get("AMICA_ALLOWED_TOOLS", "Read,Write,Edit")

# System prompt injected before every conversation
_SYSTEM = os.environ.get(
    "AMICA_SYSTEM_PROMPT",
    "You are Claudia (Claude IA) — the writing coach avatar at XKE Session 15 "
    "'Write Your Next Blog' (Xebia, June 2026). "
    "You embody the /writing-coach skill from xebia-ai-power. "
    "Your blog project lives at ~/Desktop/github/xebia-blog/posts/. "
    "\n\n"
    "## TWO CHANNELS — this is critical\n"
    "You have two channels and they MUST stay separate:\n"
    "1. THOUGHTS (silent): tool calls — Write, Edit, Read. "
    "These run silently. The audience sees the result in VS Code. You never narrate them.\n"
    "2. SPEECH (audible): your text reply — the ONLY thing TTS reads aloud. "
    "1-2 sentences MAX. Always. No markdown, no bullets, no hedging, no 'great question'.\n"
    "\n\n"
    "## OPENING — say this every session start\n"
    "On your very first reply, before anything else, announce the skill and open the interview:\n"
    "  Speak: 'Running the writing-coach. Before we touch the page — [first interview question].'\n"
    "  Never draft on the first turn. The interview is the entry gate, every time.\n"
    "\n\n"
    "## INTERVIEW FIRST (the heart of the skill)\n"
    "Before any draft, you MUST have: (1) a sharp angle, (2) a real example from someone in the room.\n"
    "Ask ONE question at a time from this bank:\n"
    "- 'What real example from your own work proves this point?'\n"
    "- 'When did this go badly for you — give me the war story.'\n"
    "- 'What opinion in here would you defend under pressure?'\n"
    "- 'Who is the one person you are writing this for?'\n"
    "- 'What would you cut if you had to ship it tonight?'\n"
    "The writer's answers > your prose. Extract, don't generate.\n"
    "Only move to drafting once you have a concrete angle AND a real example.\n"
    "\n\n"
    "## WRITING FLOW — only after the interview\n"
    "When you have the angle and the example:\n"
    "  a) Use Write/Edit to write the draft to blog-draft.md (silent — Channel 1).\n"
    "  b) Speak ONE sentence: 'Draft is in VS Code — take a look.' (Channel 2).\n"
    "  c) Ask ONE follow-up question to sharpen it further.\n"
    "\n\n"
    "## COACH STANCE\n"
    "Finish over perfect. Embolden, don't gatekeep. "
    "Name the specific strength — never generic praise. "
    "If an idea is vague, sharpen it; don't kill it.\n"
    "\n\n"
    "Start engaged. You already know what we're doing here.",
)


def _build_prompt(messages: list[dict]) -> str:
    """Flatten conversation history into a single prompt string for claude -p."""
    parts = [f"[System: {_SYSTEM}]"]
    for msg in messages:
        role = msg.get("role", "")
        content = str(msg.get("content") or "").strip()
        if not content:
            continue
        if role == "system":
            # Ignore Amica's built-in character — bridge system prompt is authoritative
            pass
        elif role == "user":
            parts.append(f"Human: {content}")
        elif role == "assistant":
            parts.append(f"Assistant: {content}")
    return "\n\n".join(parts)


async def _claude_stream(prompt: str):
    """Spawn claude subprocess and yield OpenAI-compatible SSE chunks."""
    chunk_id = f"chatcmpl-{uuid4().hex[:8]}"
    created = int(time.time())

    def _sse(data: dict) -> bytes:
        return f"data: {json.dumps(data)}\n\n".encode()

    def _chunk(delta: dict, finish_reason=None) -> dict:
        return {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": "claude-local",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }

    yield _sse(_chunk({"role": "assistant", "content": ""}))

    # Sanitize: strip leading dashes so the value can't be flag-smuggled into claude's argv parser.
    safe_prompt = prompt.lstrip("-") or "(empty)"

    cmd = [
        _CLAUDE_CMD,
        "--dangerously-skip-permissions",
        "--model", _CLAUDE_MODEL,
        "--allowedTools", _ALLOWED_TOOLS,
        "-p", safe_prompt,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        yield _sse(_chunk({"content": "[claude CLI not found — is it in PATH?]"}, "stop"))
        yield b"data: [DONE]\n\n"
        return

    # Drain stderr concurrently — without this, a full stderr pipe buffer deadlocks
    # stdout reads (pipe-buffer deadlock). We discard stderr here; it goes to uvicorn logs.
    stderr_drain = asyncio.create_task(proc.stderr.read())
    try:
        while True:
            chunk = await asyncio.wait_for(proc.stdout.read(256), timeout=_TIMEOUT)
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            yield _sse(_chunk({"content": text}))

        await asyncio.wait_for(proc.wait(), timeout=10)
    except asyncio.TimeoutError:
        proc.kill()
        yield _sse(_chunk({"content": "\n[response timed out]"}, "stop"))
    except Exception as exc:
        yield _sse(_chunk({"content": f"\n[bridge error: {exc}]"}, "stop"))
    finally:
        stderr_drain.cancel()

    yield _sse(_chunk({}, "stop"))
    yield b"data: [DONE]\n\n"


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "amica-bridge", "backend": "claude-subprocess"}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    try:
        body = await request.json()
    except Exception:
        return Response(content='{"error":"invalid JSON"}', status_code=400, media_type="application/json")

    messages: list[dict] = body.get("messages") or []
    if not messages:
        return Response(content='{"error":"messages required"}', status_code=400, media_type="application/json")

    prompt = _build_prompt(messages)

    return StreamingResponse(
        _claude_stream(prompt),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    print(f"Amica Bridge v3.0 → http://{_HOST}:{_PORT}  (backend: claude subprocess, no API key needed)")
    uvicorn.run(app, host=_HOST, port=_PORT, log_level="info")
