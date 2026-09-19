# The brief, pointer by pointer

The challenge asked for a working prototype of a KPI intelligence-to-action
engine that does seven things. This page maps each one to what the prototype
does, where that lives in the code, how it is tested or measured, and what is
honestly still missing. It is the checklist to walk before the finale, and the
page to point an evaluator at when they ask "where is requirement N?"

Status legend: **Done and measured** · **Done** · **Partial** (with the gap named).

---

## 1. Detects and prioritises material KPI movements — Done and measured

**What it does.** Every governed KPI is tested each month against its own
history with a t-test using the prediction standard error, then against the
contract's business materiality bar (both a |z| and a percentage threshold),
then against the whole portfolio with Benjamini–Hochberg at q = 0.10 so that
seven independent tests do not produce a phantom alert every month. Flagged
movements are ordered worst first; a movement that clears its own bar but fails
multiplicity control is shown as suppressed, with the reason, rather than
dropped. A daily-grain IsolationForest per region cross-checks revenue, with
its effective sample size and decision margin stated.

**Where.** `engine/anomaly.py`, `engine/screening.py`, `engine/stats_ml.py`,
`engine/policy.severity_order`, `services/scan.py`; the Dashboard and the Live
Feed replay.

**Evidence.** `eval.py`: precision 1.0, recall 1.0 across 36 cases in six
months, five controls; both pre-existing false positives removed by
multiplicity control at no cost to recall. `tests/unit/test_screening.py`
reproduces the published 1995 Benjamini–Hochberg example and pins the thin
July revenue margin. Design decisions D10, D11.

**Gap.** Stationary baseline over twelve months; no seasonality decomposition.

## 2. Reconciles data and business context across heterogeneous sources — Done

**What it does.** Three source systems in three formats: the order system is a
live **PostgreSQL** database fetched over the wire at start-up; the warehouse
and marketing systems drop **CSV** extracts on a schedule; the CRM exports
events as **JSON lines**. `engine/sources.py` ingests all of them into one
governed namespace of typed tables so the contract SQL can join across systems
(complaint rate is CRM events over OMS orders) without knowing where each side
came from. What it does know is recorded and shown: per source, the system,
kind, whether it was live or an extract, rows, latest record and fetch time. A
live source that is unreachable falls back to its last extract **visibly**. The
business context comes from a semantic contract (definitions, materiality,
drivers, levers, owners, approvers, access), ten unstructured documents
(tickets, transcripts, notes, a postmortem, two red herrings), a market-event
feed, and the decision ledger of past conclusions and human verdicts.

**Where.** `contracts/kpi_contract.yaml` (`sources:` with `kind` and
`location`), `engine/sources.py`, `engine/db.py`, `engine/retrieve.py`,
`data/market_events.json`; the Lineage page and `GET /sources`.

**Evidence.** `tests/unit/test_sources.py`: three systems, three kinds, every
source lands typed; the live OMS path against a real PostgreSQL in CI;
unreachable and unconfigured sources fall back with a stated reason and never
leak credentials. `tests/integration/test_backend_parity.py`: the same contract
runs on two engines with identical results. Design decisions D2, D25, D28, D29.

**Gap.** Reconciliation is by shared keys and grain declared in the contract;
there is no entity resolution or schema-drift detection. Freshness is shown but
not yet enforced as a gate.

## 3. Identifies and ranks explanatory drivers using appropriate analytical methods — Done and measured

**What it does.** Contribution analysis by dimension against a three-month
baseline, with shares reported only where the contract says the KPI is additive
and with "diffuse" as an honest outcome; driver co-movement checks against the
direction the contract declares, with `contradicts` reducing confidence and
`unexplained` drivers (moved, but nothing upstream did) counted at half weight;
weighted whole-term retrieval over the document corpus; a strict evidence
mapping by the language model that is counted, not scored, in Python; market
events matched by tag and region. Hypotheses are ranked by a fixed formula
(statistical movement, corroboration, external confirmation) and never by the
model. The engine says "moved with it", never "caused".

**Where.** `engine/contribution.py`, `engine/drivers.py`, `engine/retrieve.py`,
`engine/pyramid._rank_hypotheses`, `llm/prompts.EXTRACT_SYSTEM`.

**Evidence.** Root-cause accuracy 4 / 4 on the planted incident with the
rank-1 hypothesis required to be the specific planted driver; the planted
measurement artifact never leads the revenue story
(`test_planted_measurement_artifact_does_not_corroborate`). Design decisions
D14, D15, D16.

**Gap.** The driver checks themselves remain co-movement: no lag structure,
no confounder control. The one causal quantity is the difference-in-differences
estimate (D30), and it is only identifiable where the regions provide an
untreated comparison group; the engine says "not identifiable" otherwise.

## 4. Generates persona-specific narratives supported by traceable evidence — Done

**What it does.** Three personas (analyst, executive, department head) with
declared narrative styles; the model writes over verbatim facts and cites
evidence by id (`[E1]`); every cited snippet is on screen with its source file,
date and system; account names are masked before the prompt for roles not
cleared to see them; a deterministic sanitizer strips statistics vocabulary and
id clutter; the full level-by-level audit trail (SQL executed, tests, votes,
mappings) sits beneath the prose. Offline, recorded fixtures replay; with no
fixture, a deterministic template speaks.

**Where.** `llm/prompts.py`, `llm/client.py`, `llm/fallback.py`,
`engine/pyramid._tidy_narrative`, `roles.yaml`; the Investigation page.

**Evidence.** `test_executive_never_sees_a_standardised_score`,
`test_no_narrative_is_ever_empty`, `test_masking_reaches_retrieved_evidence_not_just_the_screen`;
21 rendered snapshots per page per role. Design decisions D1, D5, D6, D19.

**Gap.** Prose numbers are not yet verified against the facts handed to the
model; the model can still mis-state a figure it was given. Cheap to add.

## 5. Communicates uncertainty and abstains when evidence is insufficient or contradictory — Done and measured

**What it does.** A confidence score that cannot reach 1.0 (Laplace-smoothed
components, unassessable components dropped rather than credited, a
verifiability discount, a hard cap at 0.95), shown with its components. Two
gates: 0.60 to state a cause, 0.75 to recommend actions. Below the evidence
gate the engine **abstains**: it says what was checked, why it is insufficient,
asks one specific question and prepares an escalation brief. Between the gates
it says "likely" and offers low-regret steps. Contradicting drivers are shown as
evidence against. Sparse history yields a watching statement, not a diagnosis.
The flagship revenue case deliberately lands at TENTATIVE because its own
signal is marginal.

**Where.** `engine/confidence.py`, `engine/pyramid.py` (gates, Level 4),
`llm/prompts.NARRATIVE_SYSTEM` (abstain rules).

**Evidence.** Correct abstention 1 / 1 with no false abstentions; calibration by
band all 1.0; gate-separation margins reported (0.266 and 0.064) rather than
hidden; `test_confidence_never_claims_certainty`, `test_abstain_path`. Design
decisions D3, D12, D13.

**Gap.** Confidence is a calibrated score, not a probability, and it is
calibrated on planted data. A real pilot would re-fit the gates.

## 6. Recommends practical actions grounded in business levers, constraints and decision rights — Done

**What it does.** Actions may only use the contract's declared levers; each
lever carries an owner and an approval right ("COO for spend over ₹5L per
quarter"). The model writes the sentence; the contract chooses the recipient
and the approver. Dispatch is governed: ACTIONS go to the lever owner with the
approver copied, TENTATIVE goes marked for review, ABSTAIN escalates to the KPI
owner with the question, NO SIGNAL sends nothing. Nothing leaves without a
human approving it in the Outbox; the outbox is an append-only event log;
delivery is a dry run by default with an MCP transport behind the same
interface. An action whose lever the contract cannot match is surfaced as
unroutable, not guessed.

**Where.** `contracts/kpi_contract.yaml` (`levers`), `engine/policy.py`,
`engine/dispatch.py`, `services/outbox.py`, `services/transports.py`; the
Outbox page.

**Evidence.** `tests/integration/test_dispatch.py`: recipient and approval come
from the contract, nothing sends without approval, drafting is idempotent,
unroutable actions are surfaced; `test_mcp_transport.py` against a real local
MCP server. Design decisions D23, D24.

**Gap.** MCP delivery has not yet posted into a real Slack workspace (needs
credentials). Constraints beyond decision rights (budget ceilings, capacity
limits) are not modelled.

## 7. Mechanism to learn from analyst and business-user feedback — Done and measured

**What it does.** A verdict (up or down, with a comment) is an event on the
investigation it judges. It changes three things: retrieval (an up-voted past
conclusion weighs ×1.5 as precedent, a down-voted one is dropped), ranking (a
driver a human confirmed is promoted ×1.15, one they rejected demoted ×0.6),
and the audit trail. When the engine abstains and asks a question, a human can
**answer** it; the answer becomes same-period evidence with human provenance, a
confirmed cause becomes a hypothesis attributed to the person, a ruled-out lead
is recorded as eliminated by them, and the engine re-runs. The ledger is the
shared learning signal; on PostgreSQL it is one append-only table across
replicas.

**Where.** `feedback.py`, `store.py`, `engine/retrieve.py` (`VOTE_WEIGHT`,
`HUMAN_ANSWER_WEIGHT`), `engine/pyramid.py` (`PRECEDENT_ADJUST`, the abstain
loop); the Investigation and Ledger pages.

**Evidence.** `tests/integration/test_learning_loop.py`: a correction demotes,
a confirmation promotes, a rejected conclusion is not reused as evidence;
`test_abstain_loop.py`: a confirming answer moves the planted tracking bug from
abstain 0.438 to TENTATIVE 0.638 with the answer as `E1`, a rule-out keeps the
abstention and names who checked, and no actions are manufactured. Design
decisions D8, D17, D27.

**Gap.** The effects are bounded by design and calibrated by judgement, not by
outcome data; a pilot would measure whether corrected explanations stay
corrected.

---

# The solutioning areas, one by one

The brief also listed eight areas teams "may explore a hybrid combination of".
Same treatment: what is done, where, how it is pinned, what is not.

| Area | Status | Where | Pinned by | Not done |
|---|---|---|---|---|
| Anomaly detection, contribution analysis, **forecasting**, **causal inference**, business-rule reasoning | Done | `engine/anomaly.py`, `screening.py`, `contribution.py`, `forecast.py` (OLS band, two scenarios, R² stated), `causal.py` (difference-in-differences on the regional panel with interval, placebo check, permutation floor; "not identifiable" when no control group), contract thresholds and levers as the rules | `test_causal_graph_forecast.py`: a regional shock yields a negative effect whose interval excludes zero; a national movement is not identifiable; a KPI without a panel is not identifiable | Causal identification only where regions give a control group; no seasonality |
| Governed KPI semantics, metadata, lineage, business rules, **ontology / knowledge graph** | Done | The contract; the Lineage page with provenance; `engine/graph.py` builds the graph (42 nodes, 52 edges), draws it, and the engine walks it up (unexplained drivers) and down (exposure: downstream KPIs and owners) | Graph tests: no dangling edges; downstream reads driver edges in reverse; exposure names the owners | No inference over the graph beyond traversal |
| LLM-assisted intent understanding, orchestration, narrative synthesis, contextual retrieval | Done, with orchestration deliberately deterministic | `services/intent.py`, `engine/pyramid.py` (the orchestration: fixed levels, gates, early exit), `llm/prompts.py`, `engine/retrieve.py` | D26; `test_intent.py`; `test_pyramid_paths.py` | The model does not plan or choose tools, by decision |
| **Proactive alerts**, conversational analysis, augmented dashboards, decision workspaces | Done | `ops/watch.py` scans the portfolio and the live lane and drafts into the Outbox, never sends; the ask box and deterministic follow-ups are the conversational entry; Dashboard + Investigation + Outbox is the decision workspace | `test_watch.py`: drafts every material movement once, escalates a live breach once per day, never sends | No free-form multi-turn chat; conversational follow-ups are governed intents |
| Confidence scoring, evidence citation, **alternative hypotheses**, abstention | Done | `engine/confidence.py`; `[E#]` citations; the "alternatives considered" list with the reason each ranks lower; the abstain path | `test_confidence.py`; `test_pyramid_paths.py`; snapshots | Confidence is a calibrated score on planted data |
| Action chain: driver → controllable lever → action → expected impact → owner → confidence → monitoring plan | Done, in that order | `llm/prompts.py` (the schema), `ui/components/actions.py` (the card), `engine/policy.py` (owner and decision right from the contract) | `test_dispatch.py`: recipient and approval come from the contract | Constraints beyond decision rights (budgets, capacity) are not modelled |
| Human feedback, expert validation, correction workflows, learning loops | Done and measured | `feedback.py`, the abstain loop, `PRECEDENT_ADJUST`, `VOTE_WEIGHT` | `test_learning_loop.py`, `test_abstain_loop.py` | Effects bounded by judgement, not fitted to outcome data |
| Platform-native or custom (Databricks, Snowflake, Fabric, Tableau, Qlik, Looker, or other) | Custom in the middle, hybrid at four proven seams | Sources of any kind including any SQLAlchemy warehouse URL (`kind: sql`); the contract SQL on any SQLAlchemy engine (`RATIONALE_DB`); the ledger on PostgreSQL; `ops/export_bi.py` writes every output as CSV and Parquet for Tableau, Power BI, Looker and Qlik, and the API serves JSON. `docs/PLATFORMS.md` | `test_warehouse_kind.py` (SQLite and PostgreSQL through the generic path), `test_vendor_dialects.py` (Snowflake and Databricks drivers register, URLs parse, rewrites exact, the loader/verifier tool end to end on PostgreSQL), `test_backend_parity.py`, `test_export_bi.py` | The vendor run itself: no Snowflake or Databricks account has been used; `python -m ops.warehouse smoke/load/verify` is ready for one |

---

## The honest line

Every pointer is implemented and tested against planted ground truth. What none
of them has is a real user: the data is synthetic with known causes, and no
analyst or business user outside the team has given feedback to the loop that
learns from it. That is the first thing a pilot changes
(`docs/PILOT_AND_OPERATIONS.md`), and it is said before it is asked.
