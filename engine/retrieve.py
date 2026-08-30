"""Level-2 retrieval over unstructured company context + the decision ledger.

V0 uses transparent weighted keyword scoring (a real deployment would use
embeddings): each document is scored by term-frequency of the query terms,
with region names weighted 2x. Deterministic — same query, same ranking —
which also keeps the mock-mode fixtures stable.
"""
import json
import os
import re

from . import db

UNSTRUCT_DIR = os.path.join(db.DATA, "unstructured")
LEDGER_PATH = os.path.join(db.DATA, "state", "decision_ledger.jsonl")


def load_corpus():
    docs = []
    if os.path.isdir(UNSTRUCT_DIR):
        for fname in sorted(os.listdir(UNSTRUCT_DIR)):
            if fname.endswith(".txt"):
                with open(os.path.join(UNSTRUCT_DIR, fname), encoding="utf-8") as f:
                    docs.append({"file": fname, "kind": "document", "text": f.read()})
    if os.path.exists(LEDGER_PATH):
        with open(LEDGER_PATH, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    e = json.loads(line)
                    docs.append({
                        "file": f"decision_ledger:{e['id']}", "kind": "ledger",
                        "meta": {"kpi": e.get("kpi"), "period": e.get("period")},
                        "text": f"PAST INVESTIGATION {e['id']} | KPI: {e['kpi']} | "
                                f"period {e['period']} | confidence {e['confidence']}\n{e['summary']}",
                    })
    return docs


def build_query_terms(kpi_cfg: dict, focus_regions: list, driver_findings: list):
    terms = [(t.lower(), 1.0) for t in kpi_cfg.get("tags", [])]
    for r in focus_regions:
        terms.append((str(r).lower(), 2.0))
    for d in driver_findings:
        if d["status"] == "consistent":
            terms += [(t.lower(), 1.0) for t in d.get("tags", [])]
    seen, out = set(), []
    for t, w in terms:
        if t not in seen:
            seen.add(t)
            out.append((t, w))
    return out


def search(kpi_cfg: dict, focus_regions: list, driver_findings: list, role_id: str,
           k: int = 6, exclude_kpi: str = None, exclude_period: str = None):
    terms = build_query_terms(kpi_cfg, focus_regions, driver_findings)
    scored = []
    for doc in load_corpus():
        meta = doc.get("meta", {})
        # "Recall" means past precedent: current-period conclusions (this KPI's or a
        # sibling KPI's) are never fed back as evidence — avoids echo chambers
        if doc["kind"] == "ledger" and meta.get("period") == exclude_period:
            continue
        low = doc["text"].lower()
        score = sum(w * len(re.findall(re.escape(t), low)) for t, w in terms)
        if score > 0:
            scored.append((score, doc))
    scored.sort(key=lambda x: (-x[0], x[1]["file"]))
    snippets = []
    for rank, (score, doc) in enumerate(scored[:k], start=1):
        m = re.search(r"(20\d\d-\d\d(-\d\d)?)", doc["file"])
        snippets.append({
            "id": f"E{rank}",
            "file": doc["file"],
            "kind": doc["kind"],
            "date": m.group(1) if m else "",
            "score": round(score, 1),
            "text": db.mask_text(doc["text"][:700], role_id),
        })
    return {"terms": terms, "snippets": snippets, "corpus_size": len(load_corpus())}
