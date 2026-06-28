# Example — a finished Synthie run (Ibema)

This is what "good" looks like: a real customer taken from a messy conversation to a single,
shareable brief. Use it to see where you're headed. (Customer: **Ibema**, a Brazilian cartonboard
maker.)

---

# First Digital Decision — Ibema × Predictive maintenance to cut paper-machine breaks

## Customer snapshot
- **Industry & location:** Packaging board (cartonboard) manufacturing — Paraná, Brazil. Plants in
  Turvo and Embu das Artes.
- **Company (what they do / how they make money):** Ibema Companhia Brasileira de Papel makes
  packaging board (not graphic paper). Revenue is tonnes of board sold; profitability is driven by
  **cost-per-tonne**. Suzano is a shareholder; they're currently closing one mill while acquiring
  others — an offensive consolidation play (*inference*).
- **Person or role we'd help:** The **CEO / General Manager** (Nilton Saraiva).
- **Where the money moves:** Value is won or lost on **cost-per-tonne competitiveness** and
  **asset-footprint optimization**. Unplanned downtime and wasted fibre hit margin directly.
- **Key pain:** Costly **unplanned web/sheet breaks** on the paper machine — each one is lost
  production and wasted fibre.

## The first digital decision (the pick)
- **Use case:** Predict paper-machine **web/sheet breaks** before they happen.
- **AI type:** ML (predictive).
- **Outcome (their language):** Cut cost-per-tonne by reducing unplanned breaks and the lost
  production and fibre that come with them.
- **Why AI makes it possible:** The process historian holds subtle multi-sensor patterns that
  precede a break — patterns no operator can watch in real time. ML learns them and gives roughly
  **11.5 minutes** of warning. Technique: **anomaly detection / predictive maintenance** on labelled
  historian data.
- **Data it needs (and whether they have it):** The **PI/PHD historian** — one read-only connection
  yields both the high-frequency machine signals *and* the break labels. **They already have it.**

## Scorecard (0–5)
| Use case | AI Technical Fit | Implementability | Business Value | Deployability (Azure + customer) |
|---|---|---|---|---|
| **Predict web/sheet breaks** | 5 | 5 | 5 | 5 |
| Demand/throughput forecasting | 4 | 3 | 3 | 3 |
| Quality-defect anomaly detection | 4 | 3 | 4 | 3 |

**Why this one wins:** It scores top marks on technical fit *and* implementability — the data is
already there, labelled, and rich — so it clears the "first AI" bar that the others don't. It lands
straight on their #1 lever (cost-per-tonne), and it's provable **offline on a historian export** with
no control-system access, making it the lowest-friction, highest-trust first wedge.

## How it gets built on Microsoft Azure
- **Azure services:** **Azure Machine Learning** (train/deploy the predictive model),
  **Azure AI Foundry** (project home), **Microsoft Fabric / Azure Data Lake** (land the historian
  export). Add **Azure ML managed endpoints** when moving toward near-real-time scoring.
- **How it deploys in the BU's Azure:** Stand up an Azure ML workspace in the BU's own subscription;
  train and validate on the exported historian data there.
- **How it lands at the customer (proof-first):** No DCS/control-system access early — prove the
  break-prediction model on **exported, read-only data**, then expand. "The vendor changes the
  connector, not the strategy."
- **Proof-of-value step:** Show, on a historian export, that the model would have flagged past breaks
  ~11.5 minutes ahead → quantify breaks avoided × cost per break.

## First next step
- Request a **read-only historian export** (signals + break labels) for one machine, and validate
  the break-prediction model offline in an Azure ML workspace.

## Assumptions & open questions
- *Inference:* the close-one/acquire-others move is offensive consolidation, not retreat — confirm.
- *Inference:* top priorities are cost-per-tonne (90), asset-footprint optimization (88), fibre
  security (80) — confirm with the GM.
- Confirm the historian (PI/PHD) export can be shared read-only and includes reliable break labels.
