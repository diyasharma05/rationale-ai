# Rationale.AI — The Complete Product and Technology Guide

**Team Rational.ai · Accenture Innovation Challenge 2026 · Track 3 (BusinessIntelligence.ai) · Grand Finale edition**

This is the one document that explains the whole product: what it is for, what a
user sees, what happens underneath every click, which numbers are computed by
what, how it is secured, tested, deployed, and where its limits are. It is
written to be read end to end by someone who has never seen the code, and to be
checkable line by line by someone who has. Every constant, threshold and
measurement quoted here is taken from the code and the evaluation output on the
`round3-hardening` branch as of 2026-09-19 (241 tests passing; 15 of them run
against a real PostgreSQL).

Companion documents, each narrower than this one:

| Document | What it is for |
|---|---|
| `README.md` | Quick start, repo map, how to run it |
| `TECHNICAL_DOCUMENTATION.md` | Module-level reference (Round 2, patched for Round 3) |
| `docs/PROBLEM_STATEMENT.md` | The problem from four stakeholders' angles, with cited evidence |
| `docs/DESIGN_DECISIONS.md` | Twenty-seven design decisions (D1–D27), each with the alternative considered and the question a judge would ask |
| `docs/PILOT_AND_OPERATIONS.md` | Pilot plan, value model, Day-2 operations |
| `docs/FINALE_PLAN.md` | Deck outline, honest lines, Q&A map |
| `docs/REQUIREMENTS_MAP.md` | The brief's seven pointers mapped to code, tests and gaps |
| `docs/PLATFORMS.md` | The platform seams: what is proven against what, the vendor URLs, the BI hand-off |
| `DEMO_SCRIPT.md` | The eight-minute live demo, beat by beat |

---

## Contents

**Part A — The product**
1. [What Rationale.AI is](#1-what-rationaleai-is)
2. [The problem it solves](#2-the-problem-it-solves)
3. [What it does, precisely](#3-what-it-does-precisely)
4. [Who uses it, and what each person sees](#4-who-uses-it-and-what-each-person-sees)
5. [A tour of the application](#5-a-tour-of-the-application)
6. [The demo world: a synthetic business with a planted incident](#6-the-demo-world-a-synthetic-business-with-a-planted-incident)

**Part B — Architecture**
7. [The layers](#7-the-layers)
8. [What happens when you click "Investigate"](#8-what-happens-when-you-click-investigate)

**Part C — The engine, layer by layer**
9. [Data layer: DuckDB, the semantic contract, and role-based security](#9-data-layer-duckdb-the-semantic-contract-and-role-based-security)
10. [Detection: is this movement real?](#10-detection-is-this-movement-real)
11. [Explanation: where did it come from, and what moved with it?](#11-explanation-where-did-it-come-from-and-what-moved-with-it)
12. [Confidence, gates and ranking](#12-confidence-gates-and-ranking)
13. [The language layer: what the model is allowed to do](#13-the-language-layer-what-the-model-is-allowed-to-do)
14. [Outcomes and the rupee number](#14-outcomes-and-the-rupee-number)
15. [Governed dispatch: from conclusion to a message a person receives](#15-governed-dispatch-from-conclusion-to-a-message-a-person-receives)
16. [The learning loop and the abstain loop](#16-the-learning-loop-and-the-abstain-loop)
17. [Streaming: the Live Feed replay and the live ingestion lane](#17-streaming-the-live-feed-replay-and-the-live-ingestion-lane)
18. [State, persistence and caching](#18-state-persistence-and-caching)
19. [Telemetry and observability](#19-telemetry-and-observability)
20. [The API: the engine as a service](#20-the-api-the-engine-as-a-service)

**Part D — Quality**
21. [Evaluation against planted ground truth](#21-evaluation-against-planted-ground-truth)
22. [Tests, CI and the benchmark](#22-tests-ci-and-the-benchmark)
23. [Performance](#23-performance)

**Part E — Running and deploying**
24. [Running it: modes, environment variables, commands](#24-running-it-modes-environment-variables-commands)
25. [Deployment and the scale story](#25-deployment-and-the-scale-story)

**Part F — Honesty**
26. [What is real, what is replayed, what is simulated](#26-what-is-real-what-is-replayed-what-is-simulated)
27. [Known limitations and roadmap](#27-known-limitations-and-roadmap)
28. [Glossary](#28-glossary)

**Appendices**
- [A. Repository map with sizes](#appendix-a-repository-map-with-sizes)
- [B. Every tunable constant, in one table](#appendix-b-every-tunable-constant-in-one-table)
- [C. Design-decision cross-reference](#appendix-c-design-decision-cross-reference)

---

# Part A — The product

## 1. What Rationale.AI is

Rationale.AI is a **KPI intelligence-to-action engine**. It watches a governed
set of business metrics, notices when one moves in a way that is both
statistically real and commercially material, works out what moved with it and
why, decides honestly whether it knows enough to conclude, routes a
recommendation to the person the business has named as owner, and learns from
whether that person agreed.

The thesis in one sentence: **the language model never computes a number,
never chooses a threshold, and never decides who gets told. It writes
sentences about facts the engine has already established.** Everything
quantitative comes from SQL, statistics and a small amount of classical machine
learning, driven by a human-authored **semantic contract** that defines every
KPI, its drivers, its levers, their owners, and who may see it.

Five outcomes are possible for any investigation, and all five are first-class:

| Outcome | Meaning | What the user sees |
|---|---|---|
| **ACTIONS** | The movement is real and the explanation is established (confidence ≥ 0.75) | A ranked explanation, cited evidence, and recommended actions with named owners and decision rights |
| **TENTATIVE** | Real movement, likely explanation, not established (0.60 ≤ confidence < 0.75) | The explanation, marked as likely, with low-regret steps "while confirming" |
| **ABSTAIN** | Real movement, but the evidence does not support a conclusion (confidence < 0.60) | What was checked, why it is insufficient, one specific question for a human, and an escalation brief |
| **NO SIGNAL** | The movement is inside normal variation, or fails multiplicity control | One sentence saying so; no investigation is opened; zero model tokens spent |
| **SPARSE** | The metric has too little history to establish a baseline | A watching statement with the observed range; no causal claim |

Abstaining and staying silent are deliberate outputs, not failures. The
product's strongest property is that it declines to assert what it cannot
support.

## 2. The problem it solves

Organisations can see *what* changed instantly and find out *why* slowly. The
"why" is an analyst-day of pulling breakdowns, checking adjacent metrics and
searching Slack; the finding lives in a thread and is gone by next quarter.
Meanwhile threshold alerts on many metrics fire independently, so most are
ignored, and executives who rely on dashboards report that they do not fully
trust them.

The industry's current answer, an LLM over the warehouse, has a documented
failure mode: fluent, confident, wrong. Real enterprise schemas drop text-to-SQL
accuracy from the 90s to the 20s and 30s, and most of those errors are semantic
(invented columns, joins and filters), not syntactic. `docs/PROBLEM_STATEMENT.md`
sets this out with sources from four stakeholders' perspectives: the analyst,
the operations lead, the executive and the data-platform team.

Rationale.AI's answer is structural. Put the model **outside** the numerical
path entirely. Let a contract, written by people who know the business, define
what a KPI is and how it relates to other KPIs. Let deterministic methods do
the arithmetic. Let the model do the one thing it is good at, which is reading
documents and writing prose, and count and validate its output in Python.

## 3. What it does, precisely

Given the governed KPIs and their declared relationships, for a chosen month
and a signed-in role:

1. **Detect** material movements across the whole portfolio with a controlled
   false-discovery rate, so that an alert means something.
2. **Explain** each one with a ranked, evidenced set of hypotheses computed by
   deterministic methods, with the strength of each shown honestly, including
   when a co-moving driver is itself unexplained.
3. **Decide whether to conclude**, and abstain with a specific question when
   the evidence does not support a conclusion.
4. **Route** what the contract allows to the person the contract names, with
   the approval it requires, only after a human agrees.
5. **Learn** from the human's verdict, so a rejected explanation ranks lower
   next time, and from the human's answer, so an abstention can be resolved.

Every step above is deterministic except two, both language tasks: mapping
retrieved documents to hypotheses (Claude Haiku 4.5) and writing the persona
narrative (Claude Sonnet 5). Both are consumers of computed facts, never
producers of them, and both have a deterministic fallback so the product runs
with no network and no API key.

## 4. Who uses it, and what each person sees

Three roles ship in `roles.yaml`. They differ in what rows they may see, whether
account names are masked, which KPIs exist for them at all, and how the
narrative is written.

| Role | Persona | Row access | Account names | KPIs visible | Narrative style |
|---|---|---|---|---|---|
| **Data Analyst** (`analyst`) | analyst | All regions | Visible | 7 of 7 | Plain, precise; causal chain in rank order; names what is uncorroborated; says what to verify next. Never recites z-scores. |
| **CEO** (`ceo`) | executive | All regions | **Masked** to stable `ACCT-XXXX` codes | 7 of 7 | Three to five sentences; leads with rupee impact and the single most important cause; one action with an owner; no statistics jargon |
| **Sales Head — North** (`sales_head_north`) | department_head | **North and North-West only** | Visible | **4 of 7** (enterprise accounts, marketing conversion and the home-decor launch are hidden) | Their region and teams only; three or four plain sentences |

Security is enforced in the engine, never in the UI (Section 9.4). The same
rules hold through the API (Section 20).

## 5. A tour of the application

The Streamlit client has eight pages, registered in `ui/pages/__init__.py`. A
sidebar carries the role selector, navigation, dark-mode toggle, LLM settings
and a "Reset demo state" button. Three pages (Dashboard, Data, Investigation)
are scoped to an **analysis window**, a month picker offering February to July
2026; every number on those pages is recomputed for the chosen month.

| Page | What it shows | Where the numbers come from |
|---|---|---|
| **Dashboard** | Triage: every KPI the role may see, flagged first and worst first, with movement, rupee impact where defined, family-wise q-value, source freshness | `services/scan.py` → `engine/anomaly` + `engine/screening`; order from `engine/policy.severity_order` |
| **Live Feed** | An accelerated **replay** of the seeded daily data from 18 June to 31 July 2026, with a rolling detector catching the North-West incident as it "happens"; alarm buttons deep-link into an investigation | `engine/stream.py` (same rolling-z rule as the batch engine) |
| **Data** | Raw source inspection at day/week/month grain with a date slider, row- and column-filtered for the role | `engine/explore.py` (allowlisted sources and grains; bound date parameters) |
| **Investigation** | The reasoning pyramid for one KPI: verdict and confidence gauge, movement, detector votes, contribution breakdowns, driver checks, retrieved evidence, ranked hypotheses, narrative, actions, dispatch preview, feedback buttons, the abstain answer box, and the full level-by-level audit trail. A plain-English ask box routes a question to the right KPI | `engine/pyramid.investigate`; intent via `services/intent.py` |
| **Lineage** | Provenance: the source systems, row counts, date spans and staleness per source, the exact SQL per KPI after the role's filter is applied, and the **live ingestion lane** (Section 17) | `engine/db.source_stats`, `db.kpi_lineage`, `services/live_ingest.py` |
| **Outbox** | Drafted messages waiting for a human, and what has been approved, sent, failed or cancelled, with the full event history of each | `services/outbox.py` |
| **Decision Ledger** | Every investigation ever run, its confidence and outcome, and any human verdict folded onto it; masked for the viewing role | `feedback.read_ledger` |
| **Under the Hood** | How the answers were built: method mix (SQL / statistics / ML / LLM operation counts), per-session telemetry and cost, the evaluation results, the contract browser (honouring domain RBAC), and the security model | `telemetry.py`, `data/eval_results.json`, the contract |

The Investigation page is where the product's character shows. For the
flagship revenue case it lands at **TENTATIVE (0.715)**: the drop is real, four
declared drivers moved with it, the fulfilment collapse leads, but revenue's own
monthly signal is marginal, so the engine says "likely" rather than
"established" and offers low-regret steps. For the planted marketing tracking
bug it **abstains (0.438)** and asks a question; a human can answer it in the
page, and the engine re-runs with the answer as evidence.

## 6. The demo world: a synthetic business with a planted incident

The data is **synthetic, seeded and committed**. Nobody outside the team has
used the system. That is stated before any evaluator asks, and it is also the
reason a precision and a recall figure exist at all: the causes are known
because we planted them.

### 6.1 The business

A retailer operating across five Indian regions (North, North-West, South,
East, West), three customer segments (consumer, SMB, enterprise) and product
categories including a home-decor line launched mid-July 2026. Forty named
enterprise accounts. Thirteen months of history, August 2025 to 25 August 2026.

`data/generate_data.py` produces it deterministically from `numpy.default_rng(42)`,
so every machine gets byte-identical files. The output ships with the repo, so
there is no build step; the app regenerates it only if the CSVs are missing.

| Table | Source system (simulated) | Kind | Grain | Refresh (declared) | Rows | Contents |
|---|---|---|---|---|---|---|
| `sales_orders` | OrderDB (OMS) | **PostgreSQL**, fetched live; nightly CSV extract as fallback | transaction | daily 02:00 IST | 85,222 | order id, date, region, segment, category, account, value |
| `ops_fulfilment` | LogiTrack (WMS) | **CSV** extract | daily × region | daily 04:00 IST | 1,950 | shipments, average delivery days, SLA breaches |
| `crm_events` | RelateCRM | **JSON lines** event export | event | weekly (Mondays) | 1,156 | complaints (one object each), churn events, NPS |
| `marketing_weekly` | RelateCRM marketing | **CSV** extract | weekly × region | weekly (Mondays) | 280 | spend, sessions, conversions |

Three systems, three formats. Section 9.1 describes how they are reconciled.

Plus ten unstructured documents in `data/unstructured/` and three market events
in `data/market_events.json`.

### 6.2 The planted July-2026 incident, exactly

| Date | What was planted | Where it shows |
|---|---|---|
| **2026-06-25** | Warehouse WH-07 main conveyor fails. North-West SLA breach probability 8% → 20%; average delivery days 2.6 → 3.5 | `ops_fulfilment`; the ops note of 28 June; the Slack thread of 3 July |
| **2026-07-01 onward** | North-West consumer/SMB order volume ×0.90; remaining North-West enterprise ordering ×0.70 | `sales_orders` |
| **2026-07-01** | Two enterprise accounts, Meridian Retail Group and Kalinga Mart, stop ordering. Churn logged in CRM on 8 and 19 July | `sales_orders`, `crm_events`; the Kalinga CRM note; the Meridian exit-call transcript |
| July–August | North-West complaint rate ×2.5 (base 1.2% of orders) | `crm_events`; three support tickets |
| **2026-07-01** | Competitor "SwiftKart" launches 2-day express delivery for business customers in North and North-West | `market_events.json`; referenced in a ticket and the exit call |
| **2026-07-01 onward** | **Tracking bug**: marketing sessions ×1.05 and spend ×1.08, but recorded conversions ×0.84. A drop nothing upstream explains | `marketing_weekly` |
| **2026-07-15** | Home-decor category launches with no baseline | `sales_orders` |

Two **red herrings** are in the document corpus on purpose: a marketing memo
about a brand refresh (20 June) and a facilities memo about an office move
(5 July). Neither should be cited as a cause. A **postmortem from November 2025**
about East-region dispatch delays exists so that the decision ledger's seeded
precedent (`INV-2025-11-EAST`, "3PL overflow playbook worked") has something to
recall.

### 6.3 What the engine concludes for July 2026 (analyst role)

| KPI | Movement | Detector | Outcome | Confidence | Rank-1 explanation |
|---|---|---|---|---|---|
| Net Revenue | −7.0% | z −2.16, p ≈ 0.066, q survives at FDR 0.10 | **TENTATIVE** | 0.715 | Fulfilment SLA fell (planted cause) |
| Fulfilment SLA % | 92% → 88.3% | z −9.75 | **ACTIONS** | 0.807 | WH-07 conveyor / backlog (model-proposed from documents; the contract declares no drivers) |
| Complaint Rate | +29% | z +2.96 | **ACTIONS** | 0.779 | Fulfilment SLA fell |
| Enterprise Active Accounts | 40 → 37 | z −6.97 | **ACTIONS** | 0.784 | Fulfilment SLA fell |
| Marketing Conversion | −15.7% | z −26.7 | **ABSTAIN** | 0.438 | None: spend and sessions are healthy, so nothing declared explains it; the engine asks whether tracking changed |
| Average Order Value | −3.5% | z −0.82 | **NO SIGNAL** | 0.134 | Inside normal variation |
| Home-Decor Revenue | 6 weeks old | — | **SPARSE** | 0.25 | Too new to diagnose |

Across the five control months (February to June 2026) every KPI is NO SIGNAL
or SPARSE. Detection precision and recall are both 1.0 over 36 cases
(Section 21).

---

# Part B — Architecture

## 7. The layers

```
 ┌──────────────────────────────────────────────────────────────────────────────┐
 │  CLIENTS                                                                     │
 │   app.py (192 lines: boot, sidebar, control bar, router)                     │
 │   ui/pages/*  eight pages, each `render(ctx)`      ui/components/*  charts,  │
 │   ui/theme.py  ui/context.py (Viewer, Window, Nav, Ctx)  tiles, method strip │
 │   api/main.py  FastAPI: /healthz /kpis /scan /investigate /metrics/summary   │
 ├──────────────────────────────────────────────────────────────────────────────┤
 │  SERVICES (view models; no Streamlit import; take primitives, not ctx)       │
 │   scan.py  intent.py  outbox.py  transports.py  live_ingest.py               │
 ├──────────────────────────────────────────────────────────────────────────────┤
 │  ENGINE (every number)                                                       │
 │   pyramid.py ── orchestrates the four levels and the gates                   │
 │   db.py        DuckDB or PostgreSQL · contract · roles · RBAC · masking      │
 │   anomaly.py   z, pct, t-test          screening.py   Benjamini–Hochberg     │
 │   stats_ml.py  OLS 90% PI · IsolationForest · Pearson Δ-corr                 │
 │   contribution.py  by region/segment/category   drivers.py  co-movement      │
 │   retrieve.py  weighted term ranking   confidence.py  score + gates          │
 │   economics.py rupees   policy.py levers/owners   dispatch.py routing        │
 │   explore.py   allowlisted ad-hoc SQL  stream.py replay  cache.py disk cache │
 ├──────────────────────────────────────────────────────────────────────────────┤
 │  LANGUAGE (words only)                                                       │
 │   llm/client.py (live · fixture · absent)  llm/prompts.py  llm/fallback.py   │
 │   llm/fixtures/*.json  22 recorded responses                                 │
 ├──────────────────────────────────────────────────────────────────────────────┤
 │  STATE & OPS                                                                 │
 │   store.py  streams (JSONL|PostgreSQL)  feedback.py  telemetry.py  metrics.py│
 │   data/state/  data/cache/  data/live/    ops/bench.py  ops/ingest.py        │
 ├──────────────────────────────────────────────────────────────────────────────┤
 │  GOVERNANCE (human-authored, read by the engine)                             │
 │   contracts/kpi_contract.yaml       roles.yaml                               │
 └──────────────────────────────────────────────────────────────────────────────┘
```

**The directory listing is the architecture diagram.** Pages render; services
shape data for a screen; the engine computes; the language layer writes; state
persists; the contract governs. The boundaries are enforced by
`tests/test_layering.py`:

- services never import Streamlit (so they run from pytest, `eval.py` and the API);
- components never import services (a component renders what it is given);
- pages never build SQL (no string constant containing `SELECT … FROM`);
- `st.rerun()` appears only in `app.py` and `ui/context.py` (with one documented
  exception for the Live Feed's replay timer);
- `app.py` stays under 300 lines (it was 1,654);
- the page registry has exactly eight callable entries.

**The context object.** Pages receive one frozen `Ctx` carrying `viewer`
(role, persona, regions, masking), `window` (the analysis month), `llm`, `nav`
(the only mutable surface: `goto`, `refresh`, `investigate`) and `store` (the
session's investigation results). Five rules keep it from becoming a
god-object: it carries no data and no engine handles; services take primitives,
never `Ctx`; components take explicit arguments; only `Nav` mutates; page-local
state stays in `st.session_state` under page-prefixed keys.

## 8. What happens when you click "Investigate"

`pyramid.investigate(kpi_id, period, role_id, llm)` is a function of its inputs
given the data. This is the sequence, with the module responsible for each step.

```
 1  db.kpi_series(kpi, role)         contract SQL with the role's WHERE clause injected
 2  anomaly.analyze(...)             z vs 12-month mean · % vs trailing-3 · t-test (prediction SE)
 3  screening.screen(...)            Benjamini–Hochberg across every KPI this role sees this month
    ├─ sparse?    → SPARSE, fixed confidence 0.25, logged, return   (0 model tokens)
    └─ not material or FDR-suppressed? → NO SIGNAL, logged, return  (0 model tokens)
 4  contribution.top_contributors    per-dimension deltas vs prior-3-month mean; focus members or "diffuse"
 5  drivers.check_drivers            each declared driver: co_moves / contradicts / quiet; unexplained flag; Δ-correlation
 6  detector votes                   z + materiality · OLS 90% PI (same history, so a consistency check) · IsolationForest (revenue only, cached)
 7  confidence.score → conf1         LEVEL 1 complete (non-LLM)
 8  retrieve.search                  weighted whole-term ranking over documents + admissible ledger + human answers; top 6; masked
 9  llm.json_call("extract_…")       Haiku maps documents → hypotheses (fixture offline; heuristic fallback if absent)
10  hallucination guard              a model-proposed cause is admitted only if the contract declares NO drivers; else "unvalidated lead"
11  abstain loop                     human answers for this KPI+period become hypotheses (confirm) or eliminated leads (rule out)
12  confidence.score → conf2         LEVEL 2 complete
13  if conf2 < 0.90: market events   tag × region matching over the event feed → LEVEL 3; else early exit
14  _rank_hypotheses                 0.5·stat + 0.3·evidence + 0.2·external; ×0.5 if unexplained; ×1.15 / ×0.6 by past human verdict
15  gates                            ≥0.75 ACTIONS · ≥0.60 TENTATIVE · else ABSTAIN
16  context → mask → llm.json_call("narrative_…")   Sonnet writes persona prose over verbatim facts (fixture offline; template fallback)
17  sanitizer                        drop sentences with statistics vocabulary; cap lengths; strip id clutter; mask again
18  method_mix · telemetry · ledger  operation counts by method; per-call latency/tokens/cost; append to decision ledger; Prometheus mirror
```

Warm, the whole sequence runs in well under a second offline. The only slow
step, fitting five IsolationForests, is cached on a content hash of the data
(Section 18), so it is paid once per dataset per role, not once per click.

---

# Part C — The engine, layer by layer

## 9. Data layer: DuckDB, the semantic contract, and role-based security

### 9.1 Heterogeneous sources, one governed namespace

`engine/db.py` is the only file that knows where the data lives, and
`engine/sources.py` is how it finds out. The contract's `sources:` block declares,
for each system, a `kind` and a `location`:

| Kind | Source | How it is ingested |
|---|---|---|
| `postgres` | OrderDB, the live order system | Fetched over the wire at start-up with `COPY TO STDOUT` from the database named by `RATIONALE_OMS_DSN` (about 270 ms for 85k rows on this laptop). If that is unset or unreachable, the last nightly extract is loaded instead and the provenance says so |
| `sql` | Any warehouse with a SQLAlchemy URL: Snowflake, Databricks SQL, Fabric, BigQuery, PostgreSQL, SQLite | Same contract as `postgres` through the vendor's driver; proven against PostgreSQL and SQLite, vendor URLs documented in `docs/PLATFORMS.md` |
| `csv` | The WMS daily file and the marketing weekly file | Read directly |
| `jsonl` | The CRM event export, one JSON object per line | Read directly; DuckDB's JSON reader is built in and works offline |
| `parquet` | Not used by the demo | Supported for a lakehouse drop |

Every source lands as a **typed table** with its date column cast once, so the
contract SQL joins across systems (complaint rate is CRM events over OMS orders)
without knowing where either side came from. What it does know is recorded per
table: system, kind, redacted location, live or extract, rows, latest record
date, fetch time. The Lineage page shows that table with a summary line, and
`GET /sources` returns it. A live source that cannot be reached is never
substituted silently. The verdicts do not depend on the path: the golden case is
TENTATIVE at 0.715 whether the order system was fetched live or read from its
extract, because they hold the same nightly data.

At first use DuckDB builds an in-memory database and materialises each source
this way, for example:

```sql
CREATE TABLE sales_orders AS
SELECT * REPLACE (CAST(order_date AS DATE) AS order_date)
FROM read_csv_auto('data/sales_orders.csv')
```

Tables, not views: a view over `read_csv_auto()` re-parses the file on every
query (~54 ms against 85k rows, no warm-up benefit). One build costs ~200 ms;
every later query scans an in-memory table. Because the cast happens at load,
the contract SQL's own `CAST(col AS DATE)` becomes a free no-op instead of a
per-row string parse.

The connection is built once under a `threading.Lock` (Streamlit runs each
session in its own thread, and an unguarded check-then-set let two threads both
build the tables). Every read goes through `db.query(sql, params)`, which
executes on a **per-call cursor** over the shared database: DuckDB's documented
pattern for concurrent use, and the fix for interleaved result sets under
load.

### 9.1a Two engines behind one `query()`

Every read in the codebase goes through one function, and that function has two
implementations selected by `RATIONALE_DB`:

| Backend | When | What it is |
|---|---|---|
| **DuckDB** | Default | In-process; the CSVs materialised as typed tables at first use. Zero infrastructure, which is what the offline demo, the tests and CI run on |
| **PostgreSQL** | `RATIONALE_DB=postgresql://…` | The same contract SQL against tables loaded by `python -m ops.pg_local`, over one connection per thread. The event streams (Section 18) move with it |

Making the contract run on a second engine took three dialect changes, which
is the point: six casts spelled `::DOUBLE PRECISION` (valid in both engines,
where DuckDB alone accepted `::DOUBLE`), a placeholder translation for the two
parameter-bound Data-page queries, and a loader that uses `COPY` where DuckDB
uses `read_csv_auto`. The month key is normalised in Python after the query,
so PostgreSQL returning a timestamp where DuckDB returns a date is harmless,
and `NUMERIC` results are loaded as floats so both engines hand back the same
frame. PostgreSQL table schemas are derived from DuckDB's own CSV type
inference, so the two engines hold identically typed tables.

**Measured parity**, in `tests/integration/test_backend_parity.py`, run in CI
against a PostgreSQL service container: every KPI series for every role is
equal to a relative tolerance of 1e-9; the July breakdowns and the daily frame
are equal; the portfolio scan flags the same five KPIs; the six July verdicts
match in outcome, confidence to three decimals and rank-1 explanation; and the
full 36-case evaluation is identical case by case. RBAC holds through the
second engine because the WHERE clause is the same string.

**Running it without Docker.** PostgreSQL ships as a plain zip of binaries.
`ops/pg_local.py` downloads it once, runs it as an ordinary user process on
port 5433 with its data directory inside the repo (gitignored), loads the four
sources with `COPY`, creates the `events` table, and provisions two roles: an
owner, and `rationale_app`, which may SELECT everywhere and INSERT into
`events` and nothing else. The app connects as the latter, so the ledger is
append-only by grant; a test connects as that role and asserts that UPDATE and
DELETE are refused.

**What this proves and what it does not.** It proves the contract and the
engine are portable, and that the shared state has a transactional home, which
is what horizontal scaling needs. It does not make PostgreSQL the analytics
engine for a client: the scale answer for the numbers is the client's
warehouse (Section 25.2), and on one laptop the first click of a session is
slower on PostgreSQL because an investigation's twenty-five or so small queries
each re-aggregate the source rows over a network hop; after that the result
caches mean neither engine is asked anything (Section 23).

### 9.2 The semantic contract

`contracts/kpi_contract.yaml` is not documentation; the engine reads it. One
entry per governed KPI:

| Field | What it is | Example (revenue) |
|---|---|---|
| `name`, `unit`, `definition`, `owner` | Business identity | "Net Revenue (daily run-rate)", `INR/day`, Chief Revenue Officer |
| `source` | Which table, with its declared system, grain and refresh | `sales_orders` → OrderDB, transaction, daily 02:00 |
| `sql` | The monthly series query, **executed as written**, with `{where}` as the row-security injection point | `SUM(order_value) / COUNT(DISTINCT order_date)` grouped by month |
| `dimensions`, `dim_sql` | Breakdown dimensions and the per-member query with `{dim}` and `{period}` | region, segment, category |
| `dim_additive` | Whether member values sum to the national value (only then is a "share of movement" meaningful) | `true` for revenue; `false` for percentages and averages |
| `materiality` | The business bar a movement must clear: `min_abs_z` and `min_pct` | z ≥ 2.0 and 3% for revenue; z ≥ 2.5 and 7% for the volatile AOV |
| `good_direction`, `dim_unit` | Which way is good news; the unit of breakdown values when it differs | complaints: `down`, breakdown in raw counts |
| `ml_daily_check` | Whether to run the daily-grain IsolationForest | revenue only |
| `min_history` | Months required before causal claims | default 6 |
| `tags` | Retrieval vocabulary | revenue, orders, sales, delivery, customer |
| `drivers` | Declared causal links to other KPIs (`kpi`) or ad-hoc metrics (`metric` + `metric_sql`), each with `relation: direct \| inverse` and a note | fulfilment_sla (direct), complaint_rate (inverse), enterprise_active_accounts (direct), marketing_conversion (direct) |
| `levers` | Controllable actions, each with `owner` and `approval` | "Fulfilment capacity allocation (3PL overflow)" — VP Operations — COO (spend > ₹5L/quarter) |
| `lineage` | Where the data comes from, in words | storefront checkout → OMS → nightly ELT → analytics.sales_orders |
| `access` | Which roles may see this KPI at all | analyst, ceo, sales_head_north |

Seven KPIs are governed: Net Revenue, Average Order Value, Fulfilment SLA %,
Complaint Rate, Enterprise Active Accounts, Marketing Conversion Rate, and
Home-Decor Revenue. Revenue KPIs are defined as **daily run-rates** (sum ÷
distinct order days) because calendar length (28–31 days) otherwise injects
±4% noise that drowned a −5% signal in testing.

Why this is the centrepiece: the contract is the layer the industry is
converging on (a 2026 dbt Labs benchmark measured semantic-layer grounding
lifting text-to-SQL accuracy from 90.0% to 98.2%), taken one step further. The
model never writes the SQL at all; the contract does. In a client deployment,
the contract is authored in a facilitated workshop with the KPI owners, which
is the hard, human step (`docs/PILOT_AND_OPERATIONS.md`, phase 0).

### 9.3 Roles

`roles.yaml` defines each role's `persona` (analyst, executive, department_head),
`regions` (`all` or a list), `mask_accounts` (boolean) and a `narrative_style`
paragraph passed verbatim to the narrative prompt.

### 9.4 Role-based security, three kinds, all in the engine

| Kind | Mechanism | Where it bites |
|---|---|---|
| **Row-level** | `db.role_where(role)` returns `" AND region IN ('North','North-West')"` or `""`; it is substituted into every contract query's `{where}` | KPI series, breakdowns, driver metrics, the daily frame for the IsolationForest, the Data page, the Lineage page's SQL display |
| **Column-level** | `db.mask_text(text, role)` replaces each enterprise account name with `ACCT-` + the first four hex characters of its SHA-1, for roles with `mask_accounts: true` | Retrieved snippets, the serialised context **before** it reaches the model, the narrative headline and body afterwards, the Data page, the Ledger page |
| **Domain-level** | `db.allowed_kpis(role)` filters the contract by each KPI's `access` list | The dashboard, the scan, the FDR family, the contract browser, the ask box, and the API (403) |

Two properties matter for a client conversation. Masking happens **before the
prompt**, so account names never leave the perimeter; the only thing sent to a
model is precomputed aggregates plus masked snippets, never raw rows. And the
row filter is in the query plan, so a restricted role's caches, ML verdicts and
retrieval results are all scoped by construction: `tests/rbac/` primes every
cached path as the analyst and asserts the restricted role still sees strictly
less revenue and no hidden KPI.

## 10. Detection: is this movement real?

### 10.1 The primary test (`engine/anomaly.py`)

For the analysis month against the history before it (12-month stationary
baseline; seasonality is on the roadmap):

- **z** = (current − mean of history) / sample standard deviation. A
  near-constant history caps z at ±9.99 instead of producing −157,894.
- **pct_vs_recent** = change against the mean of the trailing three months.
  Direction and magnitude in every sentence come from the **same** baseline; a
  7% decline used to render as "up 7.0%" when the two baselines disagreed.
- **Materiality** = |z| ≥ the contract's `min_abs_z` **and** |pct| ≥ `min_pct`.
  A statistical threshold alone would flag movements nobody cares about.
- **The proper small-sample test.** With 6–11 observations the reference
  distribution is a t with n−1 degrees of freedom, and the quantity tested is a
  *new* observation, so the denominator is the prediction standard error
  s·√(1 + 1/n), not s. The p-value reported is two-sided from that t. Treating
  |z| ≥ 2 as p = 0.046 overstates significance badly; it is nearer 0.09 at n = 7.
  The z is kept because the contract thresholds and every fixture are
  calibrated on it, but the p-value is what feeds multiplicity control.
- Fewer than `min_history` months (default 6) → **sparse**, and the function
  returns before any test.

### 10.2 Multiplicity control (`engine/screening.py`)

Every month the engine tests every KPI the role can see. Seven independent
tests at |z| ≥ 2 give a family-wise false-positive rate near 28%: roughly one
phantom alert a month, which is exactly the alert fatigue the materiality gate
exists to prevent. On the demo data it produced two, in two control months
(complaint rate, February and April 2026), with nothing planted.

**Benjamini–Hochberg** controls the false *discovery* rate instead: of the
movements flagged, at most a fraction q are expected to be spurious. It stays
sensitive, unlike Bonferroni, which at n = 7 would suppress real incidents.
`FDR_Q = 0.10`, the conventional exploratory-screening level.

The family is **role-scoped**: two roles monitor different numbers of KPIs, so
the correction genuinely differs. Sparse KPIs are excluded from the family
(they are never tested). A movement that clears its own bar but fails the
family test is reported as `fdr_suppressed`, and the UI says why it was not
escalated rather than silently dropping it.

Measured on planted ground truth at q = 0.10: all five July incidents survive,
both false positives are dropped, and detection precision rises from 0.833 to
1.000 with recall unchanged at 1.0. **The rigorous method scores strictly
better than the loose one.**

One caveat stated openly: July revenue (p = 0.0658) survives its step-up
threshold by 0.0009. At q = 0.05 it would be suppressed. The choice of q is
load-bearing and a test pins the margin. Revenue's own signal *is* marginal;
conviction about it comes from four corroborating drivers and the documents,
which is a better story than "z = −2.16, significant".

### 10.3 Corroborating detectors (`engine/stats_ml.py`)

Deliberately **not** called an ensemble of independent votes.

- **OLS trend forecast with a 90% prediction interval.** An ordinary-least-
  squares fit over the history, one step ahead; the month is flagged if the
  actual lands outside the interval. The critical value comes from `scipy`'s t
  distribution (it was a 14-entry lookup table with a wrong tail). It is fit on
  the *same* history as the z-test with the same residual scale, so it agrees
  on essentially every case (measured R² < 0.06). It is a consistency check,
  not a second opinion, and it is labelled that way on screen.
- **IsolationForest per region at daily grain** (revenue only, per
  `ml_daily_check`). For each region, one 200-tree forest
  (`contamination = 0.03`, `random_state = 42`) is trained on that region's days
  before the analysis month and scores the month's days. Features are the 7-day
  rolling mean and its ratio to the 90-day rolling mean; raw daily revenue is
  too lumpy (enterprise orders) for a per-day outlier test to see a level
  shift. Requires ≥ 90 training days and ≥ 10 test days per region. Decision
  rule: > 10% of the month's days anomalous in the worst region. This is the
  one detector that sees something the monthly test cannot: a regional level
  shift that national totals smooth over.

  The UI states the caveats: with 7-day smoothing, consecutive days share six
  of seven inputs, so "4 of 31 days" is nearer 4.4 effective observations, and
  the verdict is shown with its **decision margin** ("one fewer anomalous day
  would flip this verdict").

### 10.4 Why the July numbers are what they are

Revenue falls 7.0% (z −2.16), a marginal monthly signal because the incident
hits one region from late June and the national run-rate absorbs most of it.
Fulfilment SLA (z −9.75), enterprise accounts (z −6.97) and marketing
conversion (z −26.7) are far outside their histories because those series are
tight. Complaints rise 29% (z +2.96). AOV moves −3.5% (z −0.82), deliberately
below its higher bar, to demonstrate noise rejection.

## 11. Explanation: where did it come from, and what moved with it?

### 11.1 Contribution (`engine/contribution.py`)

For each contract dimension, the analysis month's per-member value is compared
with the mean of the prior three months.

- **Share of movement** is reported only when the contract says the KPI is
  additive **and** the deltas are not mostly cancelling (|net| ≥ 0.5 × gross).
  A percentage or an average cannot be decomposed additively; for those the
  per-member **level change** is the honest output.
- **Focus members** are claimed only when a member accounts for ≥ 35% of the
  movement *in the direction that hurts* (using `good_direction`), up to two
  members. Otherwise the movement is reported as **diffuse**, which is a real
  finding: a drop spread evenly across every region argues against a regional
  cause and towards something systemic, such as a measurement change. This is
  exactly what the planted tracking bug looks like, and a test asserts it.

Earlier versions selected on |share|, which put *improving* regions into focus,
and fell back to "largest |delta|", which picked a region that beat the next by
1% of noise. Both are gone.

### 11.2 Drivers: co-movement, not causation (`engine/drivers.py`)

For each driver the contract declares, the engine asks one precise question:
*did this series move in the analysis month (|z| ≥ 1.5), in the direction the
declared relation predicts?*

| Status | Meaning |
|---|---|
| `co_moves` | Moved as the contract predicts. Concurrent, **not proven causal**. |
| `contradicts` | Moved the other way: evidence *against* this explanation. Reduces confidence. |
| `quiet` | Did not move meaningfully. A declared driver that did not move is real evidence against it. |

The causal claim is imported wholesale from the contract's `relation` field,
which a human wrote. This module contributes no evidence about direction of
causation: no lag structure, no Granger test, no confounder control, no
counterfactual. The UI and the prompts say "moved with it", never "caused".

**Unexplained drivers.** A co-moving driver that is itself a governed KPI with
declared drivers, none of which moved, is flagged `unexplained`: it moved, but
nothing upstream accounts for why. It counts at **half weight** in coverage
and in ranking. This is what stops the planted marketing tracking bug (a
measurement artifact whose own drivers, spend and sessions, are both quiet) from
counting as evidence that it caused the revenue drop. Without it, that driver,
which has the largest |z| of any, would lead the revenue story on sheer size.

A **Pearson correlation of month-over-month changes** over the 12 months
including the analysis month is computed for each driver and shown as a
descriptive co-movement statistic. With ~12 delta pairs a shared move in the
anomaly month dominates r, so it is never presented as historical proof.

### 11.3 Retrieval (`engine/retrieve.py`)

The corpus has three kinds of document:

| Kind | Source | Admissibility |
|---|---|---|
| `document` | The ten files in `data/unstructured/` | Always |
| `ledger` | Past investigations from the decision ledger, rendered as "PAST INVESTIGATION … confidence … summary" | **Strictly past**: period < analysis period, and never rows with an empty period. Capped at 2 of the top-k, so a lived-in ledger cannot crowd out human-written documents. Weighted by any human verdict: up ×1.5, down ×0 (dropped), none ×1 |
| `human_answer` | A human's answer to the engine's own clarifying question | Only for **this** KPI, for this period or earlier. Weighted ×3 after a floor of 1, so it cannot be crowded out of the top-k by keyword-dense tickets |

Query terms come from the KPI's `tags` (weight 1.0), the focus regions
(weight 2.0), and the tags of any co-moving driver (weight 1.0). Scoring is a
weighted count of **whole-term** matches using the pattern
`(?<![\w-])term(?![\w-])`. A plain word boundary was not enough: a hyphen is a
non-word character, so `\bwest\b` matched inside "north-west", which is how a
national marketing investigation once retrieved the North-West enterprise
exit-call transcript as its top evidence. The top 6 are returned as snippets
`E1`…`E6`, 700 characters each, masked for the role.

Keyword retrieval is a deliberate choice for the prototype: it is transparent,
stable, and keeps the recorded fixtures reproducible. Production would use
hybrid BM25 + embeddings with access control applied at the index.

### 11.4 Evidence mapping and the hallucination guard

Claude Haiku 4.5 receives the numbered hypotheses and the retrieved snippets
and returns JSON: for each snippet, whether it is relevant, which hypotheses it
supports, and one key fact. The system prompt is strict: *a document supports a
hypothesis only if it contains a concrete fact about that cause; topical
similarity is not support*. It may propose **at most one** new hypothesis, and
only if a document states a concrete mechanism for *this* KPI's movement.

The mapping is **counted, not scored**, in Python: a hypothesis's evidence is
the list of snippet ids attached to it. If no fixture exists offline, a
deterministic heuristic (≥ 2 keyword hits ⇒ support) stands in and is labelled
as a fallback.

**The hallucination guard.** A model-proposed hypothesis is admitted only when
the contract declares **no** drivers for the KPI (there is nothing structured to
check against; fulfilment SLA is the case, and its cause, the WH-07 conveyor,
comes from the documents). If declared drivers exist but stayed quiet or
contradicted, an unstructured anecdote must not rescue confidence: it is
surfaced as an **unvalidated lead** instead of evidence.

### 11.5 A causal estimate, where the data identifies one

Everything above tests concurrent movement. `engine/causal.py` is the one
place a causal quantity is estimated, and it uses the classical design the
regional data supports: the regions the contribution analysis puts in focus are
the treated units, the other regions the role can see are the controls, the
three months before the analysis month are the pre-period and the month itself
the post-period. **Difference-in-differences** on that weekly panel gives an
effect size with a 95% bootstrap interval (weeks resampled as blocks, 400
draws), a **pre-period placebo** as the parallel-trends check, and **placebo
regions** as a permutation reference, with the floor stated (five regions
cannot reach below p = 0.2).

| Case (July 2026, analyst) | Result |
|---|---|
| Revenue | North-West vs the other four: about −₹0.71 lakh per day per treated region, 95% CI −₹1.27 to −₹0.17 lakh; scaled to the month about −₹21 lakh, roughly 82% of the total movement; pre-period placebo near zero |
| Fulfilment SLA | −11.4 percentage points, interval well clear of zero |
| Complaint rate | +24 per thousand orders |
| Average order value | Interval spans zero, consistent with the signal gate's "nothing moved" |
| Marketing conversion | **Not identifiable**: the movement is spread across every region, so there is no untreated comparison group |
| Enterprise active accounts | **Not identifiable**: no regional daily panel for this KPI |
| Revenue, sales head | Identifiable with one control region; the output says to treat the interval with caution |

The estimate does **not** enter the confidence score or the gates; it is
evidence beside the verdict, and the narrative may quote it once with its
assumption. The assumptions are printed with it, including the one the demo
data violates slightly: the conveyor failed on 25 June, so the last pre-period
week is contaminated, which biases the estimate toward zero. It runs in about
20 ms.

### 11.6 The forecast, in words

The sparkline has always drawn a three-month OLS forecast with a 90% prediction
interval. `engine/forecast.py` states it: next month's expected value and
band, anchored on the analysis month and using only history up to it, plus two
scenarios (this month's level persists; it reverts to baseline) and the caveat
that the trend explains little of the variance (R² is shown), so the band is
essentially the normal range next month must leave before it is news.

### 11.7 The contract as a knowledge graph

Systems host sources, sources feed KPIs, KPIs drive KPIs with a declared
direction, levers control KPIs, owners own levers, approvers approve them.
`engine/graph.py` builds that graph from the contract (42 nodes, 52 edges), the
Lineage page draws it with a neighbourhood highlight, `GET /graph` serves it,
and every investigation reports its **downstream exposure**: which KPIs declare
this one as a driver and which owners that touches. A fulfilment shock names
revenue, complaints and enterprise accounts, and four owners, from the contract
alone.

### 11.8 External signals

`data/market_events.json` holds dated events with tags and regions. An event
matches when its regions intersect the focus regions (or it is national) and
its tags intersect the KPI's and hypotheses' keywords. Matched events attach to
the hypotheses they share tags with, or become an `external` hypothesis of their
own. In the July revenue investigation the SwiftKart express-delivery launch
attaches to the fulfilment, enterprise-accounts and complaint hypotheses; the
monsoon and rate-decision events do not match. This level is skipped when confidence after Level 2 is already ≥ 0.90.

## 12. Confidence, gates and ranking

### 12.1 The score (`engine/confidence.py`)

```
score = 0.35 · signal    +  0.35 · coverage  +  0.30 · evidence
signal   = min(|z| / 3, 1)
coverage = (credit + 1) / (n_drivers + 2)  −  0.25 · n_contradicting        [None if no drivers declared]
           credit counts each co-moving driver as 1, or 0.5 if unexplained
evidence = (n_corroborated + 1) / (n_hypotheses + 2)                          [0 if no hypotheses]
```

Then three adjustments, each stated openly:

1. **Unassessable components are dropped and the weights renormalised.** A KPI
   with no declared drivers used to receive a flat 0.5 "neutral prior" for
   coverage, that is 0.175 of the score for having nothing to check. Absence of
   evidence is not credit.
2. **Verifiability discount.** Renormalising alone has a perverse consequence:
   removing a checkable dimension *raises* a score (fulfilment SLA scored 0.885
   against revenue's 0.715 because revenue could be cross-checked against four
   drivers and SLA could not be checked at all). So the weighted mean is scaled
   by `0.75 + 0.25 × (assessed weight / total weight)`. The floor 0.75 is the
   smallest discount for which the invariant "a KPI cross-checked against a
   driver must not score below one that could not be checked" holds; a test
   pins it.
3. **Hard ceiling 0.95.** The Laplace smoothing already makes 1.0 unreachable
   ("1 of 1 corroborated" scores 2/3, not certainty); the cap guarantees no
   future change can put total certainty on screen. Under the previous formula
   enterprise accounts displayed 1.000.

### 12.2 The gates

| Gate | Threshold | Effect |
|---|---|---|
| Signal | materiality **and** multiplicity control | Below: NO SIGNAL, zero tokens |
| Evidence | score ≥ **0.60** | Below: ABSTAIN with a clarifying question and an escalation brief |
| Action | score ≥ **0.75** | Below (but ≥ 0.60): TENTATIVE with low-regret steps. At or above: ACTIONS |
| Early exit | score ≥ **0.90** after Level 2 | Level 3 skipped to save latency and cost |
| Sparse | fixed **0.25** | Reported on the sparse path; the narrative quotes the same constant it scores |

The gate values were asserted in Round 2. They are now validated: the
evaluation harness reports the **gate-separation margins**, the gap between the
highest score below each gate and the lowest above it across all 36 cases.

| Gate | Highest below | Lowest above | Margin |
|---|---|---|---|
| Evidence (0.60) | 0.449 | 0.715 | 0.266 |
| Action (0.75) | 0.715 | 0.779 | **0.064** |

The action margin is narrow. It is shown on the Under the Hood page rather than
hidden, and the honest line is: revenue at 0.715 is the case that *should* sit
below the action gate.

### 12.3 Hypothesis ranking

```
strength = 0.5 · stat  +  0.3 · min(n_snippets / 3, 1)  +  0.2 · (1 if any external event else 0)
stat     = min(|z_driver| / 4, 1)   for a contract driver
         = 0.8                      for a human-stated cause (testimony: above a model lead, below a saturated measurement)
         = 0.4                      for a model-proposed or external hypothesis
× 0.5   if the driver is unexplained
× 1.15  if a human previously confirmed a conclusion naming this driver for this KPI
× 0.6   if a human previously rejected one
```

Ranks are computed, never model-scored. The narrative prompt is told the ranks
are an *explanatory ordering*, not established causation. Beneath the ranked
list the page shows **alternatives considered**: every explanation that did not
lead, with the reason it ranks lower (unexplained, unbacked, contradicted,
ruled out by a named person, or model-proposed and refused by the guard).

## 13. The language layer: what the model is allowed to do

### 13.1 Two calls, two jobs

| Call | Model | Input | Output | Validation |
|---|---|---|---|---|
| Evidence mapping | `claude-haiku-4-5`, max 1,500 tokens | Numbered hypotheses + retrieved snippets + one movement sentence | JSON mappings; at most one new hypothesis | Counted in Python; guard in Section 11.4 |
| Narrative | `claude-sonnet-5`, effort `low`, max 8,000 tokens | The masked context: movement (prose form), rupee impact, focus regions, concentration, contribution rows with their own units, ranked hypotheses with provenance, contradicting drivers, confidence, outcome, unvalidated lead, detector flags, driver correlations, the contract's levers, past playbooks; plus the role's `narrative_style` | JSON: headline, body, actions (driver, lever, action, expected impact, owner, confidence, monitoring), what could change, caveats, clarifying question, escalation brief | Sanitised, masked, and actions later re-routed by the contract |

The narrative system prompt enforces the voice: headline of ~14 words; body of
2–4 sentences under 25 words each with at most one number per sentence; never a
hypothesis id; citations only as `[E1]`, one per sentence, never chained; no
engine or statistics vocabulary; if abstaining, no root cause and one useful
question; actions may only use the provided levers and owners; never write
"caused"; present unexplained hypotheses as leads.

### 13.2 The sanitizer

Whatever the model returns, the UI shows only short human prose. `_tidy_narrative`
drops any sentence containing engine vocabulary (`z=`, `z-score`, `strength=`,
`share of delta`, `evidence_gate`, `coverage=`, `r²`, `rank-1`, `co-move`,
`correlat`, and so on), caps the headline at one sentence / 140 characters and
the body at four sentences / 520 characters, collapses citation chains to the
first id, strips `H1:`-style prefixes and `[E#]` clutter from action fields, and
truncates each action field. Then account masking is applied again to the
headline and body.

Two forms of the movement sentence exist for this reason: a **technical** form
with `(z=…)` for the analyst audit trail and the model's grounding, and a
**prose** form for anything a non-analyst can see. A template narrative built
from the technical form once collapsed to "Confidence 78%." because the
sanitizer removed its only sentence.

### 13.3 Three modes, and the fixtures

`llm/client.py` decides at construction:

| Mode | When | Behaviour |
|---|---|---|
| **live** | `ANTHROPIC_API_KEY` set and `MOCK_MODE` ≠ 1 | Real calls through the official SDK, bounded to a 20-second timeout and one retry (the SDK default of 2 × 10 minutes could freeze a venue demo for half an hour). Any failure falls to fixture, then to the deterministic fallback |
| **fixture** | Offline, and `llm/fixtures/<task_key>.json` exists | Returns the recorded JSON; telemetry records a zero-cost fixture call |
| **absent** | Offline, no fixture | Returns `None`; the caller uses `llm/fallback.py` (heuristic mapping; template narrative) and the UI labels it |

Task keys are content-addressed by situation: `extract_<kpi>` and
`narrative_<kpi>_<persona>`, with `_<period>` appended for any month other than
July 2026 (so a fixture recorded for the incident month can never be replayed
for a clean month), and `_answered` appended once a human has answered the
engine's question (so abstain prose is never shown after the facts changed).
Twenty-two fixtures ship: 13 narratives (every KPI × persona combination that
reaches the narrative call in July), 5 extracts, 3 morning briefings, 1 intent.
Only `record_fixtures.py`, with `RECORD_FIXTURES=1`, may write them; an app
session running live never overwrites the curated offline demo. A full
re-record costs on the order of ₹25–30.

### 13.4 Cost

`telemetry.py` prices every live call from `response.usage` at list rates
(Haiku $1 / $5 per million input / output tokens; Sonnet $2 / $10) and converts
at ₹88 per dollar. A full investigation with both calls costs **₹1–3**.
Prompts carry only aggregates and masked snippets, so cost is independent of
data volume. Most eval cases stop at the signal gate and cost nothing: the
harness reports **0.28 model calls per investigation** on average.

## 14. Outcomes and the rupee number

The outcome table in Section 1 is decided by the gates in Section 12.2. Two
supporting computations live in `engine/economics.py`, the single place a rupee
figure is produced (it existed in three places, which is three chances for the
dashboard and the narrative to disagree):

- **Monthly impact** = (current − historical mean) × 30, defined only for
  `INR/day` KPIs. Thirty is a stated simplification; the KPI is a run-rate
  precisely so calendar length does not drive the comparison. For July revenue
  this is approximately −₹25.9 lakh per month.
- **Formatting** uses Indian numbering: ₹ lakh below one crore, ₹ crore above.

## 15. Governed dispatch: from conclusion to a message a person receives

The point of `engine/dispatch.py` is what it does **not** do: it does not let
the model decide who gets told. The model writes the sentence inside the
message; the contract decides the envelope.

**Proactive, never autonomous.** `python -m ops.watch` runs the same
multiplicity-controlled portfolio scan and the same live-lane rule on a
schedule, drafts into the Outbox whatever the contract routes for any material
movement that has no message yet, and escalates a live breach to the KPI owner.
It never sends; approval stays in the Outbox with a person. Drafting is
idempotent per KPI and month, and per breach and day, and every run is an event
in the `watch` stream.

### 15.1 Routing rules

| Outcome | Kind | To | Cc | Channel | Content |
|---|---|---|---|---|---|
| ACTIONS | `action` | The lever's declared **owner**, looked up in the contract from the action's lever text | The lever's declared **approver**, if one is required | slack | Movement line; "Recommended: …"; expected effect; how we will know it worked; decision right; confidence line; evidence ids |
| TENTATIVE | `low_regret` | Same lookup | Same | slack | Same, prefixed **FOR REVIEW** and framed as unconfirmed |
| ABSTAIN | `escalation` | The **KPI owner** | — | email | The escalation brief and "What the engine needs from a human: <question>"; no approval required because nothing is being instructed |
| NO SIGNAL, SPARSE | — | — | — | — | **Nothing.** Nothing happened, so say nothing |

The lever lookup (`engine/policy.lever_for`) matches the model's lever text to a
contract lever by substring, then by token overlap requiring at least two
shared non-stopwords and a clear winner. An action whose lever cannot be matched
is **surfaced as unroutable** rather than guessed: it is a gap in the contract,
worth showing.

### 15.2 The outbox (`services/outbox.py`)

Append-only, like the ledger: a draft, an approval and a send are **three
events** about one message, not three states overwritten in place, so "who sent
this, and when did they approve it" is answerable afterwards. Drafting is
idempotent per (investigation, lever): clicking twice does not queue the same
instruction to a person twice. `send()` **refuses** anything not in the
APPROVED state; that guard is what makes "nothing leaves without a person" true
rather than intended.

### 15.3 Transports (`services/transports.py`)

| Transport | Default? | What it does |
|---|---|---|
| **Dry run** | Yes | Records the send to `dispatched.jsonl` and reports "recorded, not delivered". The demo runs on this |
| **MCP** | Opt-in via `RATIONALE_DISPATCH=mcp` | Starts the configured Model Context Protocol server as a child process, **discovers** its tools, picks the posting tool by preference list and schema (Slack's official server exposes `slack_post_message(channel_id, text)`; others expose `send_message(channel, text)`), maps arguments by schema, and calls it. Passes `SLACK_*` and `RATIONALE_MCP_*` variables through explicitly (the SDK gives children a minimal environment). **Fails closed** on a missing required argument, a server that will not start, or any exception, and never breaks the app |

MCP is the wire, not the decision-maker: by the time a message reaches the
transport, the contract has chosen the recipient and a human has approved it.
The transport is proven end to end against a real local MCP server in
`tests/integration/test_mcp_transport.py`. Posting into an actual Slack
workspace additionally needs that workspace's credentials and has not yet been
done.

## 16. The learning loop and the abstain loop

### 16.1 Verdicts (`feedback.py`, the learning loop)

A user's thumbs-up or thumbs-down on an investigation is written as a
**verdict event** keyed to the investigation id, carrying the KPI, period, the
rank-1 driver and an optional comment. Reading the ledger folds the latest
verdict back onto the investigation it judges, so consumers see one row per
investigation with its vote.

Votes change three things, measurably:

| Where | Effect |
|---|---|
| Retrieval | An up-voted past conclusion scores ×1.5 as precedent; a down-voted one is **dropped** (×0). A conclusion a human marked wrong is actively harmful as precedent |
| Ranking | A driver a human previously confirmed for this KPI is promoted ×1.15; one they rejected is demoted ×0.6. Bounded on purpose: a correction is evidence about a past conclusion, not a veto over the statistics |
| Audit | The Ledger page shows the vote and comment against the investigation |

Before Round 3, an upvote and a downvote scored identically; feedback was text
the model might read while the UI promised it would shape future runs. The
integration tests now assert a rejection demotes and a confirmation promotes.

### 16.2 Answers (the abstain loop)

When the engine abstains it asks a specific question. That question now has an
**answer box** on the Investigation page. The answer is written as an **answer
event** with the actor (the signed-in role), the question, the answer, and
`confirms` ∈ {true, false, null}. On the next run:

- a **confirming** answer becomes a hypothesis with `source: human`, attributed
  to the actor, with the answer itself attached as evidence (`E1`), ranked with
  a statistical component of 0.8;
- a **ruling-out** answer becomes an **eliminated lead** shown as "ruled out by
  <actor>", and the abstention stands;
- **either way, no actions are manufactured**: there is no contract lever for
  "fix the tracking tag", and the engine does not invent one.

Measured on the planted tracking bug: confirm → abstain 0.438 becomes
**TENTATIVE 0.638**; rule out → stays 0.438. Not ACTIONS, deliberately:
testimony is not measurement, and "a person told us why and we have not yet
measured the effect" is precisely what tentative means. The hallucination guard
still applies to the **model**; a human answer does not open that door, and a
test asserts it.

In agent terms this is a perceive–reason–act cycle with the human as a sensor.
It is the only form of autonomy added in Round 3, and it keeps every decision
out of the model.

## 17. Streaming: the Live Feed replay and the live ingestion lane

Two different things, named separately on purpose.

**The Live Feed is a replay.** `engine/stream.py` walks the seeded daily data
from 18 June to 31 July 2026 in accelerated time. At each cursor date it
evaluates a 7-day rolling value of fulfilment SLA, revenue and complaints per
region against the trailing 60-day baseline with a ±2.0 z rule (the same shape of test the batch engine uses). The
North-West SLA and complaint series breach within days of the conveyor failure,
weeks before the monthly aggregate clears its bar. The detector is real; the
clock is not. Alarm buttons deep-link into the corresponding investigation.

**The live ingestion lane is real.** `python -m ops.ingest` is a **separate
process** that appends events (region, order value, shipments, breaches,
complaints) to `data/live/events.csv` at a configurable rate, with
`--inject-anomaly N` degrading one region's SLA after N events. The Lineage page
polls the lane and `services/live_ingest.verdict()` scores the trailing 40
events per region against a 20% breach threshold, refusing to call anything
until at least 20 events have arrived (the same discipline as the sparse
guard). The lane is deliberately isolated from the demo tables: mutating
`sales_orders` mid-demo would invalidate the recorded fixtures and move the
golden path's numbers.

## 18. State, persistence and caching

### 18.1 Where state lives

| State | Location | Format | Tracked in git? |
|---|---|---|---|
| Decision ledger (investigations, verdicts, answers) | `data/state/decision_ledger.jsonl` | Append-only JSON lines | No; **seeded at boot** from the Nov-2025 precedent so every machine reasons over the same corpus |
| Feedback mirror | `data/state/feedback.jsonl` | JSON lines | No |
| Outbox events | `data/state/outbox.jsonl` | JSON lines | No |
| Dry-run sends | `data/state/dispatched.jsonl` | JSON lines | No |
| Live ingestion lane | `data/live/events.csv`, `status.json` | CSV / JSON | No |
| IsolationForest verdicts | `data/cache/` | JSON, content-addressed | **Yes**, so a fresh clone does not pay the fit on its first click |
| Evaluation results | `data/eval_results.json` | JSON | **Yes**, so the Under the Hood panel survives a fresh clone |
| Recorded model responses | `llm/fixtures/*.json` | JSON | Yes |

When `RATIONALE_DB` names a PostgreSQL database, the first four streams live in
one `events` table there (stream, timestamp, JSON event) instead of the files,
through the same `store.py` interface. `RATIONALE_STORE=jsonl` keeps the streams
on disk while the numbers come from PostgreSQL; the evaluation harness and the
benchmark set it, so a scoring run never writes into a shared ledger.

`RATIONALE_STATE` points all of `data/state/` elsewhere. Tests use a temporary
directory; `eval.py` uses `data/state/_eval`. Without this, a test run or an
eval run would append to the very ledger it is measuring, and the retrieval
corpus would change under the assertions. Reading is tolerant of a torn line: a
malformed record is skipped, never allowed to break every investigation.

### 18.2 Which cache at which layer

| Layer | Mechanism | What | Why here |
|---|---|---|---|
| Storage | Materialised DuckDB tables | The four sources, typed | Removes re-parse for every consumer, including pytest and the API |
| Engine | `functools.lru_cache` | Contract, roles, source freshness, source stats (role-scoped), FDR family (role- and period-scoped), replay frames (role-scoped), and **every KPI series, driver metric, breakdown and the daily revenue frame (all role-scoped, returned as copies)**. The tables are a process-lifetime snapshot on either backend, so caching results changes nothing about freshness; it removes repeat questions, and on PostgreSQL each repeat was a 40 ms full-table aggregate | No Streamlit dependency, so identical behaviour in tests, `eval.py` and the API |
| Engine (CPU) | Content-hash **disk** cache | The IsolationForest verdict | Survives a process restart, which is exactly what a demo laptop needs. Fingerprint is an order-insensitive hash of the RBAC-filtered daily frame plus the period plus a model-version string, so it invalidates when the data, the role's visibility, or the model parameters change |
| View | `@st.cache_resource` | The LLM client, the metrics server | Unserialisable process singletons |
| Session | `st.session_state` | Investigation results | `investigate()` has side effects (it appends to the ledger and mints an id), so it is **never** cached process-wide: that would hand one user another's investigation |

**The RBAC cache-key rule:** any cached callable that reads role-scoped data
takes `role_id` as a parameter, and it is part of the key. `tests/rbac/
test_cache_isolation.py` reflects over cached signatures to assert it, and a
poisoning test primes every path as the analyst and reads as the restricted
role.

## 19. Telemetry and observability

`telemetry.py` records every model call (task, model, latency, input and output
tokens, cost, mode) and the latency of non-model engine steps, in a bounded
in-process list (5,000 records, trimmed with a preserved offset so per-session
bookmarks survive). Each browser session bookmarks its start so the Under the
Hood page reports **this session only**; the API's `/metrics/summary` reports
the process.

`metrics.py` mirrors engine behaviour to **Prometheus** when
`RATIONALE_METRICS=1`: investigations by KPI, outcome and role; wall-time and
confidence histograms; gate outcomes; detector votes; deterministic operations by
kind (SQL, statistics, ML, retrieval); model calls, tokens, cost and latency by
model; KPIs scanned and flagged. Everything no-ops if `prometheus_client` is
absent. `compose.yml` brings up Prometheus (5-second scrape) and **Grafana**
with a pre-provisioned "Engine Operations" dashboard whose headline panel is
*deterministic work versus model calls*: the core design claim, measured live.
These are operational metrics about the engine, deliberately not business KPIs.

## 20. The API: the engine as a service

`api/main.py` is ~110 lines because `investigate(kpi, period, role)` needed no
rearchitecting to be exposed. That is the claim the deployment story rests on:
Streamlit is one client of the engine, not the system.

| Endpoint | What it does | Security |
|---|---|---|
| `GET /healthz` | Liveness plus what this instance is configured to do (LLM mode, KPI and role counts) | — |
| `GET /kpis?role_id=` | The KPIs this role may ask about, with owners and drivers | Domain RBAC; unknown role → 404 |
| `GET /scan?role_id=&period=` | The portfolio sweep with multiplicity control applied | Domain RBAC |
| `POST /investigate` `{kpi_id, period, role_id}` | The reasoning pyramid; returns outcome, confidence, headline, body, actions, ranked hypotheses, evidence ids, method mix, model-call count, wall time | Restricted KPI → **403**; period validated by schema |
| `GET /sources` | Provenance per source: system, kind, live or extract, rows, as-of, fetch time | — |
| `GET /graph` | The contract as a knowledge graph: nodes, edges, counts | — |
| `GET /metrics/summary` | Process telemetry summary | — |

`tests/integration/test_api.py` asserts the API's answer matches the engine's,
that domain RBAC is enforced at the API and not only in the UI, and that row
RBAC holds through it (the restricted role gets strictly less revenue).

One asterisk on "stateless": every investigation appends to the ledger. With
the default JSONL store that is a local file, so replicas would each keep their
own ledger and learning loop. With `RATIONALE_DB` pointing at PostgreSQL
(Section 9.1a) the ledger is one shared append-only table and every replica
writes to it; `/healthz` reports which engine and which store are in use.

---

# Part D — Quality

## 21. Evaluation against planted ground truth

`eval.py` scores the engine against what the generator planted, on four axes a
sceptical stakeholder asks about, and writes `data/eval_results.json` for the
UI.

**The cases.** Six months (July 2026 and five controls, February to June) ×
six testable KPIs = 36 cases, plus the sparse KPI in every month. The controls
are there because a small, easy control set flatters a score: February is in
specifically because it produced an uncounted false positive before
multiplicity control, and June is in because six days of incident at the end of
the month do not move the aggregate past the bar, so it is a genuine control and
not a free pass.

**What counts as correct.**

| Axis | Rule |
|---|---|
| Detection | Flag exactly {revenue, fulfilment SLA, complaint rate, enterprise accounts, marketing conversion} in July and nothing in the controls; AOV stays normal; home-decor is handled as sparse |
| Root cause | The rank-1 hypothesis must be **the specific planted driver** (fulfilment SLA for revenue, complaints and enterprise accounts). For fulfilment SLA itself, which declares no drivers, the model-proposed hypothesis label must name the conveyor / WH-07 / backlog. The narrative body is **never** scored, because in offline mode it is a recorded fixture that already names the cause |
| Distractor rejection | Marketing conversion must **never** lead the revenue explanation |
| Abstention | Marketing conversion must abstain, and nothing else may |
| Calibration | Accuracy per confidence band |
| Gate separation | The margins in Section 12.2 |

**Results (2026-09-18, offline mode):**

| Metric | Value |
|---|---|
| Detection precision / recall / F1 | **1.0 / 1.0 / 1.0** (5 TP, 0 FP, 0 FN, 31 TN) |
| Sparse handled | 6 / 6 |
| Root-cause accuracy | 4 / 4 |
| Correct abstentions | 1 / 1, no false abstentions |
| Overall | 36 / 36 |
| Calibration | < 0.60: n = 32, mean 0.153, accuracy 1.0 · 0.60–0.75: n = 1 (0.715) · ≥ 0.75: n = 3, mean 0.79, accuracy 1.0 |
| Median runtime per case | 7.6 ms (most cases stop at the signal gate) |
| Mean model calls per case | 0.28 |

The harness was **mutation-tested**: substring-matching a bag of terms against
the label *and the body* was close to unfailable, so the root-cause rule was
tightened until a wrong rank-1 actually fails it. `python eval.py --check`
exits non-zero if any of precision, recall, root-cause accuracy or overall
accuracy falls below 1.0, and CI runs it on every push.

## 22. Tests, CI and the benchmark

**241 tests**, where Round 2 had a smoke script that printed everything and
asserted nothing. 226 run with no database at all; 15 need PostgreSQL and run
in CI against a service container.

| Area | Files | Tests | What they pin |
|---|---|---|---|
| `tests/unit/` | anomaly, causal_graph_forecast, confidence, contribution, explore, intent, live_ingest, retrieve, screening, sources, store, telemetry, vendor_dialects, warehouse_kind | 101 | The t-test and prediction SE; confidence cannot reach 1.0, 1-of-1 is not certainty, no-drivers is unassessable not half marks, unverifiable does not outscore verified; improving members are not focus areas, uniform movement is diffuse; BH matches the published 1995 example, both known false positives are suppressed, all five July incidents survive, the revenue margin is thin but holds, the family is role-scoped; "west" does not match "north-west", precedent is strictly past, self-authored precedent cannot crowd out documents; allowlisted sources and bound dates; the live lane refuses to call anything on too few events; the event store writes the same JSONL files it always did, tolerates a torn line, and round-trips through PostgreSQL; three systems in three formats land typed, the live order system is fetched over the wire in CI, and an unreachable source falls back visibly without leaking credentials; the causal estimate is negative with an interval clear of zero for the regional shock and not identifiable for the national one; the graph has no dangling edges and names the right owners; the forecast is anchored on the analysis month |
| `tests/rbac/` | rbac, cache_isolation | 16 | Row security is in the SQL; the restricted role sees strictly less revenue; hidden KPIs are hidden; masking reaches retrieved evidence, not just the screen; every cached path is role-keyed and a primed cache does not leak across roles, including the IsolationForest cache and the replay ticker |
| `tests/integration/` | pyramid_paths, learning_loop, abstain_loop, dispatch, mcp_transport, api, backend_parity, watch, export_bi | 65 | The golden path is TENTATIVE with the right lead; the measurement artifact does not corroborate; the abstain, sparse and no-signal paths; the executive never sees a standardised score; a correction demotes and a confirmation promotes; a confirming answer changes the verdict and carries provenance, a ruling-out keeps the abstention; recipient and approval come from the contract; nothing sends without approval; the MCP flow posts through a real local server, discovers the right tool, and fails closed; the PostgreSQL parity suite of Section 9.1a, including the INSERT-only grant; the watcher drafts every material movement once, escalates a live breach once per day, and never sends |
| `tests/ui/` | test_app, test_snapshots | 36 | Headless `AppTest` runs of every page for every role; the ask box fires only on submit; the sales head cannot reach restricted KPIs; the ledger masks for the viewer; dark mode repaints the charts; and **21 rendered-text snapshots** (HTML stripped; latency, timestamps, ids and money normalised) that must be byte-identical after any refactor |
| `tests/test_layering.py` | — | 23 | The architectural boundaries in Section 7 |

**CI** (`.github/workflows/ci.yml`, on every push and pull request, Python 3.13):

1. `pytest tests/unit tests/rbac tests/integration` (the fast suite, with a PostgreSQL 16 service container behind `RATIONALE_TEST_PG`)
2. `pytest tests/ui` (headless UI and snapshots)
3. `python eval.py --check` (accuracy must not regress)
4. `python -m ops.bench --check --json` (latency budget and correctness under concurrency)

**The benchmark** (`ops/bench.py`) has two jobs: per-stage timings for one
investigation, so the numbers in the UI and the deck come from a stopwatch; and
p50/p95 against N concurrent investigations in threads against the shared
DuckDB handle, which is precisely the path that has to be thread-safe, so it
doubles as a correctness check. Budgets: scan 250 ms, warm investigation
1,500 ms, p95 4,000 ms.

The Docker image runs the unit and integration suites **at build time**, so a
broken engine fails the build rather than the demo.

## 23. Performance

| Measurement | Before Round 3 | After |
|---|---|---|
| Every KPI query | Re-parsed the 4.9 MB CSV through a view on each call (~54 ms, no warm-up) and cast dates per row | Scan of an in-memory typed table; one ~200 ms build per process |
| Flagship revenue click, warm | ~12 s (IsolationForest fit ~7 s + first-use `sklearn` import ~9 s on the first click) | Sub-second; a cache hit returns before scikit-learn is imported |
| Dashboard scan | ~930 ms per widget interaction | ~250 ms budget, met |
| Throughput, one process | not thread-safe | ~8–9 requests/s; p50 243 ms at N = 1 rising to 1.7 s at N = 16; **zero wrong answers at every level** |

**The two engines, same laptop, same session** (2026-09-19; cold means every
engine result cache cleared first, which is what the first click of a session
pays):

| | DuckDB | PostgreSQL |
|---|---|---|
| KPI series query, cold | 6–12 ms | 40–45 ms |
| Portfolio scan, cold | 33–40 ms | 96–106 ms |
| Investigation, first click of a session (cold) | ~120 ms | ~0.4–0.6 s |
| Investigation, every click after (warm; no SQL runs) | ~45 ms | ~45 ms |
| Investigation p50 at N = 1 | 100 ms | 171 ms |
| Investigation p50 at N = 16 | 1.8 s | 1.7 s |
| Throughput at N = 16 | 8.1 req/s | 8.1 req/s |
| Wrong answers under contention | 0 | 0 |
| `eval.py`, median per case | 1 ms | 1 ms |

PostgreSQL is three to five times slower per query: each of an investigation's
roughly twenty-five small queries re-aggregates 85k rows row by row and crosses
a network hop, where DuckDB is a vectorised function call in the same process.
That cost is paid once. The engine keeps role-keyed result caches for every
KPI series, breakdown and daily frame (Section 18.2), so after the first click
of a session an investigation issues no SQL at all and the two engines are
indistinguishable. Under sixteen concurrent investigations both deliver the
same throughput, because the Python process, not the database, is the
bottleneck there. Zero wrong answers on either. The benchmark reports cold and
warm figures separately so the cache cannot hide the engine underneath it.

The single-process curve saturates at modest concurrency (Python GIL; DuckDB
releases it during query execution). That is the right result to present: the
service is stateless given its inputs, so past that point you add replicas.
The one genuinely shared piece of state is the ledger write (Section 20).

---

# Part E — Running and deploying

## 24. Running it: modes, environment variables, commands

```bash
pip install -r requirements.txt          # Python 3.12 / 3.13
streamlit run app.py                     # the client, http://localhost:8501
uvicorn api.main:app --port 8000         # the API, http://localhost:8000/docs
python eval.py                           # the accuracy harness (--check to gate)
python -m ops.bench --json               # latency + concurrency (--check to gate)
python -m ops.ingest --rate 2 --inject-anomaly 40   # the live lane, in a second terminal
python -m ops.pg_local init              # optional: PostgreSQL as a user process, loaded and provisioned
python -m ops.watch                      # proactive pass: scan, draft into the Outbox, never send
python -m ops.export_bi                  # BI hand-off: every output as CSV + Parquet in data/exports/
python -m ops.warehouse verify --url ... # contract SQL on Snowflake / Databricks / any warehouse == DuckDB?
python -m pytest                         # 179 tests
python record_fixtures.py                # re-record the offline demo (needs a key; ~₹25–30)
```

No key is needed. With no key the app runs on fixtures; unplug the network and
the demo is unchanged.

| Variable | Effect |
|---|---|
| `ANTHROPIC_API_KEY` | Enables live mode (or paste it in the sidebar; held in memory only) |
| `MOCK_MODE=1` | Forces offline mode even with a key. Tests and eval set it |
| `RATIONALE_STATE=<dir>` | Relocates the ledger, feedback, outbox and dispatch logs |
| `RATIONALE_DB=postgresql://…` | Runs the analytics and the event streams on PostgreSQL (Section 9.1a). Unset: DuckDB and JSONL. Any other SQLAlchemy URL (`snowflake://`, `databricks://`, `mssql+pyodbc://`, `bigquery://`, `postgresql+psycopg://`) runs the contract SQL on that engine through its driver |
| `RATIONALE_STORE` | `jsonl` keeps the event streams on disk while `RATIONALE_DB` supplies the numbers; a DSN sends them elsewhere |
| `RATIONALE_PG_BIN`, `RATIONALE_PG_PORT` | Where `ops/pg_local.py` finds the PostgreSQL binaries, and the port it uses (default 5433) |
| `RATIONALE_TEST_PG` | An owner DSN; enables the PostgreSQL store and parity tests |
| `RATIONALE_OMS_DSN=postgresql://…` | Keep DuckDB as the engine but fetch the order system live from this database at start-up (Section 9.1). Unset: the nightly extract is used and the Lineage page says so |
| `RATIONALE_METRICS=1` | Exposes Prometheus metrics on `:9108` (`RATIONALE_METRICS_PORT` to change) |
| `RATIONALE_DISPATCH=mcp` | Selects the MCP transport instead of dry run |
| `RATIONALE_MCP_COMMAND` | How to start the MCP server, e.g. `npx -y @modelcontextprotocol/server-slack` |
| `RATIONALE_MCP_CHANNEL` | Destination handle (a Slack channel id) |
| `RATIONALE_MCP_TOOL` | Optional: force a tool name instead of discovering one |
| `SLACK_BOT_TOKEN`, `SLACK_TEAM_ID` | Passed through to the Slack MCP server. Set in the shell; never paste into a chat or commit |
| `RECORD_FIXTURES=1` | Allows fixture writes (set by `record_fixtures.py` only) |
| `RECORD_SNAPSHOTS=1` | Re-baselines the UI snapshots |

Dependencies are upper-bounded on purpose (`streamlit>=1.49,<2`, `duckdb<2`,
`pandas<4`, `anthropic<2`, …) so a hosted platform resolving to a new major
cannot break a deployed demo. `.streamlit/config.toml` sets theme only; setting
`[server]` there once made a hosted deploy block on Streamlit's first-run prompt.

## 25. Deployment and the scale story

### 25.1 Today

- **One container, two entrypoints.** `Dockerfile` (python:3.13-slim) bakes in
  the dataset and fixtures, runs the unit and integration tests at build,
  exposes 8501 and 8000, and has a health check. `compose.yml` brings up the
  Streamlit client, the same image as the FastAPI service, Prometheus and
  Grafana: `docker compose up`.
- **A second engine, no Docker required.** `python -m ops.pg_local init` runs
  PostgreSQL as a user process and loads the data; `RATIONALE_DB` switches the
  app, the API, the evaluation harness and the benchmark to it. Parity is
  tested in CI (Section 9.1a).
- **Hosted demo.** `https://rationale-ai-acc.streamlit.app/` on Streamlit
  Community Cloud, kept awake by a scheduled ping every four hours. **It runs
  the `main` branch, which is still the Round-2 build**; the Round-3 work
  described here is on `round3-hardening` and has not been merged or deployed
  there yet.

### 25.2 How each component maps to a client's stack

| Prototype | Production | What does **not** change |
|---|---|---|
| DuckDB over CSV | Lakehouse or warehouse (Snowflake, BigQuery, Databricks); DuckDB stays as the CI fixture engine. PostgreSQL is already a second, parity-tested engine behind the same seam | The contract SQL is the executable definition; `engine/db.py` is the one seam |
| CSV tables | dbt incremental marts, pre-aggregated to `O(months × dimensions × members)` | **Rows scanned per investigation stay flat as the fact table grows**; you never scan 100M rows to explain a KPI |
| `roles.yaml` + `{where}` injection | Warehouse-native row-access and column-masking policies bound to Entra/Okta identity | The invariant: the filter is in the query plan, never in the UI; masking before the prompt |
| Keyword retrieval | Hybrid BM25 + embeddings, ACLs applied at the index; the deterministic scorer kept as the reproducible CI baseline | Evidence is counted, not scored, by the model |
| Fixtures | Two distinct things: a **semantic prompt cache** keyed on a content hash of the fact bundle (cost), and a **golden-set regression corpus** replayed in CI (quality) | Model IDs pinned; prose changes, numbers do not |
| JSONL ledger and outbox | **Available today:** the same streams in a PostgreSQL `events` table with an INSERT-only application role. At scale: tenant-partitioned, or Kafka + Iceberg | The ledger as audit record and learning signal |
| Streamlit | One client. Stateless FastAPI `POST /investigate` behind a load balancer; a worker queue; a nightly scheduled scan | The pyramid, the gates, the abstention |
| Single tenant | `tenant_id` as the leading partition key and cache namespace, which is the `role_id`-in-every-cache-key rule scaled up | Already enforced by a test |

**Streaming versus batch, as a design position:** stream **detection** (a
windowed z-rule per region, textbook Flink) and batch **diagnosis** (which needs
the full corpus, a stable baseline and the ledger).

**The platform seams, as they stand.** Custom in the middle, hybrid at four
edges: any SQLAlchemy warehouse URL as a live source (`kind: sql`) or as the
engine the contract SQL runs on (`RATIONALE_DB`), proven against PostgreSQL and
SQLite; the ledger on PostgreSQL; and `python -m ops.export_bi`, which writes
the scan, the series, the verdicts, the provenance, the contract graph and the
evaluation cases as CSV and Parquet for Tableau, Power BI, Looker or Qlik. The
vendor URLs for Snowflake, Databricks SQL, Fabric and BigQuery are listed in
`docs/PLATFORMS.md`. For Snowflake and Databricks the drivers are installed
(`requirements-warehouse.txt`), the two dialect differences are handled in one
place each (Snowflake returns upper-case result names; Databricks spells the
cast `::DOUBLE`), and `python -m ops.warehouse smoke | load | verify` loads the
sources and compares every KPI series with DuckDB. That tool is run end to end
against PostgreSQL in the test suite, and **against Snowflake for real** on a
trial account: 85k rows loaded in about 9 s, all 18 series identical to DuckDB
after two findings were fixed (the bulk loader's date types; Snowflake's
fixed-point division in the complaint-rate ratio, now stated as double
arithmetic in the contract), the golden path TENTATIVE 0.715 with the same
causal estimate, the first investigation 22 s over the wire and the second
0.2 s from the caches. Databricks has the same tooling and no account yet.
BigQuery is a supported source, not a supported engine.

### 25.3 Rehearsed answers

- *"How does this deploy for 500 analysts?"* The engine is a stateless service
  behind a load balancer: here is the container, the API, and the measured
  curve. Per-investigation cost is flat in data volume because investigations
  read a pre-aggregated mart. Session state moves to Redis; the ledger moves to
  a shared transactional store, and that is the one shared write.
- *"Our stack is Azure."* It is containerised: Container Apps or AKS; Fabric or
  Synapse for the mart; Entra ID with row-access policies replacing the
  `{where}` injection; the model through the client's own gateway. The contract
  and the pyramid do not change.
- *"Data residency and PII?"* Masking happens before the prompt; the only thing
  sent to a model is aggregates plus masked snippets. The engine runs fully
  offline on fixtures, so an air-gapped deployment is a configuration, not a
  port.
- *"Cost at scale?"* ₹1–3 per investigation; 10,000 a month is tens of thousands
  of rupees before a semantic cache. Instrumented, not estimated. And 100% of
  the numbers cost nothing, because no model produces one.
- *"Why Streamlit?"* It is the analyst-facing client, not the system. The API
  is the demonstration.

---

# Part F — Honesty

## 26. What is real, what is replayed, what is simulated

| Thing on screen | Status |
|---|---|
| Every number: series, z, p, q, contributions, driver checks, correlations, confidence, ranks, rupee impact | **Computed live** for the chosen month and role, from the data, on every run |
| The data | **Synthetic**, seeded, with known causes planted. No real business has been connected |
| The documents and market events | **Written for the scenario**, including two red herrings |
| The narrative and evidence mapping (offline) | **Recorded** from one real Claude run, replayed by content-addressed key; any month other than July, or any answered abstention, falls to the deterministic template |
| The narrative and evidence mapping (live) | Real calls, bounded to 20 s and one retry |
| The Live Feed | **A replay** of seeded daily data in accelerated time. The detector is real; the clock is not |
| The live ingestion lane on the Lineage page | **Real**: a separate process writes rows the app has never seen |
| Dispatch | Routed and approved for real; **delivered as a dry run** by default; MCP delivery proven against a local server, not yet against a Slack workspace |
| The PostgreSQL backend | **Real and optional.** One variable switches engine and ledger; every KPI series and all 36 evaluation cases are identical to DuckDB. Slower per query on a laptop, and not a substitute for a warehouse |
| The sources | **Heterogeneous and reconciled.** The order system is a live PostgreSQL fetched at start-up when `RATIONALE_OMS_DSN` is set, otherwise its nightly extract, and the page says which; the WMS and marketing systems are CSV extracts; the CRM is a JSON event feed. The data inside them is synthetic |
| The learning loop and abstain loop | **Real**: verdicts and answers change retrieval, ranking and the verdict, measurably |
| Users | **None** outside the team have used it |

## 27. Known limitations and roadmap

In order of how much each would matter, from `docs/DESIGN_DECISIONS.md` D22:

1. **No real users.** The pilot plan is the path to changing that, starting with
   the contract workshop.
2. **No seasonality.** The baseline is stationary over ≤ 12 months; STL or
   seasonal baselines are the roadmap item.
3. **Causal inference only where the data identifies it.** The driver checks
   test concurrent movement and say so; the one causal estimate is a
   difference-in-differences that needs an untreated region as a control and
   refuses when there is none (Section 11.5).
4. **Prose numbers are not verified against the facts.** The model can still
   mis-state a figure it was given. Cheap to add; not yet done.
5. **Retrieval is keyword matching**, deliberately, to keep fixtures stable.
6. **The MCP transport has not posted to a real Slack workspace.** Needs
   credentials.
7. **Contract authoring is a human workshop** we have not run.
8. **The answered-state narrative is the deterministic template**, not model
   prose; one live call would record the fixture.

Also worth knowing: the data ends 25 August 2026 while the contract declares
daily and weekly refresh; there is no late-arriving-data handling; there is no
drift monitoring on the IsolationForest flag rate; and the hosted app is a
Round-2 build until `main` is updated.

Roadmap beyond those: predictive what-if mode; warehouse connectors behind the
`engine/db.py` seam; scheduled proactive scans; SSO; calibration against a
client's labelled incident history; a freshness gate that refuses to score a
period whose source is behind its declared refresh.

## 28. Glossary

| Term | Meaning here |
|---|---|
| **Semantic contract** | The YAML that defines each KPI's SQL, materiality, drivers, levers, owners, approvers, lineage and access. Read by the engine, authored by humans |
| **Materiality** | The business bar a movement must clear: both a statistical threshold (\|z\|) and a percentage change |
| **Family-wise / FDR** | Testing many KPIs at once inflates false alarms; Benjamini–Hochberg controls the expected share of flagged movements that are spurious (q = 0.10) |
| **q-value** | The BH-adjusted p-value; the smallest FDR at which this movement would be flagged |
| **Driver** | Another KPI or metric the contract says influences this one, with a declared direction |
| **Co-moves / contradicts / quiet** | Whether a driver moved as predicted, the other way, or not at all, in the analysis month |
| **Unexplained** | A co-moving driver none of whose own drivers moved; counts at half weight |
| **Focus / diffuse** | Whether the movement is concentrated in ≤ 2 members of a dimension (≥ 35% each, in the harmful direction) or spread evenly |
| **Hypothesis** | A candidate explanation, sourced from a driver, a document (model-proposed), an external event, or a human answer |
| **Evidence gate / action gate** | Confidence 0.60 to state a cause; 0.75 to recommend actions |
| **Abstain** | The outcome when confidence is below the evidence gate: the engine asks a question instead of asserting a cause |
| **Lever** | A controllable action the contract lists for a KPI, with an owner and an approval right |
| **Outbox** | The queue of drafted messages awaiting human approval before dispatch |
| **Dry run** | The default transport: records a send without delivering it |
| **MCP** | Model Context Protocol; the wire over which an approved message reaches Slack, email or a ticketing system through a standard server |
| **Ledger** | The append-only record of every investigation, verdict and answer; also part of the retrieval corpus as precedent |
| **Event store** | `store.py`: the four append-only streams, as JSONL files by default or one PostgreSQL table |
| **Fixture** | A recorded model response replayed offline by content-addressed key |
| **Sanitizer** | The deterministic filter that strips statistics vocabulary and clutter from anything the model wrote |
| **Persona** | The narrative register for a role: analyst, executive or department head |

---

# Appendix A: Repository map with sizes

Python, excluding data and snapshots. Approximately 9,600 lines in total.

| Area | Lines | Contents |
|---|---|---|
| `engine/` | 2,617 | 16 modules: pyramid, db, sources, anomaly, screening, stats_ml, contribution, drivers, retrieve, confidence, economics, policy, dispatch, explore, stream, cache |
| `ui/` | 2,103 | theme, context, common, 4 components, 8 pages |
| `tests/` | ~2,600 | 27 files, 241 tests |
| top level | 1,237 | `app.py` (192), `store.py`, `feedback.py`, `telemetry.py`, `metrics.py`, `eval.py`, `record_fixtures.py` |
| `services/` | 462 | scan, intent, outbox, transports, live_ingest |
| `llm/` | 340 | client, prompts, fallback; 22 fixtures |
| `ops/` | 628 | bench, ingest, pg_local; Prometheus and Grafana provisioning; compose for the ops stack |
| `api/` | 121 | the FastAPI service |
| `data/` | — | 4 CSVs (~4.9 MB), 10 documents, 3 market events, the generator, tracked eval results and ML cache |
| governance | — | `contracts/kpi_contract.yaml`, `roles.yaml` |
| docs | — | this guide, README, technical documentation, project report, demo and video scripts, and the five `docs/` pages |

Git: 39 commits since 2026-08-30; 18 of them on `round3-hardening`.

# Appendix B: Every tunable constant, in one table

| Constant | Value | Where | What it governs |
|---|---|---|---|
| `min_history` (default) | 6 months | contract / `anomaly.py` | Below this, SPARSE |
| `materiality.min_abs_z`, `min_pct` | per KPI (e.g. 2.0 / 3% revenue; 2.5 / 7% AOV) | contract | The signal gate's business bar |
| `FDR_Q` | 0.10 | `screening.py` | Benjamini–Hochberg level |
| `DRIVER_Z` | 1.5 | `drivers.py` | A driver "moved" |
| OLS interval | 90% (two-sided t) | `stats_ml.py` | Forecast check |
| IsolationForest | 200 trees, contamination 0.03, seed 42, ≥ 90 train days, ≥ 10 test days, rule > 10% of days | `stats_ml.py` | The daily-grain detector |
| `MODEL_VERSION` | `iforest-v1-200est-c0.03-seed42` | `cache.py` | Part of the cache key |
| `FOCUS_SHARE`, `MAX_FOCUS` | 0.35, 2 | `contribution.py` | When a member is a focus |
| Cancellation guard | \|net\| ≥ 0.5 × gross | `contribution.py` | When shares are reported |
| Retrieval `k` | 6 | `retrieve.py` | Snippets returned |
| `MAX_LEDGER_SNIPPETS` | 2 | `retrieve.py` | Cap on self-authored precedent |
| `VOTE_WEIGHT` | up 1.5 / down 0.0 / none 1.0 | `retrieve.py` | Precedent weighting |
| `HUMAN_ANSWER_WEIGHT` | 3.0 | `retrieve.py` | Human answer boost |
| Focus-region term weight | 2.0 (tags 1.0) | `retrieve.py` | Query weighting |
| Snippet length | 700 chars | `retrieve.py` | Evidence shown and sent |
| `WEIGHTS` | signal 0.35, coverage 0.35, evidence 0.30 | `confidence.py` | The score |
| Signal cap | \|z\| / 3 | `confidence.py` | Full signal at \|z\| ≥ 3 |
| Contradiction penalty | 0.25 per contradicting driver | `confidence.py` | Coverage |
| `UNEXPLAINED_WEIGHT` | 0.5 | `confidence.py`, `pyramid.py` | Coverage credit and rank strength |
| `ASSESSED_FLOOR` | 0.75 | `confidence.py` | Verifiability discount |
| `MAX_CONFIDENCE` | 0.95 | `confidence.py` | Hard ceiling |
| `EVIDENCE_GATE`, `ACTION_GATE` | 0.60, 0.75 | `confidence.py` | Outcomes |
| `EARLY_EXIT` | 0.90 | `pyramid.py` | Skip Level 3 |
| `SPARSE_CONFIDENCE` | 0.25 | `pyramid.py` | Sparse path |
| Rank strength | 0.5 stat + 0.3 evidence + 0.2 external; stat = \|z\|/4, human 0.8, other 0.4 | `pyramid.py` | Hypothesis ranking |
| `PRECEDENT_ADJUST` | up ×1.15, down ×0.6 | `pyramid.py` | Learning loop in ranking |
| `IMPACT_DAYS` | 30 | `economics.py` | Monthly rupee impact |
| Sanitizer caps | headline 1 sentence / 140 chars; body 4 / 520; fields 110–220 | `pyramid.py` | Prose length |
| `LIVE_TIMEOUT_S`, `LIVE_MAX_RETRIES` | 20 s, 1 | `llm/client.py` | Bounded live path |
| Models | `claude-haiku-4-5` (extract, 1,500 tok), `claude-sonnet-5` (narrative, 8,000 tok, effort low) | `llm/client.py`, `pyramid.py` | The two calls |
| `PRICING`, `USD_INR` | Haiku $1/$5, Sonnet $2/$10 per M; ₹88 | `telemetry.py` | Cost |
| `MAX_RECORDS` | 5,000 | `telemetry.py` | Bounded telemetry |
| Replay | 2026-06-18 → 2026-07-31; roll 7 d; baseline 60 d; z 2.0 | `stream.py` | Live Feed |
| Live lane | window 40 events; breach 20%; min 20 events | `live_ingest.py` | Lineage page verdict |
| Bench budgets | scan 250 ms; warm 1,500 ms; p95 4,000 ms | `ops/bench.py` | CI gate |
| Eval thresholds | precision, recall, root-cause, overall all 1.0 | `eval.py` | CI gate |
| `PERIODS` | 2026-02 … 2026-07 | `ui/common.py` | Analysis windows offered |

# Appendix C: Design-decision cross-reference

Each section above rests on decisions argued in full, with the alternative
considered and the judge's likely question, in `docs/DESIGN_DECISIONS.md`.

| Topic | Decisions |
|---|---|
| The model never computes a number | D1 |
| The contract as executable definition | D2 |
| Gates and abstention | D3, D12, D13 |
| The four-level pyramid and early exit | D4 |
| RBAC in SQL, masking before the prompt | D5 |
| Fixtures and offline safety | D6 |
| Synthetic data and the evaluation harness | D7, D18 |
| The ledger as precedent | D8, D16 |
| Materialised tables and the ML cache | D9 |
| Multiplicity control at q = 0.10 | D10 |
| The t-test with prediction SE | D11 |
| Co-movement not causation; unexplained drivers | D14 |
| Contribution: direction-aware focus, additivity | D15 |
| The learning loop | D17 |
| Prose and technical forms | D19 |
| Architecture, tests, CI, benchmark | D20, D21 |
| What is not solved | D22 |
| Governed dispatch and MCP | D23, D24 |
| Lineage and the live lane | D25 |
| Is this an agent? | D26 |
| The abstain loop | D27 |
| A second engine (PostgreSQL) behind the same contract; the ledger's shared home | D28 |
| Heterogeneous sources reconciled at ingestion, with provenance | D29 |
| Causal inference, honestly scoped (difference-in-differences) | D30 |
| The forecast's voice | D31 |
| The contract as a knowledge graph; exposure | D32 |
| Proactive alerts: the watcher | D33 |
| Alternatives considered; the action chain | D34 |
| Platform: custom in the middle, hybrid at proven seams | D35 |
