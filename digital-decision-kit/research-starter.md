# Optional: research your customer first (paste-in prompt)

You don't *need* to do research before using Synthie — you can just answer its questions from what
you already know. But a few minutes of research makes the brief sharper and faster, because Synthie
can confirm facts instead of asking for them.

**Two ways to do it:**

## Option A — Use your own AI assistant to gather it
Paste the prompt below into Microsoft Copilot (or any assistant with web access), filling in the
customer name. Then copy its answer and paste it into Synthie at the start of your session.

```
Research the company "<CUSTOMER NAME>" (website: <URL if known>) and give me a short, factual brief:

1. Industry, location, and what the company actually does.
2. How it makes money — main revenue lines and biggest cost drivers.
3. Who likely leads it (CEO / GM / relevant decision-maker) and what they're measured on.
4. Recent moves or pressures (acquisitions, closures, market shifts).
5. What data systems a company like this probably runs (ERP, CRM, historian, ticketing, etc.).

Separate confirmed FACTS from your INFERENCES. Keep it under 250 words. Cite sources if you have them.
```

## Option B — Gather it yourself
Jot a few notes on the same five points above. Even rough notes help.

**Then:** start a Synthie session (see `synthie-system-prompt.md`) and paste your research in right
after its first question. Synthie will treat it as known evidence and confirm it quickly.

> Tip: keep facts and guesses separate when you paste — Synthie is built to respect that line.
