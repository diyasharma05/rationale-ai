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
> and at most **2 LLM calls**, both of which only write sentences. (Investigations
> that stop at the signal or sparse gate make none at all — the measured mean
> across the evaluation set is 0.28.)

---

## Round 3 — what changed, and why

Round 2 placed nationally. Round 3 was spent making every claim on screen
survive a hostile question, and making the deployment story something you can
run rather than something on a slide.

**Statistical honesty.** Testing seven KPIs a month at a 2-sigma bar produces a
false alarm roughly one month in four, purely from testing seven things. The
engine now applies Benjamini-Hochberg across the whole portfolio
(`engine/screening.py`). Detection precision went from **83% to 100%** with
recall unchanged at 100% — the rigorous method scored better than the loose one.
Small-sample tests use a t-distribution against the prediction standard error,
because at n≈11 reading |z|≥2 as p=0.046 overstates significance by roughly 4x.

**Confidence that cannot claim certainty.** The old score reached exactly
`1.000`. Ratios are now Laplace-smoothed, a KPI with no declared drivers is
scored as *unassessable* rather than given half marks, and the result is
discounted by how much of the evidence could actually be checked. Nothing
exceeds 0.84 anywhere across three roles and six months. The headline revenue
case now lands at **TENTATIVE**, not ACTIONS — its own signal is marginal
(p≈0.07) and the conviction comes from its drivers.

**Co-movement, not causation.** A driver that moved is now described as having
moved *with* the KPI, as the contract predicts. A driver that moved but that
nothing upstream explains is flagged `unexplained` and counts for half — which
is how the planted marketing tracking bug, the largest mover of the four, stops
corroborating the revenue drop and drops to last place.

**The learning loop is real.** An upvote and a downvote used to score
identically. A correction now demotes the explanation it rejects, and a
conclusion a human marked wrong is dropped from the evidence pool.

**It closes the last mile.** A conclusion becomes a message to the person the
*contract* names as the lever's owner, carrying the approval the contract
requires — the model writes the sentence but never chooses the recipient, the
same rule as the numbers one layer up. Nothing sends without a human approving
it in the Outbox; TENTATIVE verdicts go out marked *for review*; an abstention
becomes an escalation asking a specific question; no-signal produces silence.
Delivery is a dry run by default, with an MCP transport behind the same
interface so it plugs into whatever the client already runs.

**It deploys.** `docker compose up` brings up the app, the same engine behind a
FastAPI service, Prometheus and Grafana. RBAC is enforced at the API boundary,
not just in the UI. `ops/bench.py` measures the concurrency curve: ~8-9 req/s on
one process with zero wrong answers under contention, which is the honest
"add replicas past here" answer.

**It estimates one causal effect, where the data can identify one.** Difference-in-
differences on the regional panel: the regions in focus against the rest, the three months
before against the analysis month, with a bootstrap interval, a pre-period placebo check
and the permutation floor stated. For July revenue the North-West shock is about −₹0.7 lakh
a day, roughly 82% of the month's movement. For the national tracking bug it says "not
identifiable" rather than fitting something. The confidence score does not use it. The
contract is also drawn and walked as a knowledge graph (exposure: who else a movement
touches), every chart carries a forecast band with R² stated, and `python -m ops.watch`
drafts alerts into the Outbox proactively without ever sending one.

**Its sources are heterogeneous, and it says which it read.** The order system is a
live PostgreSQL database fetched over the wire at start-up (falling back, visibly, to
the last nightly extract when unreachable); the warehouse and marketing systems drop
CSV extracts; the CRM exports events as JSON lines. `engine/sources.py` reconciles them
into one governed namespace and records the provenance of every table, which the
Lineage page and `GET /sources` show. `docs/REQUIREMENTS_MAP.md` walks the brief's
seven pointers one by one.

**It is custom where it reasons and hybrid where it lands.** Any SQLAlchemy warehouse
URL works as a live source (`kind: sql`) or as the engine the contract SQL runs on
(`RATIONALE_DB`), proven against PostgreSQL and SQLite; the vendor URLs for Snowflake,
Databricks, Fabric and BigQuery are documented in `docs/PLATFORMS.md`. For Snowflake and
Databricks the drivers are installed, the dialect differences are handled, and
`python -m ops.warehouse smoke | load | verify` loads the sources and proves the contract
SQL there against DuckDB; the vendor run itself waits on an account and is marked so.
`python -m ops.export_bi` writes every output as CSV and Parquet for Tableau, Power BI,
Looker or Qlik, and the API serves the same as JSON.

**It runs on PostgreSQL too.** One variable, `RATIONALE_DB`, points the engine at a
PostgreSQL database instead of the in-process DuckDB: the same contract SQL, the same
RBAC clause, and the ledger and outbox as one shared append-only table with an
INSERT-only application role. A parity suite asserts every KPI series and all 36
evaluation verdicts are identical on both engines. `python -m ops.pg_local init` runs
PostgreSQL as a plain user process — no Docker, no service, no admin rights.

**It is tested.** 241 tests where there were effectively none:
`smoke_test.py` printed everything and asserted nothing. The accuracy harness is
mutation-tested — seed a wrong expected driver and root-cause accuracy drops
4/4 → 3/4 — and 15 render snapshots gated a refactor that took `app.py` from
1654 lines to 192.

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

# 4. (The seeded dataset ships with the repo, so there is no build step.
#     To rebuild it from scratch — it is deterministic — run:)
#     python data/generate_data.py

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

### Optional: run it on PostgreSQL (no Docker, no admin rights)

```bash
python -m ops.pg_local fetch     # portable PostgreSQL 16 binaries (~320 MB, once, to ~/pgsql16)
python -m ops.pg_local init      # start it as a user process on :5433, load the CSVs, create roles
python -m ops.pg_local env       # prints two options for your shell:
#   RATIONALE_DB=...      run the whole engine on PostgreSQL (the Lineage page and /healthz say so)
#   RATIONALE_OMS_DSN=... keep DuckDB, but fetch the order system LIVE from PostgreSQL at start-up
streamlit run app.py             # same app either way; the Lineage page shows what was read from where
python eval.py                   # same 36 verdicts
python -m ops.pg_local stop      # when done
```

DuckDB remains the default and the tests run without a database. The application
connects as `rationale_app`, which can SELECT and INSERT and nothing else, so the ledger
is append-only by grant; `python -m ops.pg_local reset-ledger` is the operator reset.

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
data/generate_data.py        seeded generator + planted scenarios (CSV extracts + a JSON event feed)
engine/sources.py            heterogeneous source loaders (PostgreSQL live / CSV / JSON lines) + provenance
engine/causal.py             difference-in-differences on the regional panel (identifiable or says why not)
engine/graph.py              the contract as a knowledge graph: build, downstream, exposure
engine/forecast.py           the OLS forecast band, in words, with R² stated
ops/watch.py                 proactive watcher: scans, drafts into the Outbox, never sends
ops/export_bi.py             BI hand-off: scan, series, verdicts, provenance, graph as CSV + Parquet
ops/warehouse.py             load the sources into Snowflake / Databricks / any SQLAlchemy warehouse and verify parity
requirements-warehouse.txt   optional vendor drivers (snowflake-sqlalchemy, databricks-sqlalchemy, pyodbc)
docs/PLATFORMS.md            the platform seams: what is proven against what, and the vendor URLs
telemetry.py                 latency / tokens / cost per call and per run
feedback.py                  decision ledger + feedback loop
store.py                     event streams: JSONL by default, PostgreSQL via RATIONALE_DB
tests/                       241 tests: unit, RBAC, integration, UI snapshots, PostgreSQL parity
ops/bench.py                 latency + concurrency benchmark
ops/pg_local.py              run the same contract on PostgreSQL without Docker
PROJECT_REPORT.md            full write-up (architecture, metrics, coverage)
docs/REQUIREMENTS_MAP.md     the brief's seven pointers -> code, tests, gaps
DEMO_SCRIPT.md               judge walkthrough
docs/PRODUCT_GUIDE.md        the complete product + technology guide (start here)
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

## Optional : Prometheus + Grafana observability (parked, opt-in)

The engine can expose its **own operational metrics** (not business KPIs — those are
analytical, and belong in the app): investigations run, outcomes, gate pass/fail,
detector votes, confidence distribution, deterministic operations by kind, LLM calls,
tokens, cost and latency. **This layer is off by default** so the app runs as a single
process with no extra services or ports. To enable it:

```bash
# terminal 1 : run the app with the metrics endpoint on :9108
RATIONALE_METRICS=1 streamlit run app.py     # PowerShell: $env:RATIONALE_METRICS="1"

# terminal 2 : the scrape/visualisation stack
cd ops
docker compose up -d
# Grafana    http://localhost:3000   (anonymous; dashboard pre-provisioned)
# Prometheus http://localhost:9090
docker compose down                          # stop it again
```

The pre-built **"Rationale.AI : Engine Operations"** dashboard shows throughput and
outcome mix, p50/p95 investigation latency, LLM latency by model, spend, and a panel
comparing **deterministic operations against LLM calls** — the core design claim,
measured live rather than asserted.

This is entirely optional: the app never depends on it, and runs identically if the
stack (or `prometheus_client`) is absent. Disable the endpoint with
`RATIONALE_METRICS=0`, or move it with `RATIONALE_METRICS_PORT`.

## Deploy it (free, ~10 minutes)

The app is deploy-ready: the dataset is committed (generation is only a fallback), it runs offline with no
API key, and degrades gracefully when the optional observability stack is absent.

**Streamlit Community Cloud**

1. Sign in at [share.streamlit.io](https://share.streamlit.io) with GitHub.
2. **New app** → repo `diyasharma05/rationale-ai`, branch `main`, file `app.py`.
3. Deploy. The dataset is committed, so there is no build step.

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
python -m pytest       # 179 tests: engine invariants, RBAC, the five planted scenarios, UI snapshots
python eval.py --check # accuracy harness against planted ground truth (CI gate)
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
