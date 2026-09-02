# Rationale.AI — Technical Documentation

**Team Rational.ai · Accenture Innovation Challenge 2026 · Round 2 · Track 3 (BusinessIntelligence.ai)**
Complete implementation reference: every component, algorithm, threshold, metric and design decision.

---

## Contents

1. [What this is](#1-what-this-is)
2. [Architecture](#2-architecture)
3. [The data layer](#3-the-data-layer)
4. [The semantic contract](#4-the-semantic-contract)
5. [The analytical engine, module by module](#5-the-analytical-engine-module-by-module)
6. [The investigation workflow (the pyramid)](#6-the-investigation-workflow-the-pyramid)
7. [The LLM layer](#7-the-llm-layer)
8. [Security model](#8-security-model)
9. [The user interface](#9-the-user-interface)
10. [Live Feed : streaming replay](#10-live-feed--streaming-replay)
11. [Observability : Prometheus + Grafana](#11-observability--prometheus--grafana)
12. [Evaluation : measured accuracy](#12-evaluation--measured-accuracy)
13. [Testing](#13-testing)
14. [Cost, latency and scalability](#14-cost-latency-and-scalability)
15. [Deployment](#15-deployment)
16. [Engineering decisions and bugs we fixed](#16-engineering-decisions-and-bugs-we-fixed)
17. [Repository map](#17-repository-map)
18. [Known limitations and roadmap](#18-known-limitations-and-roadmap)

---

## 1. What this is

A **KPI intelligence-to-action engine**. Given governed business KPIs across heterogeneous
sources, it: detects material movements, explains *why* they happened with cited evidence,
quantifies its own confidence, recommends actions tied to owners and decision rights — and
**abstains and escalates to a human** when the evidence doesn't support a conclusion.

**The governing design rule: the LLM never computes a number.** All quantities come from
SQL, statistics and machine learning; the language model reads documents and writes
sentences over precomputed facts. A typical investigation performs **~18 SQL queries,
~10 statistical tests, 5 ML model evaluations, 6 document retrievals — and exactly
2 LLM calls.** The per-run mix is displayed on every result.

## 2. Architecture

```
 STRUCTURED SOURCES (4 tables, 3 systems)          UNSTRUCTURED CONTEXT
 OrderDB/OMS      : transactions (daily refresh)   10 documents: tickets, an
 LogiTrack/WMS    : daily × region                 exit-call transcript, ops
 RelateCRM        : events (weekly sync)           notes, a Slack thread, a past
 RelateCRM mktg   : weekly × region                postmortem, 2 red herrings
        │                                                   │
        │ DuckDB · SQL comes from the semantic contract     │
        │ row/column/domain security injected per role      │
        ▼                                                   │
 LEVEL 1 · CROSS-FUNCTIONAL SIGNALS (non-LLM)               │
   detector ensemble: z-score · OLS 90% PI · IsolationForest│
   contribution by region/segment/category                  │
   driver checks + 12-month co-movement                     │
 ── SIGNAL GATE : statistical AND business materiality ──   │
        ▼ (fails → stop, 0 tokens spent)                    │
 LEVEL 2 · COMPANY CONTEXT ◀────────────────────────────────┘
   retrieval ranking (non-LLM) ◀── decision ledger (past runs + corrections)
   evidence→hypothesis mapping (LLM, Haiku) — counted in Python
        ▼
 LEVEL 3 · EXTERNAL SIGNALS (non-LLM) ◀── market-event feed
 ── EVIDENCE GATE ≥ 0.60 · ACTION GATE ≥ 0.75 ──
        ▼ (below either → LEVEL 4: abstain + clarifying question + expert brief)
 NARRATIVE LAYER (LLM, Sonnet) : persona prose over verbatim numbers,
   deterministic de-slop sanitizer, offline fixtures + template fallback
        ▼
 STREAMLIT UI : Dashboard · Live Feed · Data · Investigation · Ledger · Under the Hood
   + /metrics on :9108 → Prometheus → Grafana (embedded back into the app)
```

Key property: every box above the narrative layer is deterministic and auditable. The two
LLM touchpoints (evidence mapping, prose) are consumers of computed facts, never producers
of them.

## 3. The data layer

**Generator** (`data/generate_data.py`): fully seeded (`numpy default_rng(42)`), so every
machine produces byte-identical data. **85,222 orders** over 13 months (Aug 2025 – Aug 25
2026), 5 regions, 3 segments (consumer/SMB/enterprise), 40 named enterprise accounts.
The dataset (~5 MB) ships with the repo so `clone → run` has no build step.

| Table | Grain | Refresh (simulated) | Contents |
|---|---|---|---|
| `sales_orders` | transaction | daily 02:00 | order id, date, region, segment, category, account, value |
| `ops_fulfilment` | daily × region | daily 04:00 | shipments, avg delivery days, SLA breaches |
| `crm_events` | event | weekly (Mon) | complaints (row each), churn events, monthly NPS |
| `marketing_weekly` | weekly × region | weekly (Mon) | spend, sessions, conversions |

**The planted July-2026 incident** (exact parameters):

- 2026-06-25: WH-07 conveyor fails → NW SLA breach probability 8% → 20%, delivery days 2.6 → 3.5
- 2026-07-01 onward: NW consumer/SMB order volume ×0.90; remaining NW enterprise ordering ×0.70
- Meridian Retail Group and Kalinga Mart stop ordering July 1 (churn logged in CRM Jul 8 / Jul 19)
- NW complaint rate ×2.5 (base 1.2% of orders)
- Competitor "SwiftKart" express-delivery launch in the market-event feed (Jul 1)
- **Tracking-bug scenario**: from Jul 1, marketing sessions ×1.05 and spend ×1.08 but
  conversions ×0.84 — a drop nothing upstream explains (abstention test)
- **Sparse scenario**: `home-decor` category launches 2026-07-15 (no baseline)
- Revenue KPIs are defined as **daily run-rates** (sum ÷ distinct days) because calendar
  month length (28–31 days) otherwise injects ±4% noise that drowned a −5% signal (measured:
  z fell from −4.5 expected to −1.21 before this fix)

**What the detectors measure in July** (reproducible): revenue −7.0% (z −2.16), SLA 92→88.3%
(z −9.75), complaints +29.0% (z +2.96), enterprise accounts 40→37 (z −6.97), conversion
−15.7% (z −26.7), AOV −3.5% (z −0.82, deliberately below its gate).

## 4. The semantic contract

`contracts/kpi_contract.yaml` is **executed, not documentation** — the engine reads it at
runtime. Per KPI:

| Field | Used by |
|---|---|
| `sql` (with `{where}` RBAC injection point) | every series query |
| `dim_sql`, `dimensions` | contribution analysis |
| `materiality: {min_abs_z, min_pct}` | the signal gate (per-KPI thresholds — AOV runs a higher bar) |
| `drivers: [{kpi/metric, relation, note}]` | driver checks; `relation: direct/inverse` sets expected sign |
| `levers: [{lever, owner, approval}]` | action grounding + decision rights |
| `access: [roles]` | domain-level security |
| `good_direction`, `dim_unit`, `ml_daily_check`, `min_history` | chart polarity, contribution units, IsolationForest opt-in, sparse guard |
| `lineage`, `owner`, `tags` | provenance display, retrieval query terms |

7 governed KPIs: revenue, AOV, fulfilment SLA, complaint rate, enterprise active accounts,
marketing conversion, home-decor revenue.

## 5. The analytical engine, module by module

### `engine/anomaly.py` — detector 1 (statistics)
z = (current − mean(history)) / std(history), history = all complete months before the
analysis month (≥ `min_history`, default 6). Material only if `|z| ≥ min_abs_z` **and**
`|Δ%| vs trailing-3-month avg ≥ min_pct` — statistical *and* business materiality.
Degenerate guard: a near-constant history caps z at ±9.99 (before this, a constant series
of 19 accounts produced z = −157,894 in a role-filtered view).

### `engine/stats_ml.py` — detectors 2 & 3 + co-movement
- **OLS forecast interval**: fit y = b0 + b1·t; 90% two-sided prediction interval
  `ŷ ± t₀.₉₅,ₙ₋₂ · s·√(1 + 1/n + (x−x̄)²/Sxx)`. Flag if the actual falls outside.
  Residual scale floored like the z-detector. Empirical coverage verified at **89–90%
  over 2,000 seeded simulations** by an adversarial review. Also renders the dotted
  3-month forecast on every trend chart.
- **IsolationForest** (scikit-learn, 200 trees, contamination 3%, seeded): one model **per
  region**, trained on the trailing year of daily data, scoring the analysis month.
  Features are the **7-day smoothed level** and its **ratio to the 90-day level** — raw
  daily revenue is too noisy (±20% from lumpy enterprise orders) for per-day outliers to
  expose a 15% regional shift; smoothing reduces noise ~√7 while the shift persists.
  Decision rule: worst region with >10% of days anomalous. On July it flags and
  **independently localizes to North-West** (4/31 days).
- **Pearson co-movement**: r of month-over-month % changes between each driver and its
  KPI, over 12 months *including* the analysis month — labelled a **descriptive
  co-movement statistic, never independent corroboration** (with ~12 points, one shared
  anomalous month can move r from −0.20 to +0.95; the evidence gate does the actual
  corroborating). Missing months are reindexed so cross-gap deltas never masquerade as
  month-over-month changes.

### `engine/contribution.py`
Per contract dimension: current month vs the mean of the prior 3 months per member;
delta and share-of-delta. July result: **North-West = 86% of the revenue movement**.
Focus regions (share ≥ 35%) steer retrieval and the IsolationForest narrative.

### `engine/drivers.py`
For each declared driver: same-period z (threshold 1.5) classified as **consistent**
(moved the direction that would explain the KPI), **contradicts** (moved the wrong way —
actively reduces confidence), or **quiet**, plus the co-movement r.

### `engine/confidence.py`
```
score = 0.35·signal + 0.35·coverage + 0.30·evidence
signal   = min(|z|/3, 1)                       # |z| ≥ 3 = fully established
coverage = consistent/declared − 0.25·contradicting   (0.5 neutral if no drivers)
evidence = corroborated hypotheses / all hypotheses
sparse history caps the score at 0.40
```
Gates: **evidence ≥ 0.60** to state a cause, **action ≥ 0.75** to recommend actions.
The arithmetic is fixed Python — never model output.

### `engine/retrieve.py`
Weighted keyword TF ranking over the 10 documents **plus the decision ledger** (region
terms ×2). Same-period ledger entries are excluded (recall = *past* precedent only; this
prevents echo chambers where one investigation's conclusion feeds a sibling's evidence).

### Hypothesis ranking
strength = 0.5·min(|z|/4,1) + 0.3·min(docs/3,1) + 0.2·(external event) — computed, and
rendered as the ranked-driver bars.

## 6. The investigation workflow (the pyramid)

`engine/pyramid.py::investigate(kpi, period, role, llm)` — one call, fully parameterized:

1. **Level 1**: contract SQL (RBAC clause visible in the UI) → detector ensemble → signal
   gate. Not material → outcome `no_signal`, **0 LLM tokens**. Sparse → outcome `sparse`,
   widened bands, 0 tokens. Otherwise → contribution + driver checks → hypotheses.
2. **Level 2**: retrieval → Haiku maps snippets→hypotheses (strict JSON). The mapping is
   **counted** in Python. Rules discovered the hard way: the LLM's new hypothesis is
   admitted **only for KPIs with no declared drivers** (the hallucination guard — an
   unstructured anecdote must not rescue confidence when structured drivers stayed
   quiet; a blocked proposal is displayed as an *unvalidated lead*); unknown/absent
   support ids resolve to the admitted new hypothesis instead of being dropped.
3. **Level 3**: market events matched by region + tag overlap; corroborates or adds an
   external hypothesis. Early exit if confidence ≥ 0.90 after Level 2.
4. **Gates → outcome**: `actions` (≥.75) / `tentative` (.60–.75, actions reframed as
   "low-regret steps while confirming") / `abstain` (<.60 → Level 4: clarifying question +
   ready-to-send expert escalation brief).
5. **Narrative** (Sonnet, effort=low): persona-specific JSON over verbatim numbers, then the
   **deterministic sanitizer** (§7). Every answer includes *"what could change this answer"*.
6. Ledger append, Prometheus mirror, method-mix accounting, wall-time stamp.

July outcomes: revenue **actions @ 0.83** (0.93 for the region-filtered Sales Head), SLA
actions @ 0.82, complaints @ 0.99, enterprise @ 1.00, marketing **abstains @ 0.35**.

## 7. The LLM layer

| Task | Model | Price | Config |
|---|---|---|---|
| Evidence mapping | `claude-haiku-4-5` | $1/$5 per MTok | max 1,500 tok |
| Narrative / briefs | `claude-sonnet-5` | $2/$10 per MTok | max 8,000 tok, `effort=low` |

**Three modes** (`llm/client.py`): **live** (key present), **fixture** (committed JSON in
`llm/fixtures/` — the offline demo), **fallback** (deterministic heuristic mapping +
template narrative). The demo therefore cannot hard-fail. A key pasted in-app is held in
process memory only. **Only `record_fixtures.py` may write fixtures** (guarded by an env
flag) — added after a live session with a stale prompt overwrote curated fixtures.

**Prompt rules**: ≤4 sentences of ≤25 words, one number per sentence, only [E#] citations
(one per sentence, no chains), no hypothesis ids, no engine/statistics vocabulary, action
fields ≤12 words. **The sanitizer enforces this in code** regardless of model behaviour:
drops any sentence containing banned tokens (`z=`, `share_of_delta`, `evidence_gate`,
`correlat`…), caps lengths, collapses citation chains, strips ids from action fields.
Slop is structurally impossible, not just discouraged.

## 8. Security model

All three layers enforced in the query/engine layer, never just the UI:

| Layer | Mechanism | Demonstration |
|---|---|---|
| Row | `{where}` clause injected into **every** SQL (KPIs, drivers, contributions, data explorer, live feed) | Sales Head sees only North/North-West; the clause is visible in the displayed SQL |
| Column | enterprise account names → stable `ACCT-xxxx` codes, applied to evidence **and LLM prompts** | CEO never sees "Meridian Retail Group", even in raw-record views |
| Domain | per-KPI `access` lists | Sales Head sees 4 of 7 KPIs |

Personas (Analyst / CEO / Sales Head) also change narrative style and UI depth — the CEO
sees no z-scores anywhere.

## 9. The user interface

Five pages. Charts follow a validated design-system method (contrast ratios computed, not
eyeballed; status colors never themed; one axis per chart; direct labels).

- **Dashboard** — severity-ordered triage: 4 overview stat tiles, per-KPI trend panels where
  the shaded band is *that KPI's own* contract threshold (a red dot outside the band **is**
  the flag explanation), dotted 3-month OLS forecast, clickable detail popovers with a
  templated plain-English sentence, source freshness and normal range. **0 LLM tokens.**
  Header shows live compute time (~250 ms for 7 KPIs across 3 systems).
- **Investigation** — plain-English ask box (keyword intent, Haiku fallback live);
  verdict row (banded trend + confidence bullet-gauge with both gates drawn); ranked-driver
  bars; contribution waterfall (additive KPIs) or polarity-aware bars; "in plain words" card
  with citation popovers; action cards (lever → owner → **approver** → impact → monitoring);
  audit trail with detector verdict tiles, gate bullet bars, the executed SQL, evidence cards
  and matched events; per-run telemetry.
- **Data** — Redash-style explorer: source/grain/time-range, live volume chart, query time
  in ms, the executed SQL with the RBAC clause, latest 50 rows masked per role.
- **Decision Ledger** — every conclusion + 👍/👎 corrections; feeds Level-2 recall.
- **Under the Hood** — LLM vs non-LLM table with the *why*, evaluation results, cumulative
  telemetry, the contract viewer, the active security posture.

**Theming**: Accenture brand (light = white + `#A100FF`; dark = near-black + `#B455F0`),
runtime dark/light toggle (config swap + CSS shell, no reload), all pairs verified
≥4.5:1 text / ≥3:1 graphics. A 20-agent adversarial audit found and fixed 10 light-mode
defects (worst: amber text at 1.7:1; a body-level dropdown portal escaping the theme).
**Typography**: Inter type system (tight-tracked heading scale 1.72→1.0rem, 0.94rem body
at 1.62 line-height, tabular numerals on all hero figures), JetBrains Mono for SQL —
applied to charts and tooltips too, replacing all Streamlit defaults.

## 10. Live Feed : streaming replay

`engine/stream.py` replays the seeded history as an accelerated stream (window
2026-06-18 → 07-31, opening a week before the incident), with Play/Pause/speed and an
auto-refreshing fragment (~1s ticks).

- **Event ticker**: real rows (enterprise orders, SLA breach counts, complaints, churn),
  masked per role.
- **Dimensional monitors**: per metric, per **region** — rolling 7-day mean vs that
  region's own 60-day pre-replay baseline, ±2σ rule (the same z-logic as the batch gate).
  Monitoring is per-region *deliberately*: nationally the incident never crosses ±2σ —
  exactly how a regional failure hides in a company-wide dashboard.
- **The scripted arc (measured)**: monitors normal through ~June 27 → **Fulfilment SLA
  breaches in North-West ~June 28–30 (z −3.9, deepening to −5.6)** → **complaints breach
  ~July 12 (z +2.4)** — cause first, symptom after. Toast + banner on each breach, and
  a one-click **"Investigate this now"** handoff into the pyramid.
- Second tab embeds the live Grafana panels (§11).

## 11. Observability : Prometheus + Grafana

`metrics.py` exposes **engine telemetry** (deliberately *not* business KPIs — those are
analytical and belong in the app; Prometheus is for how the *service* behaves) at
`:9108/metrics`: investigations by kpi/outcome/role, wall-time and confidence histograms,
gate outcomes, detector votes, deterministic ops by kind (sql/stats/ml/retrieval), LLM
calls/tokens/cost/latency by model, KPIs scanned/flagged. Everything no-ops if
`prometheus_client` is absent — the app never depends on it.

`ops/docker-compose.yml`: Prometheus (5s scrape) + Grafana (anonymous, embedding enabled,
pre-provisioned datasource and dashboard). The **"Engine Operations"** dashboard: outcome
mix, p50/p95 latency, spend, detector votes, confidence distribution, and the headline
panel — **deterministic work vs LLM calls, the core design claim measured live**.
**Status: parked/opt-in** — the layer is off by default so the demo runs as a single
process (enable with `RATIONALE_METRICS=1` + `docker compose up -d` in `ops/`); the in-app
telemetry pages (Under the Hood, per-run panels) are independent of it and always on.
Counters are per-process and reset on restart.

## 12. Evaluation : measured accuracy

`eval.py` scores the engine against the planted ground truth: the incident month **plus
three control months (Mar–May) where any flag is a genuine false positive**. June is
excluded as ambiguous (the failure starts June 25). Results render in-app under
Under the Hood.

| Measure | Result |
|---|---|
| Detection (signal gate) | **recall 100%, precision 83%, F1 0.91** (TP 5 · FP 1 · FN 0 · TN 18) |
| Sparse handling | 4/4 correct |
| Root cause | **4/4** planted causes identified by the top-ranked driver/narrative |
| Abstention | **1/1** correct · 0 false abstentions |
| False-alarm impact | 1 **contained** · **0 produced a wrong conclusion** |
| Overall | **96%** across 24 scored cases |
| Calibration | ≥0.75 band → 100% accurate (mean conf 0.91) · <0.60 band → 95% |
| Runtime | median ~65 ms/investigation offline · 0.42 LLM calls avg (deterministic paths spend zero) |

The single false positive is the architecture's best argument: an April complaint blip
cleared the signal gate at z = 2.08 (threshold 2.0), the engine investigated, found **no
evidence, and abstained** — a false alarm cost attention, not a wrong decision. Honest
scope note: this validates the engine's logic against synthetic truth; real-world accuracy
needs a client's labelled history.

## 13. Testing

- `ui_test.py` — **11 headless groups** (Streamlit AppTest, mock mode): dashboard, golden
  path (actions + ranking + decision rights + what-could-change), ask-box intent, a
  **crash-regression sweep over every investigable KPI** (added after a driverless-KPI
  crash escaped the suite), abstain, sparse, CEO masking, Sales-Head domain/row security,
  Data explorer, period-picker recompute (May = clean month), Live Feed play/reset.
- `smoke_test.py` — engine end-to-end on all planted scenarios.
- `eval.py` — the accuracy harness (§12).
- **Adversarial multi-agent reviews** during development: light-mode audit (20 agents →
  10 confirmed defects, 5 rejected as nitpicks after recomputation), statistics/ML
  verification (2,000-simulation PI coverage check → 6 defects), investigation-layer
  review (16 findings incl. a crash and an evidence-mapping bug). All fixed and
  regression-tested.

## 14. Cost, latency and scalability

| Metric | Value |
|---|---|
| LLM calls per full investigation | 2 (Haiku mapping + Sonnet narrative) |
| Cost per insight (live) | ≈ ₹1–3 ($0.01–0.03) |
| Deterministic paths (no-signal / sparse) | 0 tokens |
| Dashboard scan | 7 KPIs, 3 systems, ~250 ms |
| Investigation | <2 s offline · 10–20 s live (Sonnet-bound) |
| Fixture refresh (19 live calls) | ~₹12–16 |

Scalability posture: the analytics push down to the warehouse via contract SQL;
`engine/db.py` is the **only file that knows where the data lives** (swapping DuckDB for
Snowflake/Databricks/BigQuery/Postgres is one connection change plus a dialect pass);
investigations are stateless given (KPI, period, role) so they shard horizontally; prompt
size — and therefore cost — is independent of data volume because only aggregates reach
the model.

## 15. Deployment

Hosted on Streamlit Community Cloud (free) from the public repo; also runs anywhere via
`pip install -r requirements.txt && streamlit run app.py`. Hardening that hosted deploys
forced: the dataset ships with the repo (no boot-time generation on a small instance);
all paths resolve from `__file__` (hosted CWD differs); the metrics port bind and the
`prometheus_client` import are fully optional; dependency upper bounds pin out unreviewed
majors; and **never commit `server.headless = false`** — it triggers Streamlit's
interactive first-run email prompt on a server, which blocks on stdin so the port never
binds (our one real production outage, diagnosed from "connection refused + no
traceback"). First-boot failures now render a readable traceback instead of a white
screen. Hosted demo runs offline-mode by default: zero key exposure, zero cost, instant.

## 16. Engineering decisions and bugs we fixed

The decisions that shaped the system, and defects caught by our own adversarial reviews:

1. **Calendar-length noise** — monthly revenue sums vary ±4% just from 28–31-day months,
   drowning a −5% incident (z −1.21). Revenue KPIs became daily run-rates → z −2.16 detected.
2. **Circular corroboration** — the "12-month driver correlation" included the anomaly
   month; one shared drop faked r = +0.95 "historical" support. Relabelled as descriptive
   co-movement; corroboration comes only from evidence.
3. **Evidence-mapping drop** — for driverless KPIs, the extractor's snippets referenced a
   hypothesis id that didn't exist yet, so the true cause rendered "UNCORROBORATED" and the
   verdict wrongly stalled at tentative. Fixed admission order + id resolution; fulfilment
   now correctly reaches actions @ 0.82.
4. **Degenerate z** — constant history + floor produced z = −157,894 on a role-filtered
   view; capped at ±9.99.
5. **Daily noise vs ML** — IsolationForest on raw daily values flagged nothing (a 15%
   shift ≈ 0.75σ of daily noise); moved to smoothed-level features and per-region models.
6. **Fixture governance** — a live session with a stale prompt overwrote curated fixtures
   with jargon; now only `record_fixtures.py` can write them, and the sanitizer makes slop
   impossible at render time anyway.
7. **National aggregates hide regional incidents** — both the ML detector and the live
   monitors are dimensional for this reason; it's also the pitch for why dashboards miss
   root causes.
8. **The hallucination guard** — an LLM-proposed cause cannot rescue confidence when
   declared drivers stayed quiet; demonstrated live on the marketing scenario.
9. **Prometheus for the engine, not the business** — business KPIs in a metrics store
   would be architecture theatre; engine telemetry is its honest use.
10. **The headless deploy outage** (§15) — server config does not belong in a committed
    config file.

## 17. Repository map

```
app.py                       Streamlit UI : 6 pages, theming, typography, charts
contracts/kpi_contract.yaml  the semantic contract (executed at runtime)
roles.yaml                   personas + row/column/domain security
engine/
  pyramid.py    orchestrator: levels, gates, guards, sanitizer, method mix
  anomaly.py    z + materiality + forecast check        stats_ml.py  OLS PI · Pearson · IsolationForest
  contribution.py  dimension deltas                     drivers.py   contract-driver testing
  confidence.py    score + gates                        retrieve.py  docs + ledger retrieval
  stream.py     live-feed replay + dimensional monitors db.py        DuckDB, RBAC, masking, freshness
llm/            client (live/fixture/fallback) · prompts · fallback templates · fixtures/
data/           seeded dataset (committed) + generate_data.py + unstructured/ + market events
ops/            docker-compose : Prometheus + Grafana (pre-provisioned dashboard)
metrics.py      Prometheus instrumentation (optional)   telemetry.py  per-call latency/tokens/cost
feedback.py     decision ledger + corrections           eval.py       accuracy harness
smoke_test.py · ui_test.py                              PROJECT_REPORT.md · DEMO_SCRIPT.md
```

## 18. Known limitations and roadmap

**Honest limitations**: baselines assume stationarity (no seasonality decomposition yet);
retrieval is keyword-based (fine at 10 documents, needs embeddings at scale); the ledger
is JSONL (single-process); role selection is a dropdown, not real authentication; the
evaluation is against synthetic ground truth.

**Roadmap**: predictive "what-if" mode · STL/seasonal baselines · embedding retrieval ·
warehouse connectors (Snowflake/Databricks) behind the existing `engine/db.py` seam ·
scheduled proactive scans with alert delivery · OAuth/SSO · Postgres-backed ledger ·
causal-graph inference · calibration against a client's labelled incident history.
