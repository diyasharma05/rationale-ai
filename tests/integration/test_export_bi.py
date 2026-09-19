"""The BI hand-off writes the engine's outputs, not a second computation."""
import pandas as pd

import feedback as fb
from ops import export_bi
from services import scan


def test_export_writes_every_table_in_both_formats(tmp_path):
    fb.reset_ledger()
    written = export_bi.export("2026-07", "analyst", tmp_path, "both")
    assert set(written) >= {"scan", "kpi_series", "verdicts", "sources", "contract_graph_nodes",
                            "contract_graph_edges", "eval_cases"}
    for name, info in written.items():
        assert len(info["files"]) == 2 and all((tmp_path / f"{name}.{ext}").exists() for ext in ("csv", "parquet"))
    assert (tmp_path / "README.md").exists()
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "Power BI" in readme and "Tableau" in readme and "/scan?role_id=analyst" in readme


def test_scan_export_matches_the_dashboard_scan(tmp_path):
    export_bi.export("2026-07", "analyst", tmp_path, "csv")
    df = pd.read_csv(tmp_path / "scan.csv")
    live = scan.scan("analyst", "2026-07")
    assert len(df) == len(live) == 7
    flagged = set(df.loc[df["material"], "kpi"])
    assert flagged == {k for k, (_c, _s, an) in live.items() if an["material"]}
    assert set(df.columns) >= {"kpi", "current", "z", "p_value", "q_value", "material", "owner"}


def test_export_respects_the_role(tmp_path):
    export_bi.export("2026-07", "sales_head_north", tmp_path, "csv")
    df = pd.read_csv(tmp_path / "scan.csv")
    assert len(df) == 4 and "marketing_conversion" not in set(df["kpi"])
    src = pd.read_csv(tmp_path / "sources.csv")
    assert len(src) == 4


def test_parquet_round_trips(tmp_path):
    export_bi.export("2026-07", "analyst", tmp_path, "parquet")
    edges = pd.read_parquet(tmp_path / "contract_graph_edges.parquet")
    assert {"source", "target", "type"} <= set(edges.columns) and len(edges) == 52
