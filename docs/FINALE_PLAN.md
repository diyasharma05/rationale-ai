# Grand Finale plan — against the evaluators' rubric

The evaluators' email is a rubric with three headings. This page maps where we
stand on each, what closes the gaps, and how the deck, demo and Q&A divide the
work between them.

---

## 1. Where we stand

| Rubric theme | Standing | Evidence | Gap |
|---|---|---|---|
| **Understand the problem before building** | Grounded, not validated | `docs/PROBLEM_STATEMENT.md`: four stakeholders, published evidence, explicit assumptions; `docs/REQUIREMENTS_MAP.md`: the brief's seven pointers mapped to code, tests and gaps | No real user has touched the system. We cannot fix that before the finale; we can be the team that says so first and has a pilot plan for it. |
| **Let human imagination lead** | Thesis is ours; hardening must be owned | Round-2 architecture (deterministic-first, contract, abstention) is original. Round-3 decisions are documented with alternatives in `docs/DESIGN_DECISIONS.md` | Every Round-3 decision must be understood well enough to defend *or overrule*. Mock Q&A is the test. |
| **Think like an enterprise builder** | Strongest area | 234 tests, CI gates, offline-safe, RBAC in SQL and at the API, audit trail, human-approved dispatch, measured concurrency, provenance page, pilot and Day-2 plan | Business case is a model, not a number, because there is no client. Say so. |

## 2. The order of work

1. **Read `DESIGN_DECISIONS.md` critically.** For each decision, decide: adopt,
   change, or ask. Anything you would change, we change now. This is the
   single most important task and it cannot be delegated.
2. **Mock Q&A**, hostile evaluator, no notes. Repeat until nothing sounds
   recited. The questions in the design doc are the starting set; the real
   ones will be worse.
3. **Deck** from the outline below. Business layer first, technology second.
4. **Demo rehearsal** with the updated script — including the honest opening
   and the TENTATIVE golden path.
5. **Code freeze.** The remaining risk is not technical.

## 3. Deck outline (12 slides, ~10 minutes)

The order is deliberate: problem and thinking before technology, matching the
order of the evaluators' three points.

| # | Slide | Rubric theme | The one thing it must land |
|---|---|---|---|
| 1 | **The problem, from four chairs** | 1 | Analyst: the "why" is a person-day. Ops: every metric alerts so none do. Exec: 77% rely on dashboards, 67% don't fully trust them. Platform: LLM-over-warehouse scores 21% on real schemas. |
| 2 | **What we are solving, precisely** | 1 | Detect with a controlled error rate → explain with evidence → decide whether to conclude → route to the named owner → learn from the verdict. |
| 3 | **Our thesis** | 2 | The model never computes a number and never makes a routing decision. It writes sentences. Everything else is SQL, statistics, and a governed contract. |
| 4 | **The semantic contract** | 2, 3 | One artifact defines the KPI, its thresholds, its drivers, its levers, their owners and approvers, who may see it, and where its sources live: a live PostgreSQL order system, CSV extracts and a JSON event feed, reconciled at ingestion with provenance on screen. The dbt Labs result (90 → 98%) is independent evidence this is the right layer. |
| 5 | **Live demo** (5 min) | all | Per `DEMO_SCRIPT.md`. Open with the honest line about synthetic data. |
| 6 | **Why we trust the numbers** | 3 | Precision 100% / recall 100% across 36 cases and five control months; FDR-controlled; confidence cannot reach 1.0; the harness is mutation-tested. Show the gate-separation margins including the narrow one. Then the one causal estimate: the North-West shock is about 82% of July's revenue movement, with its interval and its assumption check, and "not identifiable" for the national tracking bug. |
| 7 | **Why the flagship case is TENTATIVE** | 2, 3 | Because it should be. Revenue's own signal is marginal (p ≈ 0.07); the drivers carry it. An engine that called it ESTABLISHED at 0.71 is the one to distrust. |
| 8 | **A governed agent** | 2, 3 | It perceives, reasons, decides, acts and learns — and here is exactly where the autonomy stops and why: RBAC in SQL and at the API; masking before the prompt; the model never plans, picks a tool or chooses a recipient; human approval before any dispatch; silence on no-signal. |
| 9 | **Runs every day** | 3 | 234 tests, two CI gates, offline-safe, container, concurrency curve with zero wrong answers under load. Runs unchanged on PostgreSQL with identical verdicts; the ledger becomes one shared append-only table. |
| 10 | **From prototype to client** | 3 | The pilot in four phases, starting with the contract workshop — the human step. Three to five months to trusted, narrow dispatch. Day-2 operations table. |
| 11 | **Value, as a model** | 3 | Time-to-diagnosis, days of earlier action × daily cost, alert fatigue avoided, ₹1–3 per investigation. Honest that the realised number needs a pilot. |
| 12 | **What we have not solved, and how we built** | 1, 2 | No real users yet. No causal inference. No seasonality. And: architecture and thesis are ours; we used AI assistants for implementation and hardening; here is a decision we overruled. |

## 4. The honest lines, verbatim

Say these before being asked. An evaluator who finds them first will remember
that you did not say them.

- *"The data is synthetic, with known causes planted. No real user has used
  this. That is why we can quote a precision and a recall at all — and it is
  the first thing a pilot would change."*
- *"The Live Feed is a replay. The detector is real; the clock is not. The
  Lineage page is where something genuinely live is on screen."*
- *"Revenue lands at TENTATIVE. Its own signal is marginal. We think that is
  the right answer, and we changed the demo to say so rather than move the
  threshold."*
- *"q = 0.10 is doing work: at 0.05 the headline movement is suppressed. Here
  is the margin and the test that pins it."*
- *"The model never chose a recipient, a number, or a threshold. It wrote
  sentences. We used AI tools to build this the same way."*

## 5. Questions we expect, and where the answer lives

| Question | Answer lives in |
|---|---|
| Why not an LLM over the warehouse? | D1; slide 1 (Spider 2.0: 21%); the method strip |
| Where is requirement N of the brief? | `docs/REQUIREMENTS_MAP.md`, one section per pointer with the tests that pin it |
| Are the sources really heterogeneous? | D29; the Lineage page's provenance table; `GET /sources` |
| Who maintains the contract? | D2; pilot phase 0 |
| Is confidence a probability? | D12; slide 6 |
| Why 0.10? | D10; slide 6 |
| Your headline case doesn't conclude? | D13; slide 7 |
| Where does causation come from? | D14 for the drivers (co-movement); D30 for the one causal estimate, with its identification conditions |
| Is there any forecasting? | D31; the trend band under every chart, with R² stated |
| Why not Databricks / Snowflake / Fabric? Can it work with our Tableau? | D35; `docs/PLATFORMS.md`; `python -m ops.export_bi` and the README it writes |
| Is the contract an ontology? | D32; the graph on the Lineage page; `GET /graph` |
| Does anything happen without a click? | D33; `python -m ops.watch` drafts into the Outbox and never sends |
| Who validated this with users? | Part V of the design doc; slide 12 — say it first |
| What stops it spamming my VP? | D23; slide 8 |
| How does it deploy / scale? | D20–21, D28; slide 9; `/docs` on the API |
| Is it tied to DuckDB? Where does the ledger live with replicas? | D28: one variable moves engine and ledger to PostgreSQL; parity suite; INSERT-only role |
| What breaks on a Tuesday? | Pilot doc §4 |
| How much of this did an AI build? | Slide 12 — the honest version, with a decision you overruled |
| Is this an agent? Why isn't it more autonomous? | D26 — the taxonomy table; every withheld autonomy is a named enterprise failure mode. Then D27 for the one loop we did close. |
