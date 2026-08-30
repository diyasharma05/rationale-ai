# Rationale.AI — V0 Prototype

**Team Rational.ai · Accenture Innovation Challenge 2026 · Round 2 · Problem Track 3
(BusinessIntelligence.ai)**

A confidence-driven **KPI intelligence-to-action engine**: it detects and
**prioritises** material KPI movements deterministically, escalates through a
four-level reasoning pyramid (cross-functional signals → company context →
external signals → expert escalation) with confidence gates at every step, and
either recommends grounded actions or **abstains and asks** — it never invents
a story.

V1 highlights: a proactive **morning briefing** per persona, a plain-English
**"ask why" box** (hybrid keyword + Claude intent), live step-by-step
investigation progress, **ranked explanatory drivers** with strength scores,
action cards carrying **owners and decision rights** from the contract,
per-answer **"what could change this answer"**, source-freshness reconciliation,
and per-run latency/token/cost telemetry.

## Run it on a fresh machine (clone → frontend)

Prerequisites: **Python 3.11+** (tested on 3.13) and **git**. Works on Windows,
macOS and Linux. No API key is required — the demo runs fully offline out of the box.

```bash
# 1. Clone and enter the project
git clone https://github.com/diyasharma05/rationale-ai.git
cd rationale-ai

# 2. Create and activate a virtual environment
python -m venv .venv
#    Windows (PowerShell):
.venv\Scripts\Activate.ps1
#    macOS / Linux:
source .venv/bin/activate

# 3. Install dependencies (~2 min; includes streamlit, duckdb, scikit-learn, anthropic)
pip install -r requirements.txt

# 4. Generate the synthetic dataset (seeded — identical on every machine, ~30 s)
#    Creates data/*.csv, the unstructured documents, the market-event feed,
#    and resets the decision ledger.
python data/generate_data.py

# 5. Launch the app
streamlit run app.py
```

Your browser opens at **http://localhost:8501** — you land on the Dashboard.
Pick a role in the sidebar, set the analysis window (top right) to **July 2026**,
and click **Investigate** on any flagged KPI. Stop the app with `Ctrl+C`.

**LLM modes**
- **Offline (default):** with no `ANTHROPIC_API_KEY` set — or with `MOCK_MODE=1` —
  every investigation replays the committed fixtures in `llm/fixtures/` plus
  deterministic fallbacks. Nothing can fail on stage.
- **Live:** either paste your key in the app — sidebar → **LLM settings** →
  *Anthropic API key* → "Use this key" (held in memory only, never written to
  disk) — or set `ANTHROPIC_API_KEY` in your environment / a `.env` file before
  launching. Narratives are then generated fresh by Claude (~10–20 s per
  investigation, ≈ ₹1–3 each). "Go offline" switches back any time.
- `python record_fixtures.py` refreshes the offline fixtures from one live run
  (only this script can write fixtures).

**Verify the install (optional)**

```bash
python smoke_test.py   # engine: all planted scenarios produce the expected outcomes
python ui_test.py      # 11 headless UI checks (mock mode)
```

**Troubleshooting**
- *Port already in use* → `streamlit run app.py --server.port 8502`
- *Charts/theme look stale after editing code* → fully restart (`Ctrl+C`, rerun);
  Streamlit caches imported modules.
- *`streamlit` not found* → the virtual environment isn't activated (step 2).

## Design principle (judged)

**The LLM is never the source of quantitative truth.**

| Deterministic (SQL / stats / rules) | LLM |
|---|---|
| anomaly z-scores + materiality gates | evidence mapping snippet→hypothesis (Haiku 4.5) |
| contribution & driver analysis | persona narratives + escalation briefs (Sonnet 5) |
| retrieval ranking, event matching | |
| confidence arithmetic & all gates | |

## Repo map

```
app.py                    Streamlit UI (dashboard, investigation, ledger, under-the-hood)
contracts/kpi_contract.yaml  Semantic contract: definitions, SQL, drivers, thresholds,
                             levers, lineage, access — executed by the engine
roles.yaml                Row / column / domain security model
engine/                   pyramid.py (orchestrator), anomaly, contribution, drivers,
                          confidence, retrieve, db (DuckDB + RBAC)
llm/                      client.py (live/fixture/fallback), prompts, fixtures/
data/generate_data.py     Seeded generator with planted scenarios
telemetry.py              latency / tokens / cost per call and per investigation
feedback.py               decision ledger + feedback loop
smoke_test.py             end-to-end scenario verification
DEMO_SCRIPT.md            the 7-minute judge walkthrough
```

## Planted scenarios (July 2026)

| Scenario | Round-2 requirement it demonstrates |
|---|---|
| NW revenue −7%: fulfilment SLA collapse + 2 enterprise churns + competitor express launch | multi-factor movement with known drivers |
| Marketing conversion −16% with healthy spend/sessions (tracking bug) | low-confidence **abstention** + clarifying question |
| Home-decor category, 6 weeks old | sparse-history KPI, widened uncertainty |
| CEO masking / Sales-Head region filter / hidden KPIs | row + column + domain security |
| AOV −3.5%, not flagged | signal gate rejecting noise (alert fatigue) |
