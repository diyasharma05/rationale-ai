"""The BI hand-off: the engine's outputs as tables a Tableau, Power BI, Looker
or Qlik workbook can open, plus the API for anything that prefers JSON.

The brief allows platform-native, custom or hybrid. Rationale.AI is custom where
the reasoning happens and hybrid where the results land: the scan, the verdicts,
the ledger, the provenance and the contract graph are written here as CSV and
Parquet, so an existing dashboard can be augmented with "what moved, how sure
are we, who owns it" without the dashboard tool learning anything new.

    python -m ops.export_bi                       # July 2026, analyst, CSV + Parquet
    python -m ops.export_bi --period 2026-05 --role ceo --format csv --out data/exports

Nothing here is computed differently for the export: it is the same scan, the
same ledger and the same provenance the app shows, written to disk.
"""
import argparse
import json
import os
import pathlib
import sys
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MOCK_MODE", "1")

import pandas as pd                                        # noqa: E402

import feedback                                            # noqa: E402
from engine import db, graph                               # noqa: E402
from services import scan                                  # noqa: E402

DEFAULT_OUT = ROOT / "data" / "exports"

README = """# Rationale.AI : BI hand-off

Written by `python -m ops.export_bi` on {ts} for period {period}, role {role}.
Every table is also available as Parquet next to its CSV.

| File | One row per | Use it for |
|---|---|---|
| scan | KPI the role may see | The augmented dashboard tile: current value, movement, p and q values, material flag |
| kpi_series | KPI x month | Trend lines with the engine's own history |
| verdicts | investigation in the decision ledger | Outcome, confidence and any human verdict, for a "what did the engine conclude" panel |
| sources | source system | Provenance: kind, live or extract, rows, as-of |
| contract_graph_nodes / _edges | node / edge of the semantic contract | A lineage or ownership diagram in the BI tool |
| eval_cases | scored case in the evaluation harness | The accuracy panel |

## Connecting

* **Tableau**: Connect to a Text file (CSV) or use the Parquet connector; join `scan` to
  `kpi_series` on `kpi`. Refresh by re-running the export or scheduling it.
* **Power BI**: Get Data -> Text/CSV or Parquet for the files; or Get Data -> Web to call
  the API directly: `GET /scan?role_id=analyst&period={period}` and
  `POST /investigate` return the same numbers as JSON.
* **Looker / Looker Studio**: load the CSVs into the warehouse the engine reads (the
  contract SQL already runs there when `RATIONALE_DB` points at it) and model them; or
  call the API from a custom connector.
* **Qlik**: load the CSV or Parquet files; the REST connector can read `/scan` and
  `/sources`.

The reasoning stays in the engine. These tables are its outputs, not a second
computation, so a number here is the number the app shows.
"""


def frames(period: str, role_id: str) -> dict:
    out = {}
    rows = []
    for kpi_id, (cfg, _series, an) in scan.scan(role_id, period).items():
        rows.append({"kpi": kpi_id, "name": cfg["name"], "unit": cfg["unit"], "owner": cfg.get("owner"),
                     "period": period, "current": an.get("current"), "baseline_mean": an.get("mean"),
                     "pct_vs_recent": an.get("pct_vs_recent"), "z": an.get("z"), "p_value": an.get("p_value"),
                     "q_value": an.get("q_value"), "material": bool(an.get("material")),
                     "fdr_suppressed": bool(an.get("fdr_suppressed")), "sparse": bool(an.get("sparse"))})
    out["scan"] = pd.DataFrame(rows)
    series = []
    for kpi_id in db.allowed_kpis(role_id):
        s = db.kpi_series(kpi_id, role_id)
        s = s.assign(kpi=kpi_id)[["kpi", "period", "value"]]
        series.append(s)
    out["kpi_series"] = pd.concat(series, ignore_index=True) if series else pd.DataFrame(columns=["kpi", "period", "value"])
    led = feedback.read_ledger()
    out["verdicts"] = pd.DataFrame([{k: e.get(k) for k in ("id", "timestamp", "kpi", "period", "outcome",
                                                             "confidence", "feedback", "correction", "summary")}
                                    for e in led])
    out["sources"] = pd.DataFrame([{k: p.get(k) for k in ("table", "system", "kind", "status", "rows", "as_of",
                                                          "fetched_at", "grain", "refresh", "note")}
                                   for p in db.source_provenance()])
    g = graph.build(db.load_contract())
    out["contract_graph_nodes"] = pd.DataFrame(g["nodes"])
    out["contract_graph_edges"] = pd.DataFrame(g["edges"])
    ev = ROOT / "data" / "eval_results.json"
    if ev.exists():
        out["eval_cases"] = pd.DataFrame(json.loads(ev.read_text(encoding="utf-8"))["cases"])
    return out


def export(period: str, role_id: str, out_dir, fmt: str = "both") -> dict:
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    for name, df in frames(period, role_id).items():
        paths = []
        if fmt in ("csv", "both"):
            p = out_dir / f"{name}.csv"
            df.to_csv(p, index=False, encoding="utf-8")
            paths.append(str(p))
        if fmt in ("parquet", "both"):
            p = out_dir / f"{name}.parquet"
            df.to_parquet(p, index=False)
            paths.append(str(p))
        written[name] = {"rows": int(len(df)), "files": paths}
    (out_dir / "README.md").write_text(
        README.format(ts=datetime.now().strftime("%Y-%m-%d %H:%M"), period=period, role=role_id),
        encoding="utf-8")
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--period", default="2026-07")
    ap.add_argument("--role", default="analyst")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--format", choices=["csv", "parquet", "both"], default="both")
    a = ap.parse_args(argv)
    feedback.ensure_state()
    for name, info in export(a.period, a.role, a.out, a.format).items():
        print(f"  {name:22s} {info['rows']:>6} rows  ->  {', '.join(os.path.basename(f) for f in info['files'])}")
    print(f"README.md written to {a.out}; connect Tableau / Power BI / Looker / Qlik as described there.")


if __name__ == "__main__":
    main()
