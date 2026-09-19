# The problem, before the solution

**What this is.** The evaluators asked us to stay with the problem, analyse it
from several stakeholders' angles, and ground it in genuine need. This page does
that with published evidence, because we have not been able to interview users
directly. **That is a limitation and we state it rather than imply validation
we do not have.** Every figure below is from a cited secondary source; none is
ours. Where a source is from an adjacent domain (security operations rather
than business intelligence), we say so and explain why we think the dynamic
transfers.

---

## 1. The problem in one sentence

Organisations can see *what* changed instantly and find out *why* slowly, so
decisions are made either late or on an unverified explanation — and the tools
now being sold to close that gap (LLMs over data) introduce a new failure mode:
fluent, confident, wrong.

## 2. Four stakeholders, four versions of the problem

### The analyst: the "why" is a person-day

Dashboards answer *what moved*. Answering *why* is manual: pull the breakdowns,
check the adjacent metrics, search Slack for what ops did that week, write it up.
The best published proxy we found: a survey of 200+ data professionals found it
takes **about 19 hours to resolve a data anomaly, with the vast majority of that
time spent finding the root cause**
([Monte Carlo / Barr Moses](https://barrmoses.medium.com/the-data-engineers-guide-to-root-cause-analysis-e407d9e48362)).
That is data-quality anomalies specifically, not KPI movements — but the work
is the same shape: a signal, then a hunt through adjacent systems for a cause.
The same source describes teams "mostly in firefighting mode, looking into the
ad hoc requests coming from the business teams."

**What this means for the design:** the engine has to produce the *ranked,
evidenced explanation* — not just the alert — or it saves nobody anything.

### The operations lead: every metric alerts, so none do

Threshold alerting on many metrics independently produces a stream of alerts,
most of which are noise, and the people receiving them learn to ignore the
stream. The clearest quantified evidence is from security operations, which
has studied this for a decade: **73% of teams cite false positives as their
number-one detection challenge** (SANS 2025 Detection & Response Survey, via
[Stamus Networks](https://www.stamus-networks.com/blog/what-the-2025-sans-detection-response-survey-reveals-false-positives-alert-fatigue-are-worsening));
Microsoft/Omdia's State of the SOC found **46% of all alerts are false
positives**, and organisations report **63% of alerts go unaddressed**
([secure.com](https://www.secure.com/blog/soc/soc-alerts),
[Vectra](https://www.vectra.ai/topics/alert-fatigue)).

We think this transfers because the mechanism is statistical, not domain-
specific: test N things independently at a fixed threshold and the family-wise
false-positive rate compounds. In our own system, seven KPIs at a 2σ bar gave
roughly a 28% chance of at least one phantom alert per month before we added
multiplicity control — and it produced two, in two control months.

**What this means for the design:** control the error rate across the whole
portfolio, not per metric, and be willing to stay silent.

### The executive: relies on dashboards, doesn't trust them, has no time to check

A 2025 survey of business leaders found **77% rely on dashboards and only
sometimes or rarely question the data**, while **67% worry that this over-
reliance risks decisions made on false pretences**
([TheyDo, 2025](https://www.theydo.com/resources/2025-leadership-perspective)).
Separately, the 2025 Data Integrity Report found **67% of organisations do not
completely trust the data they use for decisions, up from 55% the year before**
(via [CXM](https://cxm.world/cxm-news/75-of-leaders-blindly-trust-data-despite-fears-of-missed-opportunities/)).
**Half of executives feel overwhelmed by the volume of dashboards they
receive**; 34% cite lack of time to scrutinise the data
([Data Centre Solutions](https://datacentre.solutions/news/19365-half-of-executives-feel-overwhelmed-by-the-sheer-volume-of-data-and-dashboards-they-receive-daily)).

This is the paradox the product lives in: the people making the decisions
depend on the numbers, doubt them, and lack time to verify them. What they
need is not another dashboard. It is an explanation *with its confidence
attached* — and an honest "we don't know yet" when that is the truth.

**What this means for the design:** a persona-appropriate narrative, a visible
confidence, and abstention as a first-class outcome.

### The data platform team: the obvious fix has a known failure mode

The industry's current answer is an LLM over the warehouse. On academic
benchmarks this looks solved; on real enterprise schemas it is not. The
Spider 2.0 benchmark, built from real enterprise workflows, found the same
model that scored **91.2% on the academic Spider 1.0 scored 21.3% on Spider
2.0**; by April 2025 the best execution accuracy was **31%**
([Atlan, citing ICLR 2025](https://atlan.com/know/ai-agent/data-for-ai/text-to-sql-for-enterprise/)).
Roughly **81% of text-to-SQL errors are schema and semantic failures** — the
model inventing plausible column names, joins and filters — rather than syntax
(same source). A domain-specific BI benchmark found a model at **93% on simple
aggregations dropping to 4% on arithmetic reasoning**
([arXiv 2505.00060](https://arxiv.org/pdf/2505.00060)).

And the mitigation the field is converging on is the one we built: a 2026 dbt
Labs benchmark measured **semantic-layer grounding lifting accuracy from 90.0%
to 98.2%** ([Atlan](https://atlan.com/know/ai-agent/data-for-ai/text-to-sql-for-enterprise/)).
Our semantic contract is exactly that layer — with the further step that the
model never writes the SQL at all; the contract does.

**What this means for the design:** the model must not be in the numerical
path. Not "grounded", not "checked" — absent.

## 3. What we are actually solving, stated precisely

Given a governed set of KPIs and their declared relationships:

1. **Detect** material movements with a controlled false-discovery rate across
   the whole set, so that an alert means something.
2. **Explain** each one with a ranked, evidenced set of hypotheses computed by
   deterministic methods, with the strength of each shown honestly — including
   when a co-moving driver is itself unexplained.
3. **Decide whether to conclude**, and abstain with a specific question when
   the evidence does not support a conclusion.
4. **Route** what the contract allows to the person the contract names, with
   the approval it requires, only after a human agrees.
5. **Learn** from the human's verdict, so a rejected explanation ranks lower
   next time.

Everything the model does is write sentences about facts it was handed.

## 4. What we have deliberately not solved

- **Causal inference, beyond one design.** The contract declares causal links;
  the driver checks test concurrent movement and say "co-moves", not "causes".
  The one causal estimate is a difference-in-differences on the regional panel,
  available only when an untreated region exists as a control.
- **Seasonality.** Stationary baseline over ≤ 12 months.
- **Real users.** Nobody outside the team has used this. The pilot plan
  (`docs/PILOT_AND_OPERATIONS.md`) is the path to changing that, and the
  contract-authoring workshop it starts with is where the domain understanding
  the evaluators asked about would actually enter the system.

## 5. Assumptions we are making, and how each could be wrong

| Assumption | If wrong… | How we would find out |
|---|---|---|
| An ops lead values an engine that says "I don't know" | Abstention reads as failure, not honesty | Shadow-mode pilot, phase 2 |
| A 0.75 action gate matches a business's risk appetite | Too cautious (misses) or too eager (spam) | Tune with the client in phase 1–2; the gate-separation report shows the margin |
| Lever owners and approvers can be written down | Decision rights are informal and contested | The contract workshop will surface this in the first hour |
| A dispatched message is actionable | It is one more notification to ignore | Phase 3, one lever, one owner who opted in |
| Monthly grain is the right unit for "why" | Incidents need daily detection and monthly explanation | Already partly true: the live detector is daily, the diagnosis is monthly |

---

### Sources

- [The Data Engineer's Guide to Root Cause Analysis — Barr Moses, Monte Carlo](https://barrmoses.medium.com/the-data-engineers-guide-to-root-cause-analysis-e407d9e48362)
- [SANS 2025 Detection & Response Survey summary — Stamus Networks](https://www.stamus-networks.com/blog/what-the-2025-sans-detection-response-survey-reveals-false-positives-alert-fatigue-are-worsening)
- [What percentage of SOC alerts are false positives — secure.com](https://www.secure.com/blog/soc/soc-alerts)
- [Alert fatigue — Vectra AI](https://www.vectra.ai/topics/alert-fatigue)
- [Data, decisions, and doubt: a 2025 leadership perspective — TheyDo](https://www.theydo.com/resources/2025-leadership-perspective)
- [75% of leaders blindly trust data — CXM](https://cxm.world/cxm-news/75-of-leaders-blindly-trust-data-despite-fears-of-missed-opportunities/)
- [Half of executives feel overwhelmed by dashboards — Data Centre Solutions](https://datacentre.solutions/news/19365-half-of-executives-feel-overwhelmed-by-the-sheer-volume-of-data-and-dashboards-they-receive-daily)
- [Text-to-SQL for Enterprise — Atlan (Spider 2.0, dbt Labs benchmark)](https://atlan.com/know/ai-agent/data-for-ai/text-to-sql-for-enterprise/)
- [Fact-Consistency Evaluation of Text-to-SQL for BI — arXiv 2505.00060](https://arxiv.org/pdf/2505.00060)
