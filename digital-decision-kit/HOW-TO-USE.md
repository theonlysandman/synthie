# How to use the Digital Decision Kit

A 20-minute, self-serve way to find the **first AI use case** worth building for one of your
customers — and turn it into a one-page brief you can share. No setup, no install. Works in any
capable chat assistant (Microsoft Copilot recommended).

> **Do this by talking, not typing.** Use the microphone / dictation button in your chat app (or
> your device's voice-to-text) and *speak* your answers. People say far more out loud than they
> type, and richer answers make a sharper brief. Don't worry about rambling — that's the point.

---

## What you'll end up with

A single **one-page brief** that names:
- who the customer is and where their money moves,
- the **one** AI use case to build first,
- a 0–5 scorecard (technical fit, implementability, value, deployability),
- how to build it on **Microsoft Azure**, and
- the first next step.

You then **email that brief back** (see the rollout folder for who/where).

---

## The 5 steps

1. **(Optional, ~5 min) Do a little research.** Open `research-starter.md` and either run the
   research prompt in Copilot or jot a few notes. Skip this if you already know the customer well.

2. **Start Synthie.** Open `synthie-system-prompt.md`, copy everything below its divider line, and
   paste it into a **new chat** in Microsoft Copilot (or ChatGPT / your assistant). Send it.

3. **Answer its questions, one at a time.** Synthie asks about the customer first — industry, the
   person you'd help, how they make money, what data they have. **Tap the mic and just talk** in
   your own words. If you did research, paste it in right after the first question.

4. **Confirm the picture, then get your ideas.** Synthie plays back what it heard and asks "Did I
   get that right?" Once you confirm, it surfaces 3–4 AI use cases, scores them, and recommends the
   **one to build first**.

5. **Generate and send the brief.** Say **"finalize"** (or paste `finalize-onepager.md`). Copy the
   one-page brief it returns, add the 3 quick feedback notes from `rollout/feedback-3q.md`, and
   **email it back**.

---

## Tips for a good result

- **Speak, don't type.** Use the mic / dictation button — it's the single biggest thing you can do
  for a better brief.
- **Pick a customer you actually know.** The brief is only as good as what you tell Synthie.
- **Ramble freely.** Long, messy, spoken answers are great — Synthie sorts them out.
- **It's fine not to know everything.** Say "I'm not sure" — Synthie marks it as an assumption.
- **First AI project mindset.** Synthie deliberately favours the idea you can *build and prove now*
  on Azure over the flashiest idea. That's the point.
- **Want a different pick?** Say "more options" or ask it to re-score — you're in control.

## See a finished example

`example-ibema.md` shows a complete run for a real customer (a Brazilian cartonboard maker) — from
customer snapshot to the chosen use case (predictive maintenance to cut paper-machine breaks) and
the Azure build path. Skim it to see where you're headed.

## Troubleshooting

- **It jumped to ideas too fast** → say "back to profile" and add more about the customer.
- **The ideas feel generic** → give it more on *where the money moves* and *what data they have*.
- **You want it Microsoft-only** → say "make it Microsoft" and it re-states the build on Azure.
