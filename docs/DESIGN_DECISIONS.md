# Rationale.AI — Design Decisions

**Purpose.** Every consequential decision in this system, with the problem it
solves, the alternatives, the evidence, and what would change our mind. This
exists so that anyone presenting the system can defend any part of it from
understanding rather than memory — and so that decisions we disagree with get
overruled *before* the finale, not discovered on stage.

**How to use it.** Read each decision and ask: *would I have made this call?*
If not, say so. A decision you would change is a better conversation to have
now than with an evaluator. Every section ends with the question a judge is
most likely to ask and the honest answer.

**Provenance, stated plainly.** Decisions marked **[R2]** are the team's
original Round-2 design — the thesis. Decisions marked **[R3]** were made
during Round-3 hardening with heavy use of an AI coding assistant; the team
made the product calls flagged **[team call]**, and must now adopt or overrule
the rest. This document is how that adoption happens. The product's own thesis
is that AI should write the sentences while humans and deterministic logic make
the decisions; the build process should be able to say the same.

---

## Part I — The thesis (Round 2)

### D1. The model never computes a number. [R2]

**Problem.** LLMs over data produce fluent, wrong figures. In BI the number *is*
the product; a wrong one is worse than none.

**Decision.** SQL, statistics and ML produce every figure. The model receives
precomputed facts and writes prose over them. Its output is sanitised (length
and vocabulary), and the one place it may propose a hypothesis is gated.

**Alternatives.** Text-to-SQL (model writes queries — fluent but unauditable);
RAG over tables (model reads rows — cannot aggregate reliably); agentic tool use
(model orchestrates — decisions leak into the model). All three put a decision
in the model.

**Why this.** Auditability. Every number on screen has a SQL statement behind it
that a human can read. The method strip on every result shows what did the work.

**Known weakness.** The model still chooses *which* facts to emphasise and can
still mis-state a passed-in figure in prose. We do not verify prose numbers
against the facts. This is a real gap; see D22.

**Judge asks:** *"Why not just put an LLM over the warehouse?"*
**Answer:** Because you cannot audit a model's arithmetic and you cannot afford
to send the warehouse to it. Show the method strip: 18 SQL queries, 10
statistical tests, 5 ML models, 6 documents, and at most 2 LLM calls that only
wrote sentences.

### D2. The semantic contract is the executable definition of a KPI. [R2]

**Problem.** "Revenue" means five things in five departments. Thresholds live
in people's heads. Nobody knows who may act on a lever.

**Decision.** One YAML per KPI: the SQL, the materiality thresholds, the
declared drivers with their expected direction, the dimensions, the levers with
their **owner and approval right**, and which roles may see it.

**Why this matters more than it looks.** It is the routing table for dispatch
(D23), the family for multiplicity control (D10), the additivity flag for
contribution (D15), and the access list for RBAC (D5). Almost every Round-3
capability was possible because this artifact already existed.

**Known weakness.** Someone has to write it, and that someone is a domain
expert. Onboarding a client is a **workshop, not a config file.** We
under-stated this in Round 2 and must say it plainly now.

**Judge asks:** *"Who maintains this contract in production?"*
**Answer:** The KPI's named owner, through a reviewed change process — it is
version-controlled and CI-validated. The honest part: authoring the first one
for a client is the hard, human step, and it is where the domain understanding
the evaluators asked about actually lives.

### D3. Confidence gates and abstention. [R2]

**Decision.** A deterministic score with two thresholds: 0.60 to state a cause,
0.75 to recommend action. Below 0.60 the engine abstains, asks a human a
specific question, and writes an escalation brief.

**Why.** An engine that always answers is an engine that is sometimes
confidently wrong. Abstention is the product's most important property and the
one competitors will not have.

**What changed in R3.** The score's *arithmetic* changed (D12) but the gates did
not — and D18 shows they are now validated by data rather than asserted.

### D4. The four-level reasoning pyramid with early exit. [R2]

Signals (SQL/stats/ML) → company context (retrieval + model mapping) → external
signals → expert escalation. Each level costs more; the engine stops once
confidence clears the action gate with margin. Cost control and explainability
in one structure.

### D5. Row-level security in the SQL; masking before the prompt. [R2]

**Decision.** The role's region filter is injected into every contract query.
Account names are replaced with stable codes in evidence snippets *and in the
serialised context sent to the model*.

**Why this is the strongest compliance answer we have.** The only things that
ever leave the perimeter are precomputed aggregates and masked snippets. No raw
rows, ever. In R3 this was extended to the API boundary (403 on a restricted
KPI) and to the lineage page (row counts change with the role).

**Judge asks:** *"Data residency? PII?"*
**Answer:** Masking happens before the prompt, not on screen. Show
`pyramid.py` masking the context, then show the lineage page counts changing
when you switch role.

### D6. Recorded fixtures make the demo offline-safe. [R2]

The model's responses for every reachable (KPI, role) combination are recorded
once and replayed. The engine's numbers are always computed live; only the
prose is cached. R3 finding: five of thirteen combinations were missing and the
rest had gone stale — see D19.

### D7. Synthetic data with planted causes, and an evaluation harness. [R2]

**Decision.** Generate a year of data for an invented retailer with a specific
incident planted (a warehouse conveyor failure), a measurement artifact planted
(a marketing tracking bug), and control months with nothing planted.

**Why.** It is the only way to quote a precision and a recall. Real client data
arrives without an answer key.

**Known weakness — the biggest one in the project.** No real user has touched
this. The retailer is invented. The thresholds were tuned by us. We have not
validated that an operations lead would trust the abstain verdict or act on a
dispatched message. **Say this before anyone asks.** See Part IV.

### D8. The decision ledger as precedent ("Recall"). [R2]

Every conclusion is appended to a ledger which becomes part of the retrieval
corpus, so past incidents inform new ones. R3 found this had become an echo
chamber (D16) and that the "learning loop" was cosmetic (D17).

---

## Part II — Statistical honesty (Round 3)

### D9. Materialise the tables; cache the ML verdict. [R3]

**Problem.** Every query re-parsed a 4.9 MB CSV (DuckDB views over
`read_csv_auto`), and the IsolationForest retrained five 200-tree models on
every run. The flagship click took ~12 seconds.

**Decision.** `CREATE TABLE` at boot with dates cast once; a content-hash disk
cache of the ML *verdict*, keyed on the (already role-filtered) data.

**Evidence.** `kpi_series` 583 ms → 8 ms. IsolationForest 1,754 ms → 1.4 ms on
a hit, and scikit-learn is never imported on a hit. Flagship click ~12 s →
381 ms cold / 114 ms warm. Dashboard scan 930 ms → 37 ms.

**Side finding worth telling.** `revenue_daily` returned rows in
nondeterministic order (`ORDER BY 1` on a `GROUP BY 1, 2`). The model's answer
was stable because it re-sorted internally, but the query contract was wrong.
Found because the cache never hit.

### D10. Multiplicity control: Benjamini–Hochberg at q = 0.10. [R3]

**Problem.** Seven KPIs tested every month at |z| ≥ 2. Family-wise false
positive rate ≈ 1 − 0.954⁷ ≈ **28%** — roughly one phantom alert a month,
from testing seven things. Confirmed: `complaint_rate` flagged in 2026-02 and
2026-04 with nothing planted.

**Alternatives.** Bonferroni (controls family-wise error but at n = 7 is strict
enough to suppress real incidents); raise the per-KPI z threshold (blunt,
loses sensitivity uniformly); do nothing and call it "alerting". BH controls
the false *discovery* rate — of the things we flag, at most q are expected
spurious — which is the right error rate for screening.

**Evidence.** All five planted July incidents survive; both false positives are
suppressed (their q-values are 0.31 and 0.54). Detection precision
0.833 → **1.000**, recall unchanged at 1.0, after *adding* two control months.
The implementation reproduces the published BH (1995) worked example and
matches `statsmodels` on 33 cases.

**The load-bearing part, disclosed.** July revenue has p = 0.0658 against a
step-up threshold of 0.0667. It clears by 0.0009. At q = 0.05 it would be
suppressed and the golden path would vanish. q = 0.10 is the conventional
level for exploratory screening, but the choice is doing work, and a regression
test pins the margin.

**Judge asks:** *"Why 0.10 and not 0.05?"*
**Answer:** Screening, not confirmation: we would rather investigate one
spurious movement in ten than miss a real one, because the investigation is
cheap and the evidence gate catches spurious ones downstream (both false
positives that *would* have got through were caught by it before this change).
Then say the margin out loud. An evaluator who finds it themselves will
remember that you did not.

### D11. A t-test with the prediction standard error, not a z. [R3]

**Problem.** With 6–11 monthly observations, `(x − x̄)/s` is not standard
normal. And the quantity being tested is a *new* observation, whose spread is
`s·√(1 + 1/n)`, not `s`.

**Evidence.** A movement of z = 2.24 reads as p = 0.025 under a normal
approximation; the honest figure at n = 7 is p = 0.093 — a **3.7× overstatement**
of significance. We kept the `z` field (the contract thresholds and fixtures are
calibrated on it) and added `t` and `p_value` alongside. The hardcoded t-table
was also wrong for every df above 15; it now uses `scipy`.

### D12. Confidence that cannot reach 1.0. [R3]

**Problem.** The shipped evaluation results showed `enterprise_active_accounts`
at confidence **1.000** — displayed to judges as 100% — on one month of n ≈ 11
data with no counterfactual.

**Three causes, three fixes.**
1. *Ratios of small counts.* "1 of 1 hypotheses corroborated" scored 1.0.
   Laplace smoothing: (k + 1)/(n + 2), so 1-of-1 is 0.667.
2. *A free prior.* A KPI with no declared drivers received a flat 0.5 for
   coverage — 0.175 of the total score for having nothing to check. Now
   unassessable components are dropped and the weights renormalised.
3. *The perverse consequence of fix 2.* Dropping a checkable dimension **raised**
   the score: `fulfilment_sla` (no drivers) scored 0.885 against `revenue`
   (four drivers, mostly confirmed) at 0.715, purely because revenue *could* be
   cross-checked. "We couldn't verify" must not outscore "we verified and it
   held", so the weighted mean is scaled by how much of the total weight was
   assessable. The scale factor floor (0.75) was chosen as the largest value at
   which that invariant holds; at 0.85 the inversion survived, below ~0.70 the
   ordering flips the other way. A test pins the invariant, not the number.

**Evidence.** enterprise 1.000 → 0.784; complaint_rate 0.995 → 0.779;
fulfilment_sla 0.825 → 0.807; marketing 0.350 → 0.438 (still abstains). Maximum
anywhere across three roles and six months: **0.813.** A hard ceiling of 0.95
exists as belt-and-braces.

**Judge asks:** *"Is this a probability?"*
**Answer:** No, and we do not call it one. It is a weighted, smoothed score of
three evidence channels that has been validated against planted ground truth
(D18): every case above 0.75 was correct, every case below 0.60 was correctly
not concluded, and the one case in between was the one that *should* be in
between. Calibration against real outcomes would need real outcomes.

### D13. Revenue lands at TENTATIVE, not ACTIONS. [R3] **[team call]**

**What happened.** Honest recalibration (D12) moved the flagship investigation
from 0.827 to 0.715 — under the 0.75 action gate. The demo's climax changed.

**The choice.** Re-fit the gates so revenue still clears (defensible only if
fitted on precision/recall, and it invites "did you move the threshold to fit
the answer?"), or embrace TENTATIVE. **The team chose TENTATIVE.**

**Why it is the stronger story.** Revenue's own signal *is* marginal (−7%,
p ≈ 0.07). The conviction comes from four corroborating drivers and the
documents. An engine that says "the cause is likely, here are low-regret steps,
here is what would confirm it" at 0.71 is behaving exactly as the thesis
promises. It also makes the abstain scenario land harder by contrast.

**Judge asks:** *"So your headline example doesn't reach a conclusion?"*
**Answer:** It reaches the *right* conclusion. Show the four drivers, the
evidence, and the gate margins. An engine that had called this ESTABLISHED at
0.71 would be the thing you should distrust.

### D14. Co-movement, not causation; unexplained drivers count for half. [R3]

**Problem.** The driver check asks one thing: *did another series move this
month, in the direction the contract predicts?* No lag, no control, no
counterfactual. Yet the status was named `consistent`, promoted into ranked
"hypotheses", and the prompt asked the model for a "causal story".

**Concrete failure.** The planted marketing tracking bug — a measurement
artifact — has the **largest |z| of any revenue driver** (−26.7) and was
counted as full corroboration of the revenue drop.

**Decision.** Status renamed `co_moves`; the UI says "moved with it, as the
contract predicts — concurrent, not proven causal"; the prompt asks for an
explanatory ordering. And: a co-moving driver whose *own* declared drivers are
all quiet is flagged `unexplained` and counts at half weight in both coverage
and ranking. Marketing conversion now ranks **last** (0.25) and is badged as a
lead.

**Judge asks:** *"So where does causation come from?"*
**Answer:** From the human who wrote the contract, and we say so in those words.
The engine tests whether the world is consistent with that declared link and
surfaces evidence; it does not discover causes. A real causal layer
(difference-in-differences on the region split) is on the roadmap and we
should not pretend otherwise.

### D15. Contribution: direction-aware focus, additivity from the contract. [R3]

**Three problems found.** Focus regions were selected on |share|, so a region
whose complaints *fell* entered the complaint-rate focus and then drove
retrieval. Shares were computed for percentages (per-region percentage points
do not sum to the national figure) and exceeded 1.0 when offsetting deltas
shrank the net denominator (measured: 1.60 and −0.41). And when nothing stood
out, the code picked the largest |delta| — for marketing conversion, five
regions within 0.19–0.21 and *West* chosen by a 1.4% noise margin.

**Decision.** Focus = share of the movement *in the direction that hurts*.
Additivity is declared per KPI in the contract (`dim_additive`), not guessed
from the unit string. When no region stands out the result is **diffuse** — a
real finding: a uniform drop across every region argues against a regional
cause and towards something systemic, which is exactly what the planted
tracking bug is.

### D16. Retrieval: whole-term matching, and precedent strictly in the past. [R3]

**Two bugs.** The term `west` matched inside `north-west` (weight 2.0), so the
national marketing investigation retrieved the North-West enterprise exit-call
transcript as its top evidence. Note that `\b` does **not** fix this — a hyphen
is a non-word character — the fix excludes hyphens from both boundaries. And
the ledger guard excluded only *same-period* entries, so analysing any month
before July pulled July's own conclusions back as evidence: 6 of 6 slots,
every real document pushed out.

**Decision.** Term boundaries that treat `-` as part of a word; precedent
admissible only from periods strictly before the one analysed; feedback rows
excluded; self-authored entries capped at 2 of 6 slots.

### D17. The learning loop, made real. [R3]

**Problem.** An upvote and a downvote scored identically. Feedback was text the
model might read; no gate, rank or threshold changed. The UI promised
otherwise.

**Decision.** Feedback is a verdict on an investigation *and on its rank-1
driver*. Retrieval weights precedent by verdict (confirmed ×1.5, rejected
dropped entirely — a wrong precedent is actively harmful). Ranking applies a
bounded adjustment (×1.15 / ×0.6): a correction is evidence about a past
conclusion, not a veto over the statistics.

**Evidence.** Mark the rank-1 explanation wrong, re-run: it drops from rank 1
(1.00) to rank 3 (0.60). Also: `no_signal` and `sparse` outcomes were never
logged — 20 of 24 eval cases — so "every investigation is appended here" was
false. Now they are.

### D18. The evaluation harness, made able to fail. [R3]

**Problem.** Root-cause "accuracy" substring-matched terms like `"sla"` against
the rank-1 label *plus the narrative body*. The label is built from the
driver's own contract name (`"Fulfilment SLA %"` contains both `sla` and
`fulfil`), and in offline mode the body is a recorded fixture that already names
the cause. The reported 4/4 partly measured a cached string.

**Decision.** Require the *specific planted driver* to rank first, scored on the
label only. Add a distractor-rejection case (the tracking bug must never lead
the revenue story). Add two control months (five total). Report **gate
separation** — the empty interval around each threshold.

**Evidence.** Mutation-tested: wrong expected driver → 4/4 becomes 3/4;
distractor allowed to lead → 3/4; phantom ground truth → recall 0.833. Gate
separation: evidence gate has a **0.266 margin** (nothing between 0.449 and
0.715 — not load-bearing); action gate has **0.064** (0.715 to 0.779 — it *is*
load-bearing, and it is what makes revenue TENTATIVE). The tentative band,
previously empty, now has an observation. `eval.py --check` is a CI gate and
fails on a seeded regression.

### D19. Prose and technical forms of the same sentence. [R3]

**Problem.** The sanitiser drops any sentence containing `z=`. The offline
template narrative put `z=` in its opening sentence. Result: the fallback body
rendered as **"Confidence 78%."** — and the executive persona saw a z-score on
the no-signal path despite the docs promising otherwise. Same bug class in
`_movement_str` and `human_line`: direction taken from sign(z) (vs the long-run
mean) while the magnitude printed was vs the trailing 3 months, so a 7% fall
rendered as "up 7.0%".

**Decision.** One function, two forms. Prose everywhere a non-analyst can see;
technical in the audit trail. Direction and magnitude from the same baseline.

---

## Part III — Enterprise shape (Round 3)

### D20. Architecture: shell, pages, services, engine, API. [R3]

`app.py` was 1,654 lines with 833 in one `if/elif` chain. Now 192 lines;
pages are `ui/pages/*.py` with `render(ctx)`; view models in `services/`
(no Streamlit import, so testable and reusable by the API); every number from
`engine/`. A layering test enforces the boundaries. Fifteen render snapshots
gated every step — and caught two regressions the refactor introduced (a
stylesheet emitted once per process instead of per run; a palette frozen at
import so dark mode stopped repainting charts).

**Judge asks:** *"How much of this is Streamlit?"*
**Answer:** Streamlit is one client. The engine is behind a FastAPI service too,
same code, with RBAC enforced there (403). Show `/docs`.

### D21. Tests, CI, and the benchmark as gates. [R3]

`smoke_test.py` printed everything and asserted nothing; it is gone. 179 tests
now, plus `eval.py --check` (accuracy) and `ops/bench.py --check` (latency
budget and correctness under concurrency) in CI. Measured concurrency: ~8–9
req/s on one process, p50 243 ms at N = 1 rising to 1.7 s at N = 16, **zero
wrong answers at every level** — the thread-safety fix holds under contention,
and past that point you add replicas because the service is stateless.

### D22. What we have not solved, in order of how much it would matter. [R3]

1. **No real users.** See D7 and Part IV.
2. **No seasonality.** The baseline is stationary over ≤ 12 months.
3. **No causal inference.** See D14.
4. **Prose numbers are not verified against the facts.** The model can still
   mis-state a figure it was given. Cheap to add; not yet done.
5. **Retrieval is keyword matching**, not embeddings — deliberately, to keep
   fixtures stable, but it is not what production would use.
6. **The MCP transport has been exercised against a real MCP server but not a
   real Slack workspace.** Needs credentials.
7. **Contract authoring is a human workshop** and we have not run one.
8. **The answered-state narrative is the deterministic template**, not model
   prose — no fixture has been recorded for it yet (one live call to add).

---

## Part IV — Dispatch and data flow (Round 3)

### D23. Governed dispatch: the contract decides who; a human decides whether. [R3] **[team idea]**

**The idea was the team's**; the design constraints below are how it was made
defensible.

**The constraint that matters.** The model **never chooses the recipient**.
Every lever in the contract names an owner and an approver; dispatch reads
those and ignores the model's own `owner` field entirely. This is D1 extended
one layer: the model never computes a number and never makes a routing
decision. Found and fixed a live instance while building it: the action card
had been rendering the *model's* owner beside the *contract's* approver; they
happened to agree.

**The outcome decides the message.** ACTIONS → owner, cc approver, as an
instruction. TENTATIVE → owner, marked FOR REVIEW, body says "below the action
threshold — not as a diagnosis". ABSTAIN → the KPI owner, as the escalation
brief with the clarifying question — asking a human, not instructing one.
no_signal / sparse → **nothing**. Silence is the correct output.

**Nothing leaves without a person.** Draft, approve and send are separate
events in an append-only log; `send()` refuses anything not approved. Delivery
is a dry run unless explicitly switched on — an engine that can message people
is a different risk class from one that draws a page.

**Judge asks:** *"What stops it spamming my VP?"*
**Answer:** Three things in order: it produces nothing for a metric behaving
normally; it produces a *question* not an instruction when unsure; and nothing
is sent until a named human approves it, with that approval recorded.

### D24. MCP as the wire, discovered not assumed. [R3]

**Why MCP.** One interface for whatever the client already runs — Slack, email,
Jira, ServiceNow. "We speak MCP" is a genuine integration claim. It is *not*
"the AI decides to email someone"; by the time a message reaches the transport,
the contract has chosen the recipient and a human has approved.

**What "written but not exercised" was hiding.** Two bugs, both fatal on the
first real call: the adapter hardcoded `send_message(channel, text)` while the
official Slack server's tool is `slack_post_message(channel_id, text)`; and the
MCP SDK starts child servers with a 12-key minimal environment, so the token
would never have reached the server. Now the adapter asks the server what tools
it offers and maps arguments from the schema; credentials are passed through
explicitly. Tested end-to-end against a real local MCP server. The official
Slack package is deprecated upstream; the adapter is vendor-neutral by
construction.

### D25. Lineage page and a live ingestion lane. [R3] **[team call: both]**

The Live Feed is a **replay** — a flight recorder of the incident, at speed,
with the real detector running. Say "replay", never "live"; it is the one claim
most likely to get caught by someone who reads the code. The Lineage page shows
provenance for any number (system → table → SQL → row filter → test) with
counts that change by role, and a separate process (`ops/ingest.py`) appending
events the app has never seen, scored by the same rolling rule. It writes to
its own lane: mutating the demo tables mid-demo would move the numbers just
shown.

---

### D26. Is this an agent? Yes — a governed one, and the constraints are the point. [R3]

**Why this needs a decision.** The evaluators' guidance opens its third theme
with *"building agents in an enterprise is hard"*. They will ask. The answer
has to be precise, because a vague yes invites "then why isn't it more
autonomous?" and a vague no throws away the framing they are using.

**The taxonomy.** Practitioners distinguish a *workflow* — predefined code
paths with model calls at fixed points — from an *agent*, where the model
dynamically directs its own process and tool use. Rationale.AI is a workflow
with gated model steps that nonetheless has the classic agent properties in a
deliberately constrained form:

| Property | Rationale.AI | Deliberate? |
|---|---|---|
| Perceives | Scans every KPI each period; daily-grain live detector | Yes |
| Reasons | The four-level pyramid | Yes — along **fixed** paths |
| Uses tools | SQL, statistics, ML, retrieval, the model, MCP transports | Yes — **code** picks the tool, never the model |
| Decides | Whether to conclude, whether to abstain, whom to route to | Bounded: routing from the contract; dispatch needs a human |
| Plans dynamically | **No.** Stages are fixed; early exit is a rule | Deliberate |
| Learns | Verdicts change future ranking and retrieval (D17) | Yes |
| Acts | Governed dispatch over MCP (D23–24) | Only after human approval |

**The decision.** Do not add model-driven planning, model-chosen tools, or
multi-agent orchestration. Each puts a decision inside the model — the one
thing D1 forbids — and each adds the unreliability the evaluators are warning
about. Every place autonomy was withheld is a place enterprise agents fail:
the fixed paths, the abstention, the human approval and the contract-governed
routing are not a lack of agency, they are the engineering answer to "safe,
reliable, works every day".

**The one agentic addition that fits.** When the engine abstains it asks a
human a specific question. Closing that loop — the human answers, the answer
becomes evidence with human provenance, the engine re-investigates — is a real
perceive–reason–act cycle with the human as a sensor, and it completes the
abstain path instead of leaving it a dead end. See D27.

**Judge asks:** *"Is this an agent, or just a pipeline with an LLM in it?"*
**Answer:** It perceives, reasons, decides, acts and learns — so yes. What it
does not do is let the model plan or pick tools, and we can show the exact
line: the model writes sentences; the contract and the code decide. Then the
follow-up they want: *"we know what an agent is, and we chose where to draw
the autonomy line — here is why each line is where it is."*

### D27. The abstain loop: the engine asks, a human answers, the engine re-runs. [R3] **[team call]**

**Problem.** When the engine abstained it asked a human a specific question —
*"Did any tracking or checkout change roll out in July?"* — and the question
went nowhere. The abstain path was a dead end dressed as a handoff.

**Decision.** A human answers in the app. The answer is stored as an event on
the investigation (like a verdict, so it is auditable: who, when, what) and
surfaced to retrieval as a document with **human provenance**, admissible for
the *same* period — unlike engine precedent, which must be strictly past. On
re-run, a confirming answer becomes a hypothesis with `source: human`; a
ruling-out answer is recorded as an eliminated lead with the actor's name.

**Why the hallucination guard does not apply.** The guard exists to stop the
*model* inventing causes when the contract already declares drivers. A domain
expert stating a cause is the opposite case: it is exactly the input the
contract cannot encode, and exactly what the evaluators asked us to seek. The
model is still blocked; a test asserts it.

**Evidence.** marketing_conversion: abstain at 0.438 → after a confirming
answer, **tentative at 0.638** with the human's statement ranked first and the
answer itself retrieved as `E1`. After a ruling-out answer: still abstain at
0.438, with *"ruled out by head_of_growth"* on screen. No actions are
produced either way, because no contract lever fixes a tracking tag — the
engine does not invent one.

**Why TENTATIVE and not ACTIONS.** Testimony is not measurement. A human-stated
cause scores 0.8 on the statistical component (above a model-proposed lead at
0.4, below a measured driver that can saturate at 1.0), and the score is
still smoothed and discounted as in D12. "A person told us why, and we have
not yet measured the effect" is precisely what tentative means.

**What it is, in agent terms.** A perceive–reason–act cycle with the human as
a sensor. The engine decided to ask; the human supplied a fact; the engine
recomputed deterministically. That is the only form of autonomy we added,
and it is the form that keeps every decision out of the model.

**Judge asks:** *"So a human can just tell it the answer?"*
**Answer:** Yes — and that is recorded, attributed, and treated as testimony
rather than proof. The verdict moves from "we don't know" to "likely, per
the head of growth, unmeasured", not to "established". Compare that to a
dashboard, where the same conversation happens in a Slack thread and is gone
by next quarter.

## Part V — The honest opening

Before any evaluator asks: *the data is synthetic, generated with known causes
planted, and no real user has used this system.* That is a limitation and it is
also the reason a precision and a recall figure exist at all. What we can claim
is that the engine's *logic* is validated against planted truth, mutation-
tested, and that every claim on screen survives a hostile question. What we
cannot claim is that an operations lead would trust it — and the path to
finding out is a pilot, which is what we are asking for.
