// app.js — Synthie browser voice client
// Captures mic at 24 kHz PCM16, streams to the relay backend, plays replies.

const SAMPLE_RATE = 24000;

const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");
const statusEl = document.getElementById("status");
const micEl = document.getElementById("mic");
const logEl = document.getElementById("log");
const diagEl = document.getElementById("diag");

// If we arrived from the landing page with a researched domain, show it.
const _domain = new URLSearchParams(location.search).get("domain");
if (_domain) {
  const sub = document.querySelector(".sub");
  if (sub) sub.textContent = `Researching with context from ${_domain}`;
}

let ws = null;
let audioCtx = null;
let micStream = null;
let sourceNode = null;
let processorNode = null;
let sentChunks = 0;

// Playback scheduling
let playCtx = null;
let playCursor = 0;
let scheduledSources = [];

// Audio diagnostics (surfaced on the page so playback is observable).
let audioDeltasReceived = 0;
let audioChunksPlayed = 0;
let lastAudioError = "";

function renderDiag() {
  const state = playCtx ? playCtx.state : "none";
  const cursor = playCtx ? (playCursor - playCtx.currentTime).toFixed(2) : "-";
  diagEl.textContent =
    `audio.delta received: ${audioDeltasReceived}  |  chunks played: ${audioChunksPlayed}  |  ` +
    `playCtx: ${state}  |  queue lead: ${cursor}s` +
    (lastAudioError ? `\nlast audio error: ${lastAudioError}` : "");
}

let currentSynthieRow = null;

function setStatus(text, cls = "") {
  statusEl.textContent = text;
  statusEl.className = cls;
}

function logRow(text, cls) {
  const row = document.createElement("div");
  row.className = "row " + cls;
  row.textContent = text;
  logEl.appendChild(row);
  logEl.scrollTop = logEl.scrollHeight;
  return row;
}

// ---- PCM helpers ----
function floatTo16BitPCM(float32) {
  const out = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

// Linear resample a Float32 buffer from inRate to outRate.
function resample(float32, inRate, outRate) {
  if (inRate === outRate) return float32;
  const ratio = inRate / outRate;
  const outLen = Math.round(float32.length / ratio);
  const out = new Float32Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const srcPos = i * ratio;
    const i0 = Math.floor(srcPos);
    const i1 = Math.min(i0 + 1, float32.length - 1);
    const frac = srcPos - i0;
    out[i] = float32[i0] * (1 - frac) + float32[i1] * frac;
  }
  return out;
}

function int16ToBase64(int16) {
  const bytes = new Uint8Array(int16.buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

function base64ToInt16(b64) {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Int16Array(bytes.buffer);
}

// ---- Playback ----
function ensurePlayCtx() {
  if (!playCtx) {
    playCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: SAMPLE_RATE });
    playCursor = playCtx.currentTime;
  }
  // Browsers start contexts suspended under autoplay policy — resume it.
  if (playCtx.state === "suspended") {
    playCtx.resume().catch(() => {});
  }
  return playCtx;
}

function playChunk(int16) {
  ensurePlayCtx();
  const float32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 0x8000;

  const buffer = playCtx.createBuffer(1, float32.length, SAMPLE_RATE);
  buffer.copyToChannel(float32, 0);

  const src = playCtx.createBufferSource();
  src.buffer = buffer;
  src.connect(playCtx.destination);
  scheduledSources.push(src);
  src.onended = () => {
    const i = scheduledSources.indexOf(src);
    if (i !== -1) scheduledSources.splice(i, 1);
  };

  const now = playCtx.currentTime;
  if (playCursor < now) playCursor = now;
  src.start(playCursor);
  playCursor += buffer.duration;
  audioChunksPlayed++;
  renderDiag();
}

function flushPlayback() {
  // Barge-in: stop everything queued without tearing down the context
  // (closing/recreating would land us back in a suspended state).
  for (const src of scheduledSources) {
    try { src.stop(); } catch (_) {}
    src.onended = null;
  }
  scheduledSources = [];
  if (playCtx) playCursor = playCtx.currentTime;
}

// ---- Voice Live event handling ----
function handleEvent(evt) {
  const type = evt.type || "";

  switch (type) {
    case "session.created":
    case "session.updated":
      setStatus("Live — speak now", "live");
      break;

    case "input_audio_buffer.speech_started":
      micEl.className = "speaking";
      flushPlayback(); // barge-in
      break;

    case "input_audio_buffer.speech_stopped":
      micEl.className = "listening";
      break;

    case "conversation.item.input_audio_transcription.completed":
      if (evt.transcript) logRow("You: " + evt.transcript, "you");
      break;

    case "response.audio_transcript.delta":
      if (!currentSynthieRow) currentSynthieRow = logRow("Synthie: ", "synthie");
      currentSynthieRow.textContent += evt.delta || "";
      logEl.scrollTop = logEl.scrollHeight;
      break;

    case "response.audio.delta":
      if (evt.delta) {
        audioDeltasReceived++;
        try {
          playChunk(base64ToInt16(evt.delta));
        } catch (err) {
          lastAudioError = String(err);
          console.error("[synthie] playback error:", err);
        }
        renderDiag();
      }
      break;

    case "response.done":
      currentSynthieRow = null;
      break;

    case "error":
    case "relay.error": {
      const m = (evt.error && evt.error.message) || evt.message || JSON.stringify(evt);
      logRow("[error] " + m, "meta");
      setStatus("Error: " + m, "error");
      break;
    }
  }
}

// ---- Start / stop ----
async function start() {
  startBtn.disabled = true;
  setStatus("Connecting…");

  try {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
  } catch (e) {
    setStatus("Microphone denied", "error");
    startBtn.disabled = false;
    return;
  }

  audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: SAMPLE_RATE });
  await audioCtx.resume();
  console.log("[synthie] mic AudioContext sampleRate =", audioCtx.sampleRate, "(target", SAMPLE_RATE + ")");

  // Prime the playback context now, inside the user gesture, so Synthie's
  // opening greeting can play without being blocked by autoplay policy.
  ensurePlayCtx();
  if (playCtx.state === "suspended") await playCtx.resume();
  audioDeltasReceived = 0;
  audioChunksPlayed = 0;
  lastAudioError = "";
  renderDiag();

  const proto = location.protocol === "https:" ? "wss" : "ws";
  const domain = new URLSearchParams(location.search).get("domain");
  const wsUrl = `${proto}://${location.host}/ws` + (domain ? `?domain=${encodeURIComponent(domain)}` : "");
  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    setStatus("Live — speak now", "live");
    micEl.className = "listening";
    stopBtn.disabled = false;

    sourceNode = audioCtx.createMediaStreamSource(micStream);
    processorNode = audioCtx.createScriptProcessor(2048, 1, 1);

    sentChunks = 0;
    processorNode.onaudioprocess = (e) => {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      const input = e.inputBuffer.getChannelData(0);
      const resampled = resample(input, audioCtx.sampleRate, SAMPLE_RATE);
      const pcm16 = floatTo16BitPCM(resampled);
      ws.send(JSON.stringify({
        type: "input_audio_buffer.append",
        audio: int16ToBase64(pcm16),
      }));
      sentChunks++;
      if (sentChunks % 25 === 0) console.log("[synthie] sent", sentChunks, "audio chunks");
    };

    sourceNode.connect(processorNode);
    processorNode.connect(audioCtx.destination);
  };

  ws.onmessage = (e) => {
    let evt;
    try {
      evt = JSON.parse(e.data);
    } catch (err) {
      console.error("[synthie] bad message:", err);
      return;
    }
    try {
      handleEvent(evt);
    } catch (err) {
      lastAudioError = String(err);
      console.error("[synthie] handleEvent error on", evt && evt.type, err);
      renderDiag();
    }
  };

  ws.onerror = () => setStatus("Connection error", "error");
  ws.onclose = () => { if (stopBtn.disabled === false) stop(); };
}

function stop() {
  if (processorNode) { processorNode.disconnect(); processorNode.onaudioprocess = null; processorNode = null; }
  if (sourceNode) { sourceNode.disconnect(); sourceNode = null; }
  if (micStream) { micStream.getTracks().forEach((t) => t.stop()); micStream = null; }
  if (audioCtx) { audioCtx.close(); audioCtx = null; }
  if (ws) { ws.close(); ws = null; }
  flushPlayback();

  micEl.className = "";
  setStatus("Stopped");
  startBtn.disabled = false;
  stopBtn.disabled = true;
}

startBtn.addEventListener("click", start);
stopBtn.addEventListener("click", stop);
