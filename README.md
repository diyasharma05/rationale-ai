# Rationale.AI

**A confidence-driven KPI intelligence-to-action engine.**
Team Rational.ai · Accenture Innovation Challenge 2026 · Round 2 · Track 3 (BusinessIntelligence.ai)

Dashboards tell you *what* changed. Rationale.AI tells you **why**, how confident it is,
and **what to do about it** — and when the evidence isn't there, it **abstains and asks a
human** instead of inventing a story.

It detects material KPI movements with SQL, statistics and machine learning, escalates
through a four-level reasoning pyramid with a confidence gate at every step, and only
then lets a language model put the findings into words.

> **The core rule: the LLM never computes a number.** A typical investigation runs
> ~18 SQL queries, ~10 statistical tests, 5 ML models and 6 document retrievals —
> and exactly **2 LLM calls**, both of which only write sentences.

---

## Architecture

```
 STRUCTURED SOURCES                                UNSTRUCTURED CONTEXT
 ─────────────────────────────────────             ──────────────────────────
 OrderDB (OMS)          transaction grain          support tickets
 LogiTrack (WMS)        daily × region             exit-call transcripts
 RelateCRM events       event grain, weekly sync   ops notes · Slack threads
 RelateCRM marketing    weekly × region            past incident postmortems
          │                                                  │
          │  DuckDB · SQL taken from the semantic contract    │
          │  row / column / domain security injected per role │
          ▼                                                  │
 ╔═══════════════════════════════════════════════╗           │
 ║ LEVEL 1 · CROSS-FUNCTIONAL SIGNALS   non-LLM  ║           │
 ║   z-score vs the KPI's own threshold          ║           │
 ║   OLS trend forecast, 90% interval            ║           │
 ║   IsolationForest per region, daily grain     ║           │
 ║   contribution by region / segment / category ║           │
 ║   driver checks + 12-month co-movement        ║           │
 ╚═══════════════════════╤═══════════════════════╝           │
      SIGNAL GATE        │  material? statistical AND ₹ impact│
      fails → stop here  │  (0 tokens spent on noise)         │
                         ▼                                    │
 ╔═══════════════════════════════════════════════╗            │
 ║ LEVEL 2 · COMPANY CONTEXT                     ║◀───────────┘
 ║   retrieval ranking          non-LLM          ║◀─── decision ledger
 ║   evidence → hypothesis map  LLM (Haiku 4.5)  ║     (past investigations
 ║   mappings are COUNTED in Python              ║      + user corrections)
 ╚═══════════════════════╤═══════════════════════╝
                         ▼
 ╔═══════════════════════════════════════════════╗
 ║ LEVEL 3 · EXTERNAL SIGNALS           non-LLM  ║◀─── market-event feed
 ║   competitor / industry / macro matching      ║     (competitor moves,
 ╚═══════════════════════╤═══════════════════════╝      macro notes)
                         │
    EVIDENCE GATE ≥ 0.60 │  may state a root cause
      ACTION GATE ≥ 0.75 │  may recommend actions
      below either       │  ↓
                         ▼
 ╔═══════════════════════════════════════════════╗
 ║ LEVEL 4 · EXPERT ESCALATION                   ║
 ║   abstain · clarifying question · brief       ║
 ╚═══════════════════════╤═══════════════════════╝
                         ▼
 ╔═══════════════════════════════════════════════╗
 ║ NARRATIVE LAYER                LLM (Sonnet 5) ║
 ║   persona-specific prose, numbers passed in   ║
 ║   verbatim · deterministic de-slop sanitizer  ║
 ║   offline fixtures + template fallback        ║
 ╚═══════════════════════╤═══════════════════════╝
                         ▼
        STREAMLIT UI  ·  Dashboard · Data · Investigation
                         Decision Ledger · Under the Hood
```

**Confidence is computed, never generated:**

```
score = 0.35 × signal strength      (|z| capped at 3)
      + 0.35 × driver coverage      (consistent drivers ÷ declared drivers,
                                     penalised by contradicting ones)
      + 0.30 × evidence agreement   (hypotheses corroborated by documents
                                     or external events ÷ all hypotheses)
```

Everything the engine reads — KPI definitions, the SQL itself, materiality thresholds,
causal driver links, action levers with owners and approvers, lineage and access rules —
lives in one governed file: [`contracts/kpi_contract.yaml`](contracts/kpi_contract.yaml).
It is **executed, not documentation**.

---

## Quick start

Prerequisites: **Python 3.11+** (tested on 3.13) and **git**. Windows, macOS or Linux.
**No API key required** — the demo runs fully offline out of the box.

```bash
# 1. Clone and enter the project
git clone https://github.com/diyasharma05/rationale-ai.git
cd rationale-ai

# 2. Create and activate a virtual environment
python -m venv .venv
#    Windows (PowerShell):
.venv\Scripts\Activate.ps1
#    macOS / Linux:
source .venv/bin/activate

# 3. Install dependencies (~2 min: streamlit, duckdb, scikit-learn, plotly, anthropic)
pip install -r requirements.txt

# 4. Generate the synthetic dataset (seeded — identical on every machine, ~30 s)
#    Writes data/*.csv, the unstructured documents and the market-event feed,
#    and resets the decision ledger.
python data/generate_data.py

# 5. OPTIONAL — add an Anthropic API key for live narratives. Pick ONE:
#    a) this terminal session:
#       Windows:        $env:ANTHROPIC_API_KEY = "sk-ant-your-key-here"
#       macOS / Linux:  export ANTHROPIC_API_KEY="sk-ant-your-key-here"
#    b) a .env file:    copy .env.example to .env and paste the key into it
#    c) inside the app: sidebar → LLM settings → paste key → "Use this key"

# 6. Launch
streamlit run app.py
```

The browser opens at **http://localhost:8501** and lands on the Dashboard.
Pick a role in the sidebar, set the analysis window (top right) to **July 2026**,
and click **Investigate** on a flagged KPI. `Ctrl+C` stops the server.

### LLM modes

| Mode | How | Behaviour |
|---|---|---|
| **Offline** (default) | no key set, or `MOCK_MODE=1` | replays the committed responses in `llm/fixtures/` plus deterministic fallbacks — instant, and cannot fail during a demo |
| **Live** | key via env, `.env`, or the in-app field | Claude generates fresh narratives (~10–20 s per investigation, ≈ ₹1–3 each) |

A key entered in the app is held **in memory only** and never written to disk.
`python record_fixtures.py` refreshes the offline fixtures from one live run — and is
the only script permitted to write them, so a live session can never overwrite the demo.

---

## What you can do in the app

**Dashboard** — severity-ordered KPI triage. Stat tiles for the month (KPIs needing
attention, ₹ impact, largest deviation, source freshness), then a trend panel per KPI
where the shaded band is that metric's *own* alert threshold — a red dot outside the band
is literally why it was flagged. Dotted line = 3-month OLS forecast. Every metric has a
**details** popover with a plain-English read, its normal range, source and freshness.
Zero LLM tokens are spent on this page.

**Live Feed** — replays the real event stream in accelerated time (▶ Play, adjustable
speed). Orders, shipments, SLA breaches, complaints and churn land day by day in a live
ticker; three **dimensional monitors** evaluate a rolling 7-day window against each
region's own 60-day baseline, using the same z-rule as the batch signal gate. Watch the
WH-07 incident get caught as it happens: **Fulfilment SLA breaches in North-West around
28–30 June**, complaints follow around **12 July** — cause first, symptom after. When a
monitor breaches, an alert fires and one click hands off into a full investigation.

**Data** — a Redash-style explorer over the governed sources: source picker, grain,
time-range slider, live volume chart, row counts and **query time in milliseconds**, the
**SQL that just ran** (with the RBAC clause visible), and the latest raw records with
sensitive columns masked per role.

**Investigation** — ask in plain English ("why did revenue fall in July?") or pick a KPI.
You get a verdict row (trend chart + confidence gauge with both gates drawn as
thresholds), **ranked explanatory drivers** as bars, a contribution **waterfall**, action
cards carrying **lever → owner → who must approve → expected impact → monitoring**, a
"what could change this answer" note, and a full audit trail: the three-detector ensemble,
the executed SQL, driver statistics, retrieved evidence, and matched external events.

**Decision Ledger** — every investigation, conclusion, confidence score and user
correction. Past-period entries feed back into Level 2 retrieval, so the engine recalls
precedent (the "Recall" step) and learns from 👍/👎 feedback.

**Under the Hood** — the LLM vs non-LLM breakdown *and why* for each step, live telemetry
(latency, tokens, cost per insight), the semantic contract, and the active security model.

**Anywhere** — switch persona (CEO / Data Analyst / Sales Head), move the analysis window
across 6 months, toggle dark/light.

---

## Method mix : what does what

| Job | Method | Why not the LLM |
|---|---|---|
| KPI series, contributions, breakdowns | **SQL** (DuckDB, from the contract) | numbers must be reproducible and auditable |
| "Is this abnormal?" | **statistics** — z-score + materiality | a threshold is a business decision, not a guess |
| Second opinion on abnormality | **regression** — OLS forecast, 90% interval | independent of the first test |
| Day-level anomaly cross-check | **machine learning** — IsolationForest ×5 regions | catches shifts monthly aggregates smooth over |
| Driver testing, ranking, confidence, gates | **statistics + fixed formulas** | scores must not drift run to run |
| Evidence retrieval | **weighted keyword ranking** | transparent and stable |
| Reading documents → mapping evidence | **LLM (Haiku 4.5)** | language comprehension is the model's job |
| Persona narrative, action wording, briefs | **LLM (Sonnet 5)** | writing is the model's job |

---

## Planted scenarios (July 2026)

The dataset is seeded, so these reproduce exactly on any machine.

| Scenario | Outcome | Requirement it proves |
|---|---|---|
| Revenue −7% (≈ −₹25.9L/mo): WH-07 conveyor failure → SLA collapse → 2 enterprise churns → competitor's express launch | **actions @ 0.83** | multi-factor movement with traceable drivers |
| Fulfilment SLA 92% → 88.3% | **actions @ 0.82** | operational root cause from unstructured evidence |
| Complaint rate +29% | **actions @ 0.99** | downstream effect correctly attributed |
| Marketing conversion −16%, but spend and traffic healthy (planted tracking bug) | **abstains @ 0.35** | low-confidence abstention + clarifying question + escalation brief |
| Home-decor category, 6 weeks old | **sparse guard** | new-KPI handling, widened uncertainty, 0 tokens |
| AOV −3.5% | **not flagged** | noise rejection / alert fatigue |
| CEO masking · Sales-Head region filter · hidden KPIs | — | row + column + domain security |

Switching the analysis window to **May 2026** shows a clean month — proof the engine
recomputes rather than replaying a canned story.

---

## Repo map

```
app.py                       Streamlit UI (5 pages, theming, charts)
contracts/kpi_contract.yaml  Semantic contract — executed by the engine
roles.yaml                   Row / column / domain security model
engine/
  pyramid.py                 orchestrator: 4 levels, gates, narrative sanitizer
  anomaly.py                 z-score + materiality + forecast check
  stats_ml.py                OLS prediction interval, Pearson, IsolationForest
  contribution.py            dimension deltas and shares
  drivers.py                 contract-declared driver testing
  confidence.py              weighted score + gate thresholds
  retrieve.py                document + ledger retrieval
  db.py                      DuckDB access, RBAC, masking, freshness
llm/
  client.py                  live / fixture / fallback modes
  prompts.py                 system prompts and builders
  fallback.py                deterministic templates (no key, no fixture)
  fixtures/                  committed offline responses
data/generate_data.py        seeded generator + planted scenarios
telemetry.py                 latency / tokens / cost per call and per run
feedback.py                  decision ledger + feedback loop
smoke_test.py                engine scenario verification
ui_test.py                   11 headless UI checks
PROJECT_REPORT.md            full write-up (architecture, metrics, coverage)
DEMO_SCRIPT.md               judge walkthrough
```

---

## Does it actually work? (evaluation)

The generator plants known causes, so there is ground truth to score against —
an incident month plus **three control months where nothing was planted**, so any
flag there is a genuine false positive.

```bash
python eval.py     # offline, ~1 min; writes data/state/eval_results.json
```

Current results (also rendered in the app under **Under the Hood → "Does it actually
get the right answer?"**):

| Measure | Result |
|---|---|
| Detection | **recall 100%**, precision 83% (TP 5 · FP 1 · FN 0 · TN 18) |
| Root cause | **4 / 4** planted causes correctly identified |
| Abstention | **1 / 1** correct, **0** false abstentions |
| False alarms | 1 **contained** by the evidence gate · **0** produced a wrong conclusion |
| Overall | **96%** across 24 scored cases |
| Calibration | ≥0.75 band: 100% accurate · <0.60 band: 95% |

The single false positive is worth reading, not hiding: in April a complaint-rate blip
cleared the signal gate (z = 2.08 against a 2.0 threshold), the engine investigated,
found no supporting evidence, and **abstained instead of inventing a cause**. That is
the gated architecture doing its job — a false alarm cost some attention, not a wrong
decision.

This validates the engine's *logic* against synthetic ground truth. Real-world accuracy
would need a client's labelled incident history.

## Optional : Prometheus + Grafana observability

The engine exposes its **own operational metrics** (not business KPIs — those are
analytical, and belong in the app) at `http://localhost:9108/metrics`: investigations
run, outcomes, gate pass/fail, detector votes, confidence distribution, deterministic
operations by kind, LLM calls, tokens, cost and latency.

```bash
cd ops
docker compose up -d
# Grafana    http://localhost:3000   (anonymous; dashboard pre-provisioned)
# Prometheus http://localhost:9090
```

The pre-built **"Rationale.AI : Engine Operations"** dashboard shows throughput and
outcome mix, p50/p95 investigation latency, LLM latency by model, spend, and a panel
comparing **deterministic operations against LLM calls** — the core design claim,
measured live rather than asserted.

This is entirely optional: the app never depends on it, and runs identically if the
stack (or `prometheus_client`) is absent. Disable the endpoint with
`RATIONALE_METRICS=0`, or move it with `RATIONALE_METRICS_PORT`.

## Deploy it (free, ~10 minutes)

The app is deploy-ready: it generates its dataset on first boot, runs offline with no
API key, and degrades gracefully when the optional observability stack is absent.

**Streamlit Community Cloud**

1. Sign in at [share.streamlit.io](https://share.streamlit.io) with GitHub.
2. **New app** → repo `diyasharma05/rationale-ai`, branch `main`, file `app.py`.
3. Deploy. First boot takes ~1 minute while the synthetic dataset is generated.

No secrets are required — visitors get the offline demo, and anyone who wants live
Claude narratives can paste their own key in the sidebar (held in memory, never stored).
To run the hosted app in live mode instead, add `ANTHROPIC_API_KEY` under
**App settings → Secrets** (this bills your account for every visitor).

**Anywhere else** (Render, Fly.io, a VM, Docker):

```bash
pip install -r requirements.txt
python data/generate_data.py
streamlit run app.py --server.port $PORT --server.address 0.0.0.0
```

## Verify the install

```bash
python smoke_test.py   # engine: every planted scenario produces its expected outcome
python ui_test.py      # 11 headless UI checks (mock mode, no key needed)
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `streamlit` not found | the virtual environment isn't activated (step 2) |
| `Activate.ps1` blocked on Windows | `Set-ExecutionPolicy -Scope Process RemoteSigned`, then retry |
| Port 8501 already in use | `streamlit run app.py --server.port 8502` |
| No data / empty charts | run `python data/generate_data.py` (step 4) |
| Code edits don't appear | fully restart (`Ctrl+C`, rerun) — Streamlit caches imported modules |

---

## Roadmap

Predictive "what-if" mode · embedding-based retrieval · real ERP connectors ·
expert-network integration · STL deseasonalization · causal-graph inference ·
multi-tenant deployment.
