# Rationale.AI — Judge Demo Script (~8 minutes)

## Setup (before the room)

```
pip install -r requirements.txt
streamlit run app.py
```

- **Offline by default.** No key ⇒ cached fixtures. Unplug the network and the
  whole demo below is unchanged.
- Click **↺ Reset demo state** in the sidebar before starting.
- Optional, if you want the container story on screen: `docker compose up`
  brings up the app, the API (`localhost:8000/docs`), Prometheus and Grafana.

---

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

## 3. The hallucination guard — abstaining (1.5 min)

Investigate **Marketing Conversion Rate** (flagged, −16%).

- Both contract drivers (spend, sessions) are **quiet**.
- Regional contribution is **diffuse** — all five regions within noise of each
  other. The engine says so: *"no region stands out… which argues against a
  regional cause and towards something systemic."*
- Confidence 0.44 → **ABSTAINS**, asks a clarifying question about tracking,
  and produces a **Level-4 escalation brief**.
  > "It would rather say 'I don't know, ask a human' than invent a story."

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
- **"How does this deploy?"** → `docker compose up`. Same engine behind a
  FastAPI service (`/docs`), because `investigate(kpi, period, role)` is
  stateless given its inputs. RBAC is enforced at the API, not just the UI —
  a restricted role gets a 403.
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
