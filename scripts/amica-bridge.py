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
_TIMEOUT = int(os.environ.get("AMICA_TIMEOUT", "120"))
_PORT = int(os.environ.get("AMICA_BRIDGE_PORT", "8101"))
_HOST = os.environ.get("AMICA_BRIDGE_HOST", "127.0.0.1")
# Restrict tool surface: writing tasks need Read/Write/Edit/WebFetch.
# Bash and Computer excluded — no shell execution via voice input.
_ALLOWED_TOOLS = os.environ.get("AMICA_ALLOWED_TOOLS", "Read,Write,Edit,WebFetch")

# System prompt injected before every conversation
_SYSTEM = os.environ.get(
    "AMICA_SYSTEM_PROMPT",
    "You are Claude — the AI behind this avatar — live at XKE Session 15 'Write Your Next Blog' "
    "(Xebia, June 2026). Ricardo is demoing a voice-driven writing coach to Xebia engineers. "
    "Your job: help anyone in the room get their blog idea unstuck. "
    "When someone shares an idea, sharpen the angle, challenge the framing, or draft an opening. "
    "Be direct and curious — no hedging, no 'great question!', no bullet symbols in speech. "
    "Spoken replies: under 40 words, natural sentences. "
    "If asked to write something long, write it fully then give a one-sentence spoken summary. "
    "Start engaged — you already know what we're doing here.",
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
            # Merge: bridge context first, then avatar's character instructions
            parts[0] = f"[System: {_SYSTEM}\n\nCharacter: {content}]"
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
