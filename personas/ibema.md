# Seed — Ibema (Paraná cartonboard maker)

Use this as **known evidence** grounding the customer profile. Keep **facts** and **inferences**
separate, exactly as the agent should. This makes State 1 Ibema-accurate out of the gate, so you
can confirm it quickly rather than re-asking, then move to State 2 (the first ML play).

## The person to sell to

The **CEO / General Manager** of a Paraná-based cartonboard (packaging-board) maker.

## Known facts (from the Ibema Opportunity Analysis)

- Company: **Ibema Companhia Brasileira de Papel**.
- CEO: **Nilton Saraiva**.
- Plants in **Turvo** and **Embu das Artes**.
- **Suzano** is a shareholder.
- Product is **packaging board / cartonboard** — not graphic paper.
- Currently **closing one mill while acquiring others**.

## Data inventory (the hinge for any ML play)

- **Process historian (PI / PHD)** — the single read-only connection that yields both the
  high-frequency machine signals *and* the break labels (when a web/sheet break actually happened).
  This is rich, labelled, time-series data: the strongest possible base for an ML use case.
- Likely also: production/throughput records, quality data, and downtime logs.

## Inferences (hypotheses — not fact)

- The close-one / acquire-others move reads as an **offensive consolidation play**, not a retreat.
- Top business priorities (0–100):
  - **Cost-per-tonne competitiveness — 90**
  - Asset-footprint optimization — 88
  - Fiber security — 80
- How they react to new ideas: **"prove it on exported data before anyone touches a control
  system"** — proof-first, low-risk, no DCS/control-system access early on.

## Candidate first ML play (for State 2)

- **Outcome:** cut costly unplanned **web/sheet breaks** on the paper machine — each break is lost
  production and wasted fibre, so this lands straight on **cost-per-tonne**.
- **Why ML makes it possible:** the historian holds the subtle multi-sensor patterns that precede a
  break — patterns no operator can watch in real time. ML learns them and gives **~11.5 minutes** of
  warning. Technique: **anomaly detection / predictive maintenance** on the labelled historian data.
- **Data it needs — which they have:** the PI/PHD historian signals + break labels. Already present.
- **Why it's first:** clean, bounded, provable **offline on a historian export** with no control-system
  risk — the lowest-friction wedge with the clearest ROI (breaks avoided × cost per break).
- **Why it grows the seller's organic revenue:** proving cost-per-tonne savings on a read-only export
  builds the trust to expand across machines and plants — "the vendor changes the connector, not the
  strategy."