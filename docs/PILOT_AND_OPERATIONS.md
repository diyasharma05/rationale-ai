# From prototype to a client: the pilot, and what breaks on a Tuesday

The evaluators asked us to think beyond the prototype — customer needs, ROI,
time-to-market, scalability, operational realities. This is that page. The
durations are estimates from the shape of the work, not from a pilot we have
run; we have not run one, and we say so.

---

## 1. Who buys this, and what they use today

| Stakeholder | Job to be done | What they do today | Why it fails them |
|---|---|---|---|
| **Head of BI / Analytics** | Answer "why did X move?" fast enough to matter | Dashboards + an analyst opening a notebook | The *what* is instant; the *why* is a person-day, and the finding lives in a Slack thread |
| **COO / VP Operations** | Catch an operational incident before it reaches revenue | Threshold alerts on ops metrics | Alert fatigue: every metric alerts independently, so most alerts are ignored |
| **CFO / CRO** | Know which movements are real and what they cost | Monthly review deck, after the fact | Weeks of latency; no confidence attached to any explanation |
| **Data / platform team** | Not be the bottleneck for every "why" question | Ad-hoc SQL on request | Unrepeatable, unaudited, and the same question is answered again next month |

The buyer is usually the Head of BI or the COO. The *user* who has to trust it
is the operations lead who receives a dispatched action — and that trust is
the thing a pilot exists to earn.

## 2. The pilot, phase by phase

### Phase 0 — The contract workshop (2–3 weeks)

**This is the hard, human step, and we under-stated it in Round 2.** The
semantic contract has to be written by people who know the business: which
KPIs matter, how each is defined in SQL, what counts as material, which levers
exist, who owns them, and who may approve. That is a facilitated workshop with
the KPI owners, not a configuration task for an engineer.

Deliverable: a version-controlled contract for 5–10 KPIs, reviewed by their
owners. Exit criterion: each KPI owner has signed off their definition and
their decision rights.

### Phase 1 — Connect and backfill (1–2 weeks)

Point the contract's SQL at one existing mart or warehouse view per source.
Backfill 12+ months. Run the engine in **read-only** mode on history and check
the obvious: does it flag the incidents the client already knows about? Does
it stay quiet in the months they consider normal?

Exit criterion: recall on known past incidents, and a false-positive rate the
COO considers tolerable — decided with them, not for them.

### Phase 2 — Shadow mode (4–8 weeks)

The engine runs on live data and drafts everything — verdicts, evidence,
recommended actions, dispatch messages — but **sends nothing**. Analysts
compare its conclusions to their own. Every disagreement is logged as a verdict
in the ledger, which is also the learning loop's training signal.

This is where the thresholds get tuned to the client's risk appetite, and where
we find out whether the abstain verdict is valued or resented. We do not know
that yet.

Exit criterion: analysts agree with the rank-1 explanation on a share of cases
the client sets in advance, and the abstention rate is acceptable to the people
who receive the escalations.

### Phase 3 — Governed dispatch, narrowly (4+ weeks)

Turn on dispatch for **one KPI, one lever, one owner** who has opted in. Human
approval remains mandatory. Widen only as trust is earned.

Exit criterion: the owner reports the messages were actionable, and the
realised impact of accepted actions is tracked against what the engine
predicted — which the ledger makes measurable.

**Realistic total: three to five months to a trusted, narrowly-dispatching
deployment.** Anyone who tells you it is weeks has not done the workshop.

## 3. Value, stated as a model rather than a number

We do not have a client's numbers, so we give the shape of the calculation
and the inputs a client would fill in.

**Time to diagnosis.** Today: an analyst-day or more per material movement,
plus the elapsed calendar time until someone is free. With the engine: minutes
to a ranked, evidenced explanation or an honest abstention. Value = (analyst
hours saved × loaded cost) + (days of earlier action × daily cost of the
problem).

**The second term dominates.** In the planted scenario, the warehouse conveyor
failed on June 25 and the monthly revenue signal did not clear its bar until
the July numbers closed. The live detector on daily data flagged the region
within days. For a retailer losing on the order of ₹90k/day in one region,
every day of earlier action is that much recovered. Fill in your own daily
number; the structure is what matters.

**Alert fatigue, avoided.** Seven KPIs tested independently produce roughly
one false alarm a month before anyone has done anything wrong. Every false
alarm is an analyst-day and, worse, a reason to ignore the next real one.
Multiplicity control removed both false positives in our evaluation set at no
cost to recall.

**Running cost.** ₹1–3 per investigation in model calls (measured, not
estimated), plus compute that is small at this scale. Ten thousand
investigations a month is tens of thousands of rupees — a rounding error
against one analyst.

**What we cannot yet claim.** Any of this against real outcomes. Phase 3 is
where the realised-vs-predicted impact becomes a measured number, and it is
the number a CFO will actually care about.

## 4. Day-2 operations: what breaks on a Tuesday

| It's Tuesday and… | What happens | What we have | What we would add |
|---|---|---|---|
| **The nightly load is late** | The analysis month is incomplete; run-rates look low | Source freshness is shown per system on the dashboard and lineage page | A freshness gate: do not score a period whose source is behind its declared refresh |
| **A column is renamed upstream** | Contract SQL fails | Every query is wrapped; the UI shows an error, not a traceback | Contract CI runs every KPI's SQL against the mart on each change |
| **A KPI owner wants a new threshold** | Materiality changes for everyone | Contract is version-controlled; `eval.py --check` guards regressions | A review step: owner proposes, BI approves, CI shows the effect on past months before merge |
| **The model provider ships a new version** | Prose changes; numbers do not | Model IDs are pinned; the golden-set fixtures are a regression corpus | Re-record fixtures on a schedule and diff the prose; numbers are unaffected by construction |
| **Someone asks "who approved that message?"** | Audit request | Append-only ledger and outbox: draft, approval, send are separate events with actor and time | Export to the client's audit system |
| **The IsolationForest starts flagging every month** | Drift or a regime change | Verdict is cached on a content hash and shows its decision margin | Drift monitoring on the flag rate; automatic fall-back to the statistical test alone |
| **A dispatched action was wrong** | Trust damage | Human approval was mandatory; the verdict can be marked wrong, which demotes that explanation next time | An incident review template, and dispatch auto-pauses for that KPI until reviewed |
| **The API is slow** | p95 climbs | Benchmark in CI with budgets; service is stateless | Add replicas behind the load balancer; the curve says where |
| **A restricted role sees something they shouldn't** | Security incident | Row filter in SQL, masking before the prompt, cache keys include the role, tests assert isolation | Warehouse-native row-access policies replace our injection at production scale |

## 5. What we would need from Accenture, if this went further

- A client with a warehouse, 12+ months of history, and one known past incident
  to validate against.
- Two to three KPI owners willing to spend a day in the contract workshop.
- One operations lead willing to receive dispatched messages in shadow mode
  first and tell us, honestly, whether they would act on them.

That last person is the one we have not yet met, and everything above is
weaker until we have.
