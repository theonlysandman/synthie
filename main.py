"""
main.py — Real-time voice loop for Synthie (synthetic customer agent)
=====================================================================
Streams mic audio to Azure Voice Live, routes it through the Synthie
Foundry Agent, and plays the spoken reply out of the speaker.
Live transcript is printed to the console.

Authentication: AzureCliCredential (local dev — requires `az login`).
Voice Live Agent mode does NOT support API-key auth.

Usage:
    python main.py

Required env vars (set in .env):
    VOICELIVE_ENDPOINT      - https://<resource>.services.ai.azure.com/
    PROJECT_NAME            - short project name (last segment of PROJECT_ENDPOINT)
    AGENT_NAME              - name of the agent created by create_agent.py

Optional env vars:
    AGENT_VERSION           - pin a specific agent version; blank = latest
    VOICELIVE_API_VERSION   - API version string (default: 2026-04-10)
    AZURE_VOICE             - TTS voice name (default: en-US-AvaNeural)

Controls:
    Ctrl+C  →  clean shutdown
"""

import asyncio
import os
import sys
from typing import Optional

import pyaudio
from dotenv import load_dotenv
from azure.identity import AzureCliCredential

# Voice Live SDK — async-only since azure-ai-voicelive 1.0.0b5
from azure.ai.voicelive.aio import connect
from azure.ai.voicelive.models import (
    AudioInputTranscriptionOptions,
    AzureSemanticVadMultilingual,
    AzureStandardVoice,
    InputAudioFormat,
    Modality,
    OutputAudioFormat,
    RequestSession,
    ServerEventType,
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
VOICELIVE_API_VERSION: str = os.environ.get("VOICELIVE_API_VERSION", "2026-04-10")
AZURE_VOICE: str = os.environ.get("AZURE_VOICE", "en-US-AvaNeural")

# ---------------------------------------------------------------------------
# Audio constants
# ---------------------------------------------------------------------------
SAMPLE_RATE = 24_000        # Hz
CHANNELS = 1                # mono
FORMAT = pyaudio.paInt16    # 16-bit PCM
CHUNK_FRAMES = 1200         # ~50 ms at 24 kHz


# ---------------------------------------------------------------------------
# Microphone capture task
# ---------------------------------------------------------------------------

async def _mic_task(
    conn,
    stop_event: asyncio.Event,
    loop: asyncio.AbstractEventLoop,
) -> None:
    mic_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=50)
    pa = pyaudio.PyAudio()

    def _callback(in_data, frame_count, time_info, status_flags):  # noqa: ARG001
        loop.call_soon_threadsafe(mic_queue.put_nowait, in_data)
        return (None, pyaudio.paContinue)

    stream = pa.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=SAMPLE_RATE,
        input=True,
        frames_per_buffer=CHUNK_FRAMES,
        stream_callback=_callback,
    )
    stream.start_stream()

    try:
        while not stop_event.is_set():
            try:
                chunk = await asyncio.wait_for(mic_queue.get(), timeout=0.2)
            except asyncio.TimeoutError:
                continue
            try:
                await conn.input_audio_buffer.append(audio=chunk)
            except Exception:  # noqa: BLE001
                break
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()


# ---------------------------------------------------------------------------
# Speaker playback task
# ---------------------------------------------------------------------------

async def _speaker_task(
    audio_queue: asyncio.Queue,
    stop_event: asyncio.Event,
    loop: asyncio.AbstractEventLoop,
) -> None:
    pa = pyaudio.PyAudio()
    out_stream = pa.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=SAMPLE_RATE,
        output=True,
        frames_per_buffer=CHUNK_FRAMES,
    )

    try:
        while not stop_event.is_set():
            try:
                chunk = await asyncio.wait_for(audio_queue.get(), timeout=0.2)
            except asyncio.TimeoutError:
                continue

            if chunk is None:
                # Barge-in sentinel: flush outstanding audio chunks.
                while not audio_queue.empty():
                    try:
                        audio_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                continue

            await loop.run_in_executor(None, out_stream.write, chunk)
    finally:
        out_stream.stop_stream()
        out_stream.close()
        pa.terminate()


# ---------------------------------------------------------------------------
# Main voice loop
# ---------------------------------------------------------------------------

async def _voice_loop() -> None:
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    audio_queue: asyncio.Queue = asyncio.Queue(maxsize=100)

    agent_config = {
        "agent_name": AGENT_NAME,
        "project_name": PROJECT_NAME,
        "agent_version": AGENT_VERSION,
        "conversation_id": None,
        "foundry_resource_override": None,
        "authentication_identity_client_id": None,
    }

    credential = AzureCliCredential()

    print(f"\nConnecting Synthie to Voice Live…")
    print(f"  Endpoint   : {VOICELIVE_ENDPOINT}")
    print(f"  Agent      : {AGENT_NAME}" + (f" v{AGENT_VERSION}" if AGENT_VERSION else " (latest)"))
    print(f"  Project    : {PROJECT_NAME}")
    print(f"  Voice      : {AZURE_VOICE}")
    print(f"\nSynthie is ready. Speak to begin the simulation. Press Ctrl+C to exit.\n")

    async with connect(
        endpoint=VOICELIVE_ENDPOINT,
        credential=credential,
        api_version=VOICELIVE_API_VERSION,
        agent_config=agent_config,
    ) as conn:

        session_config = RequestSession(
            modalities=[Modality.TEXT, Modality.AUDIO],
            input_audio_format=InputAudioFormat.PCM16,
            output_audio_format=OutputAudioFormat.PCM16,
            voice=AzureStandardVoice(name=AZURE_VOICE),
            turn_detection=AzureSemanticVadMultilingual(),
            input_audio_transcription=AudioInputTranscriptionOptions(
                model="mai-transcribe-1",
            ),
        )
        await conn.session.update(session=session_config)

        mic = asyncio.create_task(_mic_task(conn, stop_event, loop), name="mic-capture")
        spk = asyncio.create_task(_speaker_task(audio_queue, stop_event, loop), name="speaker-play")

        _in_agent_turn = False

        try:
            async for event in conn:
                etype = event.type

                if etype == ServerEventType.SESSION_UPDATED:
                    sid = getattr(event.session, "id", "unknown")
                    print(f"[Session ready — ID: {sid}]")
                    print("[Synthie is listening…]\n")

                elif etype == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
                    if _in_agent_turn:
                        print("\n[You interrupted Synthie — cancelling response…]")
                        try:
                            await conn.response.cancel()
                        except Exception:  # noqa: BLE001
                            pass
                        await audio_queue.put(None)
                        _in_agent_turn = False
                    print("\nAgent-under-test: ", end="", flush=True)

                elif etype == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STOPPED:
                    print()

                elif etype == getattr(
                    ServerEventType,
                    "CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_DELTA",
                    None,
                ):
                    print(getattr(event, "delta", ""), end="", flush=True)

                elif etype == getattr(
                    ServerEventType,
                    "CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED",
                    None,
                ):
                    transcript = getattr(event, "transcript", "")
                    print(f"\rAgent-under-test: {transcript}", flush=True)

                elif etype == ServerEventType.RESPONSE_AUDIO_DELTA:
                    audio_chunk = event.delta
                    if isinstance(audio_chunk, str):
                        import base64
                        audio_chunk = base64.b64decode(audio_chunk)
                    if audio_chunk:
                        await audio_queue.put(audio_chunk)
                    _in_agent_turn = True

                elif etype == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DELTA:
                    if not _in_agent_turn:
                        print("\nSynthie: ", end="", flush=True)
                        _in_agent_turn = True
                    print(getattr(event, "delta", ""), end="", flush=True)

                elif etype == ServerEventType.RESPONSE_DONE:
                    if _in_agent_turn:
                        print()
                        _in_agent_turn = False

                elif etype == getattr(ServerEventType, "WARNING", None):
                    msg = getattr(getattr(event, "warning", None), "message", str(event))
                    print(f"\n[Warning: {msg}]", flush=True)

                elif etype == ServerEventType.ERROR:
                    err = getattr(event, "error", event)
                    code = getattr(err, "code", "unknown")
                    msg = getattr(err, "message", str(err))
                    print(f"\n[Error {code}]: {msg}", flush=True)

        except KeyboardInterrupt:
            pass
        finally:
            stop_event.set()
            mic.cancel()
            spk.cancel()
            try:
                await asyncio.gather(mic, spk, return_exceptions=True)
            except Exception:  # noqa: BLE001
                pass

    print("\n[Synthie session closed — goodbye!]")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    try:
        asyncio.run(_voice_loop())
    except KeyboardInterrupt:
        print("\n[Ctrl+C received — exiting.]")


if __name__ == "__main__":
    main()
