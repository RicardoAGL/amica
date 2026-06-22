# /// script
# requires-python = ">=3.11"
# dependencies = ["anthropic>=0.40", "fastapi>=0.115", "uvicorn>=0.32"]
# ///
"""Thin OpenAI-compatible bridge: Amica → Anthropic API.

Runs independently from AFP so AFP can stay up while this is started/stopped.

Usage:
    ~/infisical-run.sh uv run scripts/amica-bridge.py
    # or: ANTHROPIC_API_KEY=<key> uv run scripts/amica-bridge.py

Amica .env.local overrides needed:
    NEXT_PUBLIC_CHATBOT_BACKEND=chatgpt
    NEXT_PUBLIC_OPENAI_URL=http://localhost:8101
    NEXT_PUBLIC_OPENAI_MODEL=claude-haiku-4-5-20251001
    NEXT_PUBLIC_OPENAI_APIKEY=local-bridge  (any non-empty string)

Env vars:
    ANTHROPIC_API_KEY   — required; use ~/infisical-run.sh to inject it
    AMICA_BRIDGE_MODEL  — default model (default: claude-haiku-4-5-20251001)
    AMICA_BRIDGE_PORT   — listen port (default: 8101)
    AMICA_MAX_TOKENS    — max output tokens (default: 1024)
"""

import json
import os
import time
from collections.abc import AsyncIterator
from uuid import uuid4

import anthropic
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Amica Bridge", version="1.0.0")

# Only localhost origins — blocks DNS-rebinding from external pages.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

_aclient = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

_DEFAULT_MODEL = os.environ.get("AMICA_BRIDGE_MODEL", "claude-haiku-4-5-20251001")
_MAX_TOKENS = int(os.environ.get("AMICA_MAX_TOKENS", "1024"))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _split_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    """Separate system prompt from chat turns."""
    system = " ".join(m.get("content", "") for m in messages if m.get("role") == "system")
    chat = [m for m in messages if m.get("role") != "system"]
    return system, chat


async def _openai_stream(model: str, system: str, messages: list[dict]) -> AsyncIterator[bytes]:
    """Real token-by-token Anthropic stream re-encoded as OpenAI SSE."""
    chunk_id = f"chatcmpl-{uuid4().hex[:8]}"
    created = int(time.time())

    def _sse(data: dict) -> bytes:
        return f"data: {json.dumps(data)}\n\n".encode()

    def _chunk(delta: dict, finish_reason: str | None) -> dict:
        return {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }

    yield _sse(_chunk({"role": "assistant", "content": ""}, None))

    kwargs: dict = {"model": model, "max_tokens": _MAX_TOKENS, "messages": messages}
    if system:
        kwargs["system"] = system

    try:
        async with _aclient.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield _sse(_chunk({"content": text}, None))
    except Exception as exc:
        error_msg = f"[bridge error: {exc}]"
        yield _sse(_chunk({"content": error_msg}, None))

    yield _sse(_chunk({}, "stop"))
    yield b"data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "amica-bridge", "model": _DEFAULT_MODEL}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    try:
        body = await request.json()
    except Exception:
        return Response(
            content='{"error":"invalid JSON"}',
            status_code=400,
            media_type="application/json",
        )

    messages: list[dict] = body.get("messages") or []
    if not messages:
        return Response(
            content='{"error":"messages is required and must be non-empty"}',
            status_code=400,
            media_type="application/json",
        )

    # Accept any model starting with "claude-"; fall back to default otherwise.
    raw_model = str(body.get("model") or "")
    model = raw_model if raw_model.startswith("claude") else _DEFAULT_MODEL

    system, chat = _split_messages(messages)

    if body.get("stream", True):
        return StreamingResponse(
            _openai_stream(model, system, chat),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Non-streaming path (Amica rarely uses this, but handle it)
    kwargs: dict = {"model": model, "max_tokens": _MAX_TOKENS, "messages": chat}
    if system:
        kwargs["system"] = system
    msg = await _aclient.messages.create(**kwargs)
    text = msg.content[0].text if msg.content else ""
    return Response(
        content=json.dumps({
            "id": f"chatcmpl-{uuid4().hex[:8]}",
            "object": "chat.completion",
            "model": model,
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
            ],
        }),
        media_type="application/json",
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("WARNING: ANTHROPIC_API_KEY is not set — requests will fail.")
        print("Run with: ~/infisical-run.sh uv run scripts/amica-bridge.py")
    port = int(os.environ.get("AMICA_BRIDGE_PORT", "8101"))
    print(f"Amica Bridge → http://localhost:{port}  (model: {_DEFAULT_MODEL})")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
