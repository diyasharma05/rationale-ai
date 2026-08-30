# Rationale.AI — Project Report
### Team Rational.ai · Accenture Innovation Challenge 2026 · Round 2 · Track 3 (BusinessIntelligence.ai)

> **One line:** A confidence-driven KPI intelligence-to-action engine that detects material
> movements with SQL + statistics + ML, escalates through a four-level reasoning pyramid with
> confidence gates, and either recommends grounded actions — or **abstains and asks a human**.
> The LLM writes sentences; it never computes.

---

## 1. The problem (Round-1 recap → Round-2 build)

Enterprises watch dashboards that say *what* moved, never *why*. Answering "why did revenue
fall?" takes an analyst 2–5 days of stitching silos, reading tickets, and reconciling
definitions — and every department gives a different answer. Our Round-1 pitch: a reasoning
engine that escalates from live KPIs → company context → external signals → human experts,
with a confidence gate at every step. **Round 2 asked for a working prototype. This is it.**

---

## 2. Core design principle (the judged one)

**The LLM is never the source of quantitative truth.**

| Job | Method | Tool |
|---|---|---|
| KPI series, contributions, breakdowns | SQL from the governed contract | DuckDB |
| "Is this abnormal?" | z-score + materiality, OLS forecast interval | numpy |
| Day-level anomaly cross-check | IsolationForest (5 per-region models) | scikit-learn |
| Driver testing | concurrency z + Pearson co-movement | numpy |
| Confidence score + all gates | fixed weighted formula | Python |
| Evidence retrieval | weighted keyword TF ranking | Python |
| Reading documents, mapping evidence → hypotheses | LLM | Claude Haiku 4.5 |
| Persona narrative, action wording, escalation brief | LLM | Claude Sonnet 5 |

Every number is computed upstream and passed to the model **verbatim**. A typical
investigation: **~18 SQL queries · ~10 statistical tests · 5 ML models · 6 documents
retrieved · exactly 2 LLM calls** — the mix is displayed on every result ("What built this
answer").

---

## 3. Architecture

```
                        ┌────────────────────────────────────────────┐
                        │        SEMANTIC CONTRACT (YAML)            │
                        │ definitions · SQL · thresholds · drivers   │
                        │ levers+decision rights · lineage · access  │
                        └─────────────────┬──────────────────────────┘
 DATA (4 sources, 3 systems)              │ executed, not documentation
 ┌─────────────┐  ┌─────────────┐         ▼
 │ OrderDB OMS │  │LogiTrack WMS│   ┌───────────────── ENGINE (non-LLM) ─────────────────┐
 │ txn · daily │  │daily·region │   │ L1 SIGNALS: anomaly ensemble (z / OLS-PI /         │
 └──────┬──────┘  └──────┬──────┘   │    IsolationForest) → contribution → driver checks │
 ┌──────┴──────┐  ┌──────┴──────┐   │    ── SIGNAL GATE (statistical + ₹ materiality) ── │
 │ RelateCRM   │  │ RelateCRM   │──▶│ L2 CONTEXT: retrieval over tickets/transcripts/   │
 │ events·wkly │  │ mktg weekly │   │    decision ledger → LLM maps evidence→hypotheses  │
 └─────────────┘  └─────────────┘   │ L3 EXTERNAL: market-event matching (rules)         │
        +                           │    ── EVIDENCE GATE 0.60 · ACTION GATE 0.75 ──     │
 unstructured docs (10)             │ L4 ESCALATION: expert brief when gates fail        │
 market events feed                 └───────────────┬─────────────────────────────────── ┘
 decision ledger (memory)                           │ facts, ranked hypotheses, confidence
                                                    ▼
                                    ┌──────── LLM LAYER (words only) ────────┐
                                    │ Haiku 4.5: evidence mapping (JSON)     │
                                    │ Sonnet 5: persona narrative + actions  │
                                    │ deterministic sanitizer caps/de-slops  │
                                    │ fixtures → full offline mock mode      │
                                    └───────────────┬────────────────────────┘
                                                    ▼
                              STREAMLIT UI (Accenture theme, dark/light)
                    dashboard · investigation · decision ledger · under-the-hood
```

---

## 4. Data & scenario design (synthetic, seeded, reproducible)

- **85,222 orders**, 13 months (Aug 2025 – Aug 2026), 5 regions, 3 segments, 40 enterprise
  accounts; 4 sources with **different grains and refresh cadences** (transaction / daily×region
  / event / weekly×region) — a Round-2 minimum requirement.
- **10 unstructured documents** (tickets, an exit-call transcript, ops notes, a Slack thread,
  a past postmortem, 2 red herrings) + a market-event feed + a pre-seeded decision ledger.
- **Planted July-2026 story** (matches our Round-1 deck): a WH-07 conveyor failure in
  North-West degrades fulfilment → complaints spike → two enterprise accounts churn to a
  competitor's new express service → revenue falls. Plus a marketing tracking bug and a
  6-week-old product category.

**What the detectors actually measure (July 2026):**

| KPI | Movement | z | Outcome |
|---|---|---|---|
| Net Revenue (daily run-rate) | −7.0% (≈ −₹25.9L/month) | −2.16 | ✅ actions @ **0.83** |
| Fulfilment SLA % | 92% → 88.3% | −9.75 | ✅ actions @ **0.82** |
| Complaint Rate | **+29.0%** | +2.96 | ✅ actions @ **0.99** |
| Enterprise Active Accounts | 40 → 37 | −6.97 | ✅ actions @ **1.00** |
| Marketing Conversion | −15.7% (drivers healthy) | −26.7 | ⛔ **abstains @ 0.35**, asks a human |
| Home-Decor Revenue (new) | 6 weeks old | n/a | ◔ sparse guard, zero LLM tokens |
| Average Order Value | −3.5% | −0.82 | ✓ signal gate rejects as noise |

Every Round-2 scenario requirement (multi-factor movement, abstention, sparse history,
role-based security, noise rejection) is a **planted, reproducible** demo path.

---

## 5. The reasoning pipeline (one investigation, step by step)

**"Why did revenue fall?"** (typed in plain English — hybrid intent routing picks the KPI)

1. **Level 1 — Cross-functional signals** *(SQL + statistics + ML, ~200 ms)*
   - Contract SQL executed (row-security clause visibly injected).
   - **Detector ensemble, 3 independent tests**: z = −2.16 (gate ±2.0) → FLAG; actual
     ₹13.86L/day vs OLS forecast ₹14.79L [90% PI 13.87–15.70] → FLAG; IsolationForest
     (5 regional models, trained on trailing year of daily data) → FLAG, **localizes to
     North-West** (4/31 anomalous days).
   - Contribution: **North-West = 86% of the movement**, enterprise segment leading.
   - Driver check from the contract: SLA ↓, complaints ↑, enterprise accounts ↓, marketing ↓
     → 4 candidate hypotheses, each with a 12-month co-movement statistic.
2. **Level 2 — Company context** *(retrieval + Haiku)*
   - 6 documents retrieved from tickets/transcripts/**decision ledger** (the "Recall" step —
     a Nov-2025 postmortem with a proven 3PL playbook surfaces).
   - Claude maps snippets → hypotheses; the mapping is **counted in Python**, never scored
     by the model. Marketing hypothesis gets zero evidence → stays UNCORROBORATED.
3. **Level 3 — External signals** *(rules)*: competitor's express-delivery launch matches
   region + tags → corroborates the churn/fulfilment story.
4. **Gates**: confidence 0.83 = 0.35·signal + 0.35·coverage + 0.30·evidence →
   evidence gate 0.60 ✓ → action gate 0.75 ✓ → **ACTIONS**.
5. **Narrative** *(Sonnet, effort=low)*: persona-specific, numbers passed verbatim,
   [E#] citations clickable; actions grounded in contract levers **with decision rights**
   (owner + who must approve). Every answer carries **"What could change this answer."**
6. If gates fail → **Level 4**: the engine abstains, asks the single most useful clarifying
   question, and generates a ready-to-send expert escalation brief.

---

## 6. Trust machinery (what makes it different)

- **Hallucination guard**: an LLM-proposed hypothesis cannot rescue confidence when the
  contract's declared drivers stayed quiet — it is displayed as an "unvalidated lead" instead
  of evidence. (Demonstrated live on the marketing scenario.)
- **No echo chambers**: same-period ledger entries are excluded from retrieval; "Recall"
  means past precedent only.
- **Deterministic de-slop sanitizer**: whatever the model returns, the UI shows ≤4 short
  sentences; sentences containing engine/statistics vocabulary are dropped in code.
- **Calibrated humility**: abstention is a first-class outcome with its own UI, not an error.
- **Noise filter**: AOV moved −3.5% and is deliberately *not* flagged — the answer to
  alert fatigue.
- **Learning loop**: 👍/👎 + corrections land in the decision ledger and are retrieved by
  future investigations.

---

## 7. Security & governance (three layers, enforced in the query layer)

| Layer | Mechanism | Demo |
|---|---|---|
| **Row-level** | WHERE clause injected into every SQL query per role | Sales Head sees only North/North-West numbers — visible in the displayed SQL |
| **Column-level** | Enterprise account names → stable ACCT-codes, applied to evidence **and LLM prompts** | CEO view never sees "Meridian Retail Group" |
| **Domain-level** | Per-KPI `access` lists in the contract | Sales Head sees 4 of 7 KPIs |

Three personas (CEO / Data Analyst / Sales Head) get different narratives, different detail
depth (the CEO never sees a z-score), and different data scopes — same engine.

---

## 8. UI/UX

- **Company-style dashboard**: severity-ordered stat tiles (Redash counters), Grafana-style
  trend panels where the **shaded band is each KPI's own alert threshold** — a red dot outside
  the band *is* the explanation of the flag; dotted 3-month OLS forecast on every chart.
- **Clickable metrics**: every tile has a details popover — plain-English sentence (templated,
  not LLM), the numbers, normal range, source freshness, mini-chart, Investigate button.
- **Investigation page**: verdict row (trend + confidence bullet-gauge with both gates drawn
  as thresholds) → ranked-driver bars → contribution **waterfall** → action cards → audit trail.
- **Method chips everywhere**: 🗄 SQL · 📐 statistics · 🌲 ML · 🔎 retrieval · ✨ LLM (words only).
- **Accenture theme** (core purple #A100FF on white; #B455F0 on black) with an in-app
  dark/light toggle; every color pair contrast-verified (WCAG ≥4.5:1 text, ≥3:1 graphics).
- **0 LLM tokens on the dashboard** — the whole page is computed.

---

## 9. Cost, latency, scalability (measured, shown in-app)

| Metric | Value |
|---|---|
| LLM calls per investigation | **2** (1 Haiku mapping + 1 Sonnet narrative) |
| Cost per insight | **≈ ₹1–3** ($0.01–0.03) |
| Models & pricing | Haiku 4.5 $1/$5 · Sonnet 5 $2/$10 per MTok, effort=low |
| Deterministic analytics | milliseconds (DuckDB pushdown over 85k rows) |
| End-to-end latency | mock < 2 s · live 10–20 s (Sonnet-bound) |
| Deterministic paths (no-signal, sparse) | **0 LLM tokens** |
| Full offline demo | fixtures + heuristic fallbacks — cannot hard-fail on stage |
| Fixture refresh (19 live calls) | ~₹12–16 per full re-record |

Per-run telemetry (latency, tokens, $, ₹, model, mode) is displayed under every investigation
and cumulatively in Under-the-Hood.

---

## 10. Engineering quality (how we verified it)

- **Test suites**: 9-group headless UI suite (Streamlit AppTest) covering the golden path,
  abstention, sparse, intent routing, RBAC/masking, and a **crash-regression sweep over every
  investigable KPI**; plus an end-to-end engine smoke test of all planted scenarios.
- **Adversarial review workflows** (multi-agent):
  - *Light-mode audit* — 20 agents, 4 lenses; **10 confirmed defects** fixed (worst: amber
    text at 1.7:1 contrast; a body-level dropdown portal escaping the theme), 5 findings
    rejected as nitpicks after recomputation.
  - *Statistics/ML verification* — recomputed the OLS prediction interval from first
    principles: **89–90% empirical coverage over 2,000 seeded simulations**; caught a
    circular-correlation bug (anomaly month inflating "historical" driver correlation from
    −0.20 to +0.95) and 5 more defects — all fixed.
  - *Investigation-layer review* — **16 findings** including a page crash on driverless KPIs
    and an evidence-mapping bug that wrongly downgraded a verdict; all fixed, regression-tested.
- **Honest failure analysis**: daily revenue was too noisy (±20%) for per-day outlier
  detection to see a 15% regional shift — the forest scores the 7-day smoothed level vs the
  90-day level instead. We can explain *why* each method is shaped the way it is.

---

## 11. Round-2 requirement coverage

| Requirement | Where |
|---|---|
| Detects & prioritises material movements | detector ensemble + severity-ordered dashboard + morning summary line |
| Reconciles heterogeneous sources | 4 sources, 3 grains, freshness strip, per-evidence provenance |
| Identifies & **ranks** drivers | ranked-driver bars, computed strength = movement+evidence+external |
| Persona narratives w/ traceable evidence | 3 personas, [E#] citation popovers, decision ledger |
| Uncertainty + abstention | confidence gauge w/ gates, abstain path, "what could change this answer" |
| Actions with levers, constraints, decision rights | action cards: lever → owner → **approver** → impact → monitoring |
| Learns from feedback | 👍/👎 + corrections → ledger → future retrieval |
| Security / cost / latency / scalability | row+column+domain security · telemetry panel · stateless-per-investigation design |
| LLM vs non-LLM breakdown "and why" | Under-the-Hood method table + method chips + per-run mix |
| KPI semantic contract | `contracts/kpi_contract.yaml` — executed, not documentation |

---

## 12. Roadmap (post-prototype)

Predictive "what-if" mode (the deck's Team Mentalist) · embedding-based retrieval · real ERP
connectors (SAP Joule-style) · expert-network MCP integration · STL deseasonalization ·
causal-graph inference · multi-tenant deployment on client cloud.

---

## 13. Suggested slide map

1. **Title** — one-liner + team
2. **Problem** — dashboards say what, never why (§1)
3. **Principle** — LLM never computes + method-mix table (§2)
4. **Architecture** — the diagram (§3)
5. **Live pipeline walkthrough** — the revenue investigation with real numbers (§5)
6. **Trust machinery** — hallucination guard, abstention, noise filter (§6)
7. **Security & personas** (§7)
8. **UI** — screenshots: dashboard, verdict row, waterfall, action cards (§8)
9. **Economics** — ₹1–3 per insight, 2 LLM calls, offline-safe (§9)
10. **Rigor** — tests, adversarial audits, 2,000-simulation verification (§10)
11. **Requirement coverage** — the checklist (§11)
12. **Roadmap + ask** (§12)
