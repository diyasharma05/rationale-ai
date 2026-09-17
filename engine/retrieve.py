"""Level-2 retrieval over unstructured company context + the decision ledger.

V0 uses transparent weighted keyword scoring (a real deployment would use
embeddings): each document is scored by term-frequency of the query terms,
with region names weighted 2x. Deterministic — same query, same ranking —
which also keeps the mock-mode fixtures stable.
"""
import os
import re
from functools import lru_cache

from . import db

import feedback as _fb

UNSTRUCT_DIR = os.path.join(db.DATA, "unstructured")


def load_corpus():
    docs = []
    if os.path.isdir(UNSTRUCT_DIR):
        for fname in sorted(os.listdir(UNSTRUCT_DIR)):
            if fname.endswith(".txt"):
                with open(os.path.join(UNSTRUCT_DIR, fname), encoding="utf-8") as f:
                    docs.append({"file": fname, "kind": "document", "text": f.read()})
    # read through feedback so the ledger location stays in one place (and so
    # RATIONALE_STATE isolation applies to retrieval too); tolerant of torn lines
    for e in _fb.read_ledger():
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
        if d["status"] == "co_moves":
            terms += [(t.lower(), 1.0) for t in d.get("tags", [])]
    seen, out = set(), []
    for t, w in terms:
        if t not in seen:
            seen.add(t)
            out.append((t, w))
    return out


MAX_LEDGER_SNIPPETS = 2


@lru_cache(maxsize=256)
def _term_re(term: str) -> str:
    """Whole-term matching, treating '-' as part of the word.

    Plain \\b is not enough: a hyphen is a non-word character, so \\bwest\\b
    happily matches inside "north-west" — which is how a national marketing
    investigation ended up retrieving the North-West enterprise exit-call
    transcript as its top evidence. Excluding '-' from both boundaries keeps
    "west" and "north-west" distinct terms.
    """
    return rf"(?<![\w-]){re.escape(term)}(?![\w-])"


def _admissible_ledger(meta: dict, exclude_period: str) -> bool:
    """Precedent must be strictly in the PAST.

    The old rule excluded only entries whose period equalled the analysis
    period, which let *future* conclusions in: analysing any month before the
    July incident pulled July's own conclusions back as evidence and filled all
    six slots, pushing every real source document out. Feedback-mirror rows are
    written with period "" and were never excluded at all.
    """
    p = (meta.get("period") or "").strip()
    if not p:
        return False                       # feedback mirrors carry no period
    if exclude_period and p >= exclude_period:
        return False                       # same period, or look-ahead
    return True


def search(kpi_cfg: dict, focus_regions: list, driver_findings: list, role_id: str,
           k: int = 6, exclude_kpi: str = None, exclude_period: str = None):
    terms = build_query_terms(kpi_cfg, focus_regions, driver_findings)
    corpus = load_corpus()          # once: it was loaded twice per search (scoring + corpus_size)
    scored = []
    for doc in corpus:
        is_ledger = doc["kind"] == "ledger"
        if is_ledger and not _admissible_ledger(doc.get("meta", {}), exclude_period):
            continue
        low = doc["text"].lower()
        score = sum(w * len(re.findall(_term_re(t), low)) for t, w in terms)
        if score > 0:
            scored.append((score, is_ledger, doc))
    scored.sort(key=lambda x: (-x[0], x[2]["file"]))
    # Cap self-authored precedent so a lived-in ledger cannot crowd out the
    # human-written corpus: source documents always keep most of the top-k.
    capped, n_ledger = [], 0
    for score, is_ledger, doc in scored:
        if is_ledger:
            if n_ledger >= MAX_LEDGER_SNIPPETS:
                continue
            n_ledger += 1
        capped.append((score, doc))
    scored = capped
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
    return {"terms": terms, "snippets": snippets, "corpus_size": len(corpus)}
