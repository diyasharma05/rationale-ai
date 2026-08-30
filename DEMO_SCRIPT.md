# Rationale.AI — Judge Demo Script (~7 minutes)

## Setup (before the room)

```
pip install -r requirements.txt
python data/generate_data.py        # regenerates data + resets the ledger
streamlit run app.py
```

- Offline insurance: set `MOCK_MODE=1` in `.env` (or just unplug — no key ⇒ mock).
  Everything below works identically on cached fixtures.
- Click **↺ Reset demo state** in the sidebar before starting.

## 1. The morning briefing — proactive, not reactive (45s)

Role: **Data Analyst** → Dashboard.
- Open on the **☀️ morning briefing card**: the engine already read the overnight
  scan and wrote a plain-language summary with a severity-ordered watchlist —
  "you don't ask it what's wrong; it tells you."
- Below it: the **source reconciliation strip** — 3 systems, different grains
  (transaction / daily / event / weekly) with as-of dates.
- KPI grid is **triage-ordered**: flagged first, worst first, with ₹/month impact
  on the cards. Point at AOV: moved −3.5% but *not* flagged → "this is the noise
  filter that kills alert fatigue."

## 2. Golden path — ask it like a human (2.5 min)

Go to Investigation and **type into the ask box: "Why did revenue fall in July?"**
— the engine maps the question to the governed KPI and starts on its own, showing
each pyramid level as it works (watch the live status steps).
- **Level 1 (non-LLM)**: z=−2.16, −7% → signal gate PASSES. Contribution pinpoints
  **North-West = 86% of the movement**, enterprise segment leading. Driver check
  from the contract: SLA ↓, complaints ↑29%, enterprise accounts ↓, marketing ↓ —
  4 candidate hypotheses.
- **Level 2**: retrieval over tickets/transcripts/ops notes **and the decision
  ledger** — show the Nov-2025 postmortem retrieved = the RECALL step. Claude
  (Haiku) maps snippets → hypotheses; the mapping is *counted* in Python.
- **Level 3 (non-LLM)**: SwiftKart express-delivery launch matches region+tags.
- **Gates**: evidence 0.60 ✓, action 0.75 ✓ → confidence ~0.83 → **ACTIONS**.
- The answer comes first, audit trail second (how a human wants to read it).
  Evidence citations [E1]… are clickable popovers under the narrative.
- **Ranked explanatory drivers** table: strength bars blend statistics, evidence
  and external confirmation — computed, not LLM-scored. H-marketing shows
  **UNCORROBORATED** — the engine says so openly.
- **Action cards**: lever → owner → **decision right** (who must approve, from
  the contract) → impact → monitoring → confidence pill.
- **"What could change this answer"** box — calibrated humility, from your deck's
  output spec.
- Open "Under the hood for this run": wall time, tokens, ₹ cost per insight.

## 3. Hallucination guard — the abstain scenario (1.5 min)

Investigate **Marketing Conversion Rate** (flagged, −16%).
- Both contract drivers (spend, sessions) are **quiet** — nothing upstream explains it.
- No document corroborates a cause; if the LLM proposes a tangential hypothesis it
  is **blocked by the hallucination guard** and shown as an "unvalidated lead".
- Confidence 0.35 → **ABSTAINS**, asks a clarifying question (tracking change?),
  and generates the **Level-4 expert escalation brief**. "The engine would rather
  say 'I don't know, ask a human' than invent a story."

## 4. Sparse history + persona + security (1.5 min)

- Investigate **Home-Decor Revenue**: launched 6 weeks ago → no baseline →
  monitoring-only, confidence capped, zero LLM tokens spent (deterministic path).
- Switch role to **CEO**, re-run Revenue: 3-sentence narrative, ₹ impact, one
  action — and account names are **masked to ACCT-codes** (column security),
  including inside the LLM prompt.
- Switch to **Sales Head — North**: dashboard shrinks to 4 KPIs (domain security),
  every number is North/North-West only (row security in the SQL layer). Show
  "Under the Hood → Security model".

## 5. Learning loop + economics (1 min)

- On any investigation: 👎 with a correction → show it appear in the **Decision
  Ledger** → future investigations retrieve it (past-period entries only — no echo
  chambers).
- **Under the Hood**: LLM vs non-LLM table (judged requirement), cumulative
  telemetry, cost per insight ≈ ₹1–3.

## Anticipated questions

- *Why not just an LLM over the warehouse?* → LLM never touches quantitative truth;
  show the breakdown table.
- *What if the API is down?* → flip to MOCK, same demo (fixtures + deterministic
  fallbacks).
- *Roadmap* → predictive mode (deck's Team Mentalist), embeddings retrieval, real
  ERP connectors, expert-network MCP integration, STL deseasonalization.
