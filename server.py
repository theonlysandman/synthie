"""
server.py — Web relay for Synthie (browser voice client)
=========================================================
Serves a small web page and relays browser audio to Azure Voice Live.

The browser cannot hold an Azure credential, so this backend authenticates
(AzureCliCredential — requires `az login`) and proxies Voice Live events
between the browser WebSocket and the Voice Live realtime WebSocket.

Reuses the exact connect() parameters verified working in main.py.

Usage:
    python server.py
    # then open http://localhost:8000

Required env vars (set in .env):
    VOICELIVE_ENDPOINT
    PROJECT_NAME
    AGENT_NAME

Optional env vars:
    MODEL_DEPLOYMENT_NAME   (default: gpt-realtime-2)
    AGENT_VERSION
    VOICELIVE_API_VERSION   (default: 2026-04-10)
    PORT                    (default: 8000)
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from azure.identity import AzureCliCredential
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

import research

from azure.ai.voicelive.aio import connect
from azure.ai.voicelive.models import (
    AzureStandardVoice,
    InputAudioFormat,
    Modality,
    OutputAudioFormat,
    RequestSession,
    ServerVad,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
load_dotenv()

_REQUIRED = ["VOICELIVE_ENDPOINT", "PROJECT_NAME", "AGENT_NAME"]
_missing = [v for v in _REQUIRED if not os.environ.get(v)]
if _missing:
    sys.exit(
        "ERROR: The following required environment variables are not set:\n"
        + "\n".join(f"  - {v}" for v in _missing)
        + "\n\nFill in .env and re-run."
    )

VOICELIVE_ENDPOINT: str = os.environ["VOICELIVE_ENDPOINT"].rstrip("/") + "/"
PROJECT_NAME: str = os.environ["PROJECT_NAME"]
AGENT_NAME: str = os.environ["AGENT_NAME"]
AGENT_VERSION: Optional[str] = os.environ.get("AGENT_VERSION") or None
MODEL_DEPLOYMENT_NAME: str = os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-realtime-2")
VOICELIVE_API_VERSION: str = os.environ.get("VOICELIVE_API_VERSION", "2026-04-10")
AZURE_VOICE: str = os.environ.get("AZURE_VOICE", "en-US-AvaNeural")
PORT: int = int(os.environ.get("PORT", "8000"))

_WEB_DIR = Path(__file__).parent / "web"
_CONV_DIR = Path(__file__).parent / "conversations"
_CONV_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Synthie Web")


@app.get("/")
async def landing() -> FileResponse:
    """Entry page — ask for the customer's website, then research it."""
    return FileResponse(_WEB_DIR / "landing.html")


@app.get("/talk")
async def talk() -> FileResponse:
    """Voice page — where the user actually talks to Synthie."""
    return FileResponse(_WEB_DIR / "index.html")


@app.post("/api/research")
async def api_research(payload: dict) -> JSONResponse:
    """Research a customer's business from its website URL (cached on disk)."""
    url = (payload or {}).get("url", "")
    if not url or not str(url).strip():
        return JSONResponse({"error": "Provide a website URL."}, status_code=400)
    try:
        record = await research.research_business(str(url))
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=502)
    profile = record.get("profile", {}) or {}
    return JSONResponse({
        "domain": record.get("domain"),
        "cached": record.get("cached", False),
        "grounded": record.get("grounded", False),
        "confidence": (profile.get("confidence") or "").lower(),
        "company_name": profile.get("company_name"),
        "industry": profile.get("industry"),
    })


@app.get("/api/conversations")
async def list_conversations(domain: str = "") -> JSONResponse:
    """List cached conversations, optionally filtered by ?domain=<host>.

    Returns lightweight summaries (no transcript bodies). Pass a domain to get
    only that customer's sessions, newest first.
    """
    slug = research.domain_of(domain) if domain else ""
    summaries: list[dict] = []
    for path in _CONV_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if slug and data.get("domain") != slug:
            continue
        summaries.append({
            "id": path.stem,
            "domain": data.get("domain"),
            "session_id": data.get("session_id"),
            "started_at": data.get("started_at"),
            "updated_at": data.get("updated_at"),
            "turns": len(data.get("turns", [])),
        })
    summaries.sort(key=lambda s: s.get("started_at") or "", reverse=True)
    return JSONResponse({"count": len(summaries), "conversations": summaries})


@app.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: str) -> JSONResponse:
    """Return a single cached conversation (full transcript) by its id."""
    # Guard against path traversal — only allow plain file stems.
    if "/" in conv_id or "\\" in conv_id or ".." in conv_id:
        return JSONResponse({"error": "Invalid id."}, status_code=400)
    path = _CONV_DIR / f"{conv_id}.json"
    if not path.is_file():
        return JSONResponse({"error": "Not found."}, status_code=404)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse(data)


@app.websocket("/ws")
async def voice_relay(ws: WebSocket) -> None:
    """Relay Voice Live events between the browser and Azure."""
    await ws.accept()

    # The browser may pass ?domain=<host> so we can pre-load cached research
    # about the customer and seed it into the conversation as context.
    domain = ws.query_params.get("domain") or ""
    research_prompt = ""
    if domain:
        cached = research.load_cached(research.domain_of(domain))
        if cached:
            research_prompt = research.profile_to_prompt(cached)
            print(f"[relay] loaded research for {domain}")

    credential = AzureCliCredential()

    # Accumulate the conversation transcript and cache it to disk so each
    # session is saved (turn-by-turn, so a disconnect doesn't lose it).
    session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    conv_slug = research.domain_of(domain) if domain else "no-domain"
    conv_path = _CONV_DIR / f"{conv_slug}-{session_id}.json"
    conversation: dict = {
        "domain": conv_slug,
        "session_id": session_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "turns": [],
    }
    _assistant_buf: list[str] = []

    def _save_conversation() -> None:
        conversation["updated_at"] = datetime.now(timezone.utc).isoformat()
        try:
            conv_path.write_text(
                json.dumps(conversation, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:  # noqa: BLE001
            print(f"[relay] failed to cache conversation: {e}")

    def _add_turn(role: str, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        conversation["turns"].append({
            "role": role,
            "text": text,
            "at": datetime.now(timezone.utc).isoformat(),
        })
        _save_conversation()

    try:
        async with connect(
            endpoint=VOICELIVE_ENDPOINT,
            credential=credential,
            api_version=VOICELIVE_API_VERSION,
            model=MODEL_DEPLOYMENT_NAME,
            agent_name=AGENT_NAME,
            project_name=PROJECT_NAME,
            agent_version=AGENT_VERSION,
        ) as conn:

            # Configure audio in/out, the spoken voice, and server-side turn
            # detection. Without explicit turn_detection the agent's VAD is
            # disabled, so Azure never detects end-of-speech and never replies.
            await conn.session.update(session=RequestSession(
                modalities=[Modality.TEXT, Modality.AUDIO],
                voice=AzureStandardVoice(name=AZURE_VOICE),
                input_audio_format=InputAudioFormat.PCM16,
                output_audio_format=OutputAudioFormat.PCM16,
                turn_detection=ServerVad(
                    threshold=0.5,
                    prefix_padding_ms=300,
                    silence_duration_ms=500,
                    create_response=True,
                    interrupt_response=True,
                ),
            ))

            # If we researched this customer's website, seed that context first
            # so Synthie can confirm rather than re-ask the basics.
            if research_prompt:
                await conn.send({
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": research_prompt}],
                    },
                })

            # Synthie speaks first: seed a hidden kickoff user turn, then request
            # a response. A bare response.create on an empty conversation yields
            # nothing, so we inject a short opener cue the agent responds to. The
            # agent's own system prompt (instructions.md, Stage 1 opener) owns the
            # exact wording — Q1 asks what industry they're selling into. The
            # agent service rejects a per-turn instructions override, so we cue,
            # we don't dictate.
            await conn.send({
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Start the session with your opener and Q1."}],
                },
            })
            await conn.send({"type": "response.create"})

            async def browser_to_azure() -> None:
                try:
                    while True:
                        msg = await ws.receive_json()
                        await conn.send(msg)
                except WebSocketDisconnect:
                    pass

            async def azure_to_browser() -> None:
                async for event in conn:
                    etype = str(getattr(event, "type", "?"))
                    # Log meaningful turn events; skip the high-volume audio deltas.
                    if "audio.delta" not in etype and "transcript.delta" not in etype:
                        print(f"[relay] {etype}")
                        if etype == "error":
                            err = getattr(event, "error", event)
                            print(f"    error: {getattr(err, 'message', err)}")

                    # Cache the conversation transcript turn-by-turn.
                    if etype == "conversation.item.input_audio_transcription.completed":
                        _add_turn("user", getattr(event, "transcript", "") or "")
                    elif etype == "response.audio_transcript.delta":
                        _assistant_buf.append(getattr(event, "delta", "") or "")
                    elif etype == "response.done":
                        _add_turn("synthie", "".join(_assistant_buf))
                        _assistant_buf.clear()

                    await ws.send_json(event.as_dict())

            b2a = asyncio.create_task(browser_to_azure())
            a2b = asyncio.create_task(azure_to_browser())

            done, pending = await asyncio.wait(
                {b2a, a2b}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        try:
            await ws.send_json({"type": "relay.error", "message": str(e)})
        except Exception:  # noqa: BLE001
            pass
    finally:
        # Flush any partial assistant turn and persist the final transcript.
        if _assistant_buf:
            _add_turn("synthie", "".join(_assistant_buf))
            _assistant_buf.clear()
        if conversation["turns"]:
            _save_conversation()
            print(f"[relay] cached conversation -> {conv_path.name} "
                  f"({len(conversation['turns'])} turns)")
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass


app.mount("/web", StaticFiles(directory=str(_WEB_DIR)), name="web")


def main() -> None:
    print(f"\nSynthie web server starting…")
    print(f"  Agent      : {AGENT_NAME}" + (f" v{AGENT_VERSION}" if AGENT_VERSION else " (latest)"))
    print(f"  Project    : {PROJECT_NAME}")
    print(f"  Open       : http://localhost:{PORT}\n")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
