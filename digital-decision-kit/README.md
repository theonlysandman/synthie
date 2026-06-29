# Digital Decision Kit

A portable, paste-anywhere prompt kit that helps a CSI business unit find the **first AI use case**
worth building for a customer — and turn it into a one-page brief, in about 20 minutes, with no
setup. Built to work in any tenant and any capable chat assistant (Microsoft Copilot recommended).

It's powered by **Synthie**, a two-stage discovery guide:
1. **Understand the customer** (industry, person, company, where the money moves, what data exists).
2. **Find & score the first digital decision** — 3–4 AI use case candidates scored 0–5 on technical
   fit, real-world implementability, business value, and deployability on **Microsoft Azure** — then
   narrowed to the **one to build first**, using a deliberate "first AI project" lens.

The output is a standardized **one-page brief** you can email back.

## What's in here

| File | What it's for |
|---|---|
| `synthie-system-prompt.md` | **The core.** Paste this into a chat to run the whole discovery. |
| `rollout/quick-start.md` | One-page step-by-step guide for the person doing it. |
| `research-starter.md` | Optional prompt/checklist to research the customer first. |
| `finalize-onepager.md` | Paste-in prompt to produce the final brief on demand. |
| `example-ibema.md` | A complete worked example (Ibema → predictive maintenance). |
| `feedback-3q.md` | 3 feedback questions to send back with the brief. |
| `rollout/` | The invite email for distributing to BUs. |

## Quick start

1. Open `synthie-system-prompt.md`, copy below the divider, paste into Microsoft Copilot.
2. Answer its questions about a customer you know.
3. Say "finalize" to get the one-page brief.
4. Email it back (with the 3 feedback notes from `feedback-3q.md`).

See `quick-start.md` for the full one-page guide.

---

> The voice-based version of Synthie lives in the repository root (`main.py`, `server.py`, `web/`,
> etc.) and is unchanged. This kit is the text-based, shareable path.
