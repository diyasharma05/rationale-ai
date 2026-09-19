# Rationale.AI — Judge Demo Script (~8 minutes)

## Setup (before the room)

```
pip install -r requirements.txt
streamlit run app.py
```

- **Offline by default.** No key ⇒ cached fixtures. Unplug the network and the
  whole demo below is unchanged.
- Click **↺ Reset demo state** in the sidebar before starting.
- Optional, for the live-data beat: in a second terminal run
  `python -m ops.ingest --rate 2 --inject-anomaly 40`. Leave it running.
- Optional, to post into a real Slack channel on stage (use a throwaway
  channel): set `SLACK_BOT_TOKEN`, `SLACK_TEAM_ID`, `RATIONALE_MCP_CHANNEL`
  (the channel id), `RATIONALE_MCP_COMMAND="npx -y @modelcontextprotocol/server-slack"`
  and `RATIONALE_DISPATCH=mcp` in the shell before `streamlit run`. Test it
  once the night before; if the venue network is doubtful, leave it in dry run.
- Optional, if you want the container story on screen: `docker compose up`
  brings up the app, the API (`localhost:8000/docs`), Prometheus and Grafana.
- Optional, for the portability beat (no Docker needed): the night before, run
  `python -m ops.pg_local init` once. On the day, set the `RATIONALE_DB` line it
  prints and launch a second `streamlit run app.py` on another port. The Lineage
  page names the engine; the verdicts are the same to three decimals.

---

## 0. Thirty seconds of honesty, first (30s)

Before touching the app, say this — evaluators who discover it themselves
will remember that you didn't:

> "Everything you're about to see runs on a synthetic dataset for an invented
> retailer, with known causes planted in it. No real user has used this yet.
> That is a limitation — and it is also the only reason we can show you a
> precision and a recall. Real data doesn't come with an answer key. The pilot
> plan starts with the human step that changes this: a contract workshop with
> the people who own the KPIs."

Then: "The rule the whole system is built on: the model never computes a
number and never decides who gets told. It writes sentences."

## 1. Triage, not a dashboard (45s)

Role: **Data Analyst** → Dashboard.

- The KPI grid is **ordered by severity**, not alphabetically: flagged first,
  worst first, with ₹/month impact on the cards.
- Point at **AOV**: it moved −3.5% and is *not* flagged. "That's the noise
  filter. Most BI tools would have alerted on it."
- Point at the **source reconciliation strip**: three systems, four grains
  (transaction / daily / event / weekly), each with its own as-of date.

> If asked "why is the data seven weeks old?" — it's a fixed synthetic dataset
> pinned to the incident month, so the demo is reproducible. Say so plainly.

## 2. Golden path — and why it stops short (2.5 min)

Investigation → type **"Why did revenue fall in July?"** → **Ask**.

- **Level 1 (no LLM)**: revenue is down 7%. Contribution pinpoints
  **North-West = 86% of the movement**. Four contract drivers are checked.
- **The multiplicity line** — this is the one to land slowly:
  > "We test seven KPIs every month. At a 2-sigma bar you get a false alarm
  > roughly one month in four, just from testing seven things. So we control
  > the false *discovery* rate across the whole portfolio. Five of seven
  > flagged this month, FDR-controlled at 10%."
- **The distractor**: marketing conversion has the **largest** movement of any
  driver — and the engine ranks it **last**, badged *"nothing upstream explains
  why it moved: treated as a lead, not as corroboration."* It is a tracking
  bug, and the engine worked that out without being told.
- **Level 2**: retrieval over tickets, transcripts and ops notes, plus the
  decision ledger. Citations `[E1]…` are clickable.
- **The verdict is TENTATIVE, at 0.71 confidence.** Do not apologise for this —
  it is the most important thing on the screen:
  > "Revenue's own signal is marginal: p is about 0.07. The conviction comes
  > from four corroborating drivers and the documents, not from revenue itself.
  > So the engine offers low-regret steps and says what would change its mind.
  > It does not claim an established root cause at 0.71."
- Action cards: lever → owner → **decision right** (who must approve) → impact
  → monitoring.
- Open **"Under the hood for this run"**: wall time, tokens, ₹ cost.

> On the Live Feed, call it a **replay**, never "live". It walks real rows
> with a date cursor and the detector is genuine, but the clock is not.
> "Flight recorder" is accurate and lands just as well; the Lineage page is
> where you show something genuinely live.

## 3. The hallucination guard — abstaining (1.5 min)

Investigate **Marketing Conversion Rate** (flagged, −16%).

- Both contract drivers (spend, sessions) are **quiet**.
- Regional contribution is **diffuse** — all five regions within noise of each
  other. The engine says so: *"no region stands out… which argues against a
  regional cause and towards something systemic."*
- Confidence 0.44 → **ABSTAINS**, asks a clarifying question about tracking,
  and produces a **Level-4 escalation brief**.
  > "It would rather say 'I don't know, ask a human' than invent a story."
- **Then close the loop.** The question is on screen with an answer box. Pick
  *Yes — it confirms it*, type *"a checkout tracking tag change shipped on 3
  July"*, record. It re-runs: **ABSTAIN → TENTATIVE**, the human's statement
  ranked first, tagged with the role that said it, retrieved as evidence E1.
  No actions appear — there is no contract lever for fixing a tag, and the
  engine does not invent one.
  > "The engine decided to ask. A person supplied a fact. It recomputed. That
  > is the only autonomy we added, and notice what it did NOT do: it did not
  > jump to ESTABLISHED. Testimony is not measurement."
- If someone asks "is this agentic?": it perceives, reasons, decides, acts and
  learns — yes. What it never does is let the model plan, pick a tool, or
  choose a recipient. Point at this exact moment as where the autonomy line is.

## 4. Sparse history, personas, security (1.5 min)

- **Home-Decor Revenue**: launched six weeks ago → no baseline →
  monitoring-only, zero LLM tokens.
- Switch to **CEO**, re-run Revenue: short narrative, no statistics vocabulary
  anywhere, account names **masked to ACCT-codes** — including inside the LLM
  prompt, not just on screen.
- Switch to **Sales Head — North**: four KPIs instead of seven (domain), every
  number North-only (row security in the SQL). Under the Hood → Security model.

## 5. The learning loop, for real (1 min)

On the revenue investigation: **👎 Wrong** with a correction, then **Re-run**.

- The rejected explanation **drops from rank 1 to rank 3** and is visibly
  demoted; the next-best driver takes the lead.
  > "An upvote and a downvote used to be the same thing. Now a correction
  > changes the ranking, and a conclusion a human rejected is dropped from the
  > evidence pool entirely."

## 5a. The last mile — governed dispatch (1 min)

On the fulfilment SLA investigation (it reached ACTIONS): scroll to **Send this
to the people who can act**.

- The preview shows where each action goes: **VP Operations**, approval
  **COO (pre-approved playbook per Nov-2025 postmortem)**. Say where that came
  from:
  > "The model didn't pick that recipient. The contract did. Every lever in
  > the semantic contract names who acts and who signs off. The model writes
  > the sentence; it never chooses the envelope. Same rule as the numbers,
  > one layer up."
- **Draft dispatch** → Nav → **Outbox**. The message is there, in full: the
  movement, the recommended action, the expected effect, how you'd know it
  worked, the decision right, the confidence stated honestly, the evidence
  IDs. Nothing has been sent.
- **Approve & send.** It moves to *sent*, with who approved it and when.
  > "Nothing leaves without a person. The engine drafts and routes; a human
  > decides. That is the abstain principle applied to the outbound path."
- Now go back and look at the **revenue** (TENTATIVE) preview: the messages
  are marked FOR REVIEW and the body says *below the action threshold, not as
  a diagnosis*. And **marketing conversion** (ABSTAIN) produces one message —
  an escalation to the KPI owner asking a specific question, not an
  instruction to anyone.
- If asked why it isn't posting to real Slack: it's a dry run by default, on
  purpose. An engine that can message people is a different risk class from
  one that draws a page. Delivery is one env var — `RATIONALE_DISPATCH=mcp` —
  and the transport is MCP, so it plugs into whatever the client already
  runs: Slack, email, Jira, ServiceNow. The adapter is tested end-to-end
  against a real MCP server (it discovers the posting tool and maps the
  arguments from the server's schema). What it has not done unless you set
  it up beforehand is post into an actual Slack workspace — that needs a
  bot token; see the setup note above. Say which of those two you have.

## 5b. Where the data comes from (1 min)

Nav → **Lineage**. This is the answer to "is this real data?", and the honest
answer has two halves.

- **Provenance.** Four named source systems with measured row counts, grains,
  declared refresh cadences and actual date spans. Pick a KPI and the page
  shows the whole chain: system → DuckDB table → the governed SQL → the row
  filter for this role → the anomaly test → multiplicity control.
- Switch role to **Sales Head** and the row counts change with you: 85,222
  orders becomes 40,542. The row filter applies to the lineage page too.
- **Say the synthetic part first, before anyone asks.** The dataset is
  generated with known causes planted in it, and that is *why* there is a
  precision and recall number at all. Real client data arrives without an
  answer key.
- **Live ingestion.** Scroll to the bottom. A second process is appending
  events right now; the counter climbs, and once North-West degrades the same
  rolling rule flags it:
  > "The Live Feed you saw earlier is a replay — a flight recorder of the
  > incident, at speed. This is different: that data did not exist when this
  > page loaded. It proves the ingestion path is real, not a fixture."
- It writes to its own lane, not into the demo tables — mutating those would
  move the numbers you just showed. Worth saying; it reads as discipline.

## 6. Does it actually work? (1 min)

Under the Hood → **"Does it actually get the right answer?"**

- **Precision 100%, recall 100%** across 36 cases and five control months,
  scored against planted ground truth.
- **Gate separation**: the evidence gate has a 0.25 margin — nothing lands near
  it. The action gate has 0.064, and we say so rather than hide it.
- Mention the harness is mutation-tested: seed a wrong expected driver and
  root-cause accuracy drops 4/4 → 3/4. It can fail.

---

## Anticipated questions

- **"Why not just an LLM over the warehouse?"** → The LLM never touches a
  number. Show the method strip: SQL queries, statistical tests, ML models,
  documents retrieved, and *"LLM · words only"*.
- **"What if the API is down?"** → It already is. This entire demo has been
  running offline on cached responses.
- **"Where's the causal inference / forecasting / knowledge graph?"** → On the
  revenue investigation, scroll to *Causal estimate*: difference-in-differences,
  North-West against the other four regions, about −₹0.7 lakh a day with its
  interval and the pre-period check; roughly 82% of the month's movement. Then
  open marketing conversion: *Not identifiable* — no untreated region, so it
  says so. The forecast band sits under every chart with R² stated. The
  contract graph is on the Lineage page; pick a KPI to light up its neighbourhood.
- **"Does anything happen without a click?"** → `python -m ops.watch` in a
  terminal: it scans, drafts into the Outbox for every material movement, and
  stops. Nothing sends until a person approves.
- **"How does this deploy?"** → `docker compose up`. Same engine behind a
  FastAPI service (`/docs`), because `investigate(kpi, period, role)` is
  stateless given its inputs. RBAC is enforced at the API, not just the UI —
  a restricted role gets a 403.
- **"Isn't this all DuckDB? Where does the ledger live with replicas?"** →
  One variable. `RATIONALE_DB` points the same contract at PostgreSQL; the
  ledger and outbox become one shared append-only table the app can only
  INSERT into. Show the Lineage page saying PostgreSQL, then the same revenue
  verdict at 0.715. DuckDB stays the default because a demo laptop should
  need no server.
- **"How far does it scale?"** → Show the measured curve: ~8-9 req/s on one
  process, p50 243ms at N=1 rising to 1.7s at N=16, zero wrong answers at any
  level. Past that you add replicas; the service is stateless. At 100M rows you
  don't scan them — investigations read a pre-aggregated mart, so rows scanned
  per investigation stays flat.
- **"Data residency / PII?"** → Masking happens *before* the prompt. Only
  precomputed aggregates and masked snippets ever leave the perimeter.
- **"Why q = 0.10?"** → Standard for exploratory screening. Be honest that it
  is load-bearing: at q=0.05 the July revenue movement itself would be
  suppressed, and we have a regression test pinning that margin.
- **Roadmap** → STL deseasonalisation, embedding retrieval, real ERP
  connectors, and a genuine causal layer (difference-in-differences on the
  region split) to replace co-movement.

## What we tell them we have NOT solved

No seasonality decomposition. Retrieval is weighted keyword matching, not
embeddings. The contract *declares* the causal links; the engine only tests
concurrent movement and says so in those words. Ground truth is synthetic —
it validates the engine's logic, not real-world accuracy.
