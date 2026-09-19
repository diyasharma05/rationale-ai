"""The semantic contract as a knowledge graph.

The contract already is one: systems host sources, sources feed KPIs, KPIs drive
other KPIs with a declared direction, levers control KPIs, owners own levers and
approvers approve them. This module makes the graph explicit -- for the Lineage
page to draw, for the API to serve -- and, more usefully, traversable:

    downstream(kpi)  which KPIs declare this one as a driver, and how
    exposure(kpi)    the blast radius of a movement: downstream KPIs, their
                     owners, and the levers those owners hold

The engine already walked one edge of this graph before it had a name
(drivers._is_unexplained looks one level upstream); naming the graph lets the
Investigation page say who else a movement touches, from the contract rather
than from the model.
"""

NODE_TYPES = ("system", "source", "kpi", "metric", "lever", "owner", "approver")


def build(contract: dict) -> dict:
    nodes, edges = {}, []

    def node(nid, ntype, label, **attrs):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "type": ntype, "label": label, **attrs}
        return nid

    for src, spec in (contract.get("sources") or {}).items():
        sys_id = node(f"system:{spec.get('system', src)}", "system", spec.get("system", src))
        src_id = node(f"source:{src}", "source", src, kind=spec.get("kind", ""), grain=spec.get("grain", ""))
        edges.append({"source": sys_id, "target": src_id, "type": "hosts"})
    for kpi_id, cfg in contract["kpis"].items():
        k = node(f"kpi:{kpi_id}", "kpi", cfg["name"], unit=cfg.get("unit", ""), owner=cfg.get("owner", ""))
        if cfg.get("source"):
            edges.append({"source": f"source:{cfg['source']}", "target": k, "type": "feeds"})
        for d in cfg.get("drivers", []):
            if "kpi" in d:
                edges.append({"source": f"kpi:{d['kpi']}", "target": k, "type": "drives",
                              "relation": d.get("relation", "")})
            else:
                m = node(f"metric:{d['metric']}", "metric", d.get("label", d["metric"]))
                edges.append({"source": m, "target": k, "type": "drives", "relation": d.get("relation", "")})
        for lv in cfg.get("levers", []):
            l_id = node(f"lever:{lv['lever']}", "lever", lv["lever"])
            edges.append({"source": l_id, "target": k, "type": "controls"})
            if lv.get("owner"):
                o = node(f"owner:{lv['owner']}", "owner", lv["owner"])
                edges.append({"source": o, "target": l_id, "type": "owns"})
            appr = str(lv.get("approval", "") or "")
            if appr and not appr.lower().startswith("none"):
                a = node(f"approver:{appr}", "approver", appr)
                edges.append({"source": a, "target": l_id, "type": "approves"})
    return {"nodes": list(nodes.values()), "edges": edges}


def downstream(contract: dict, kpi_id: str) -> list:
    """KPIs that declare `kpi_id` as one of their drivers."""
    out = []
    for other, cfg in contract["kpis"].items():
        for d in cfg.get("drivers", []):
            if d.get("kpi") == kpi_id:
                out.append({"kpi": other, "name": cfg["name"], "relation": d.get("relation", ""),
                            "note": d.get("note", ""), "owner": cfg.get("owner", "")})
    return out


def upstream(contract: dict, kpi_id: str) -> list:
    cfg = contract["kpis"][kpi_id]
    return [{"id": d.get("kpi") or d.get("metric"), "relation": d.get("relation", ""),
             "kind": "kpi" if "kpi" in d else "metric"} for d in cfg.get("drivers", [])]


def exposure(contract: dict, kpi_id: str) -> dict:
    """Who else a movement in `kpi_id` touches, from the contract alone."""
    down = downstream(contract, kpi_id)
    owners = {}
    for d in down:
        for lv in contract["kpis"][d["kpi"]].get("levers", []):
            owners.setdefault(lv.get("owner", ""), set()).add(lv["lever"])
    return {"kpi": kpi_id, "downstream": down,
            "owners": [{"owner": o, "levers": sorted(ls)} for o, ls in sorted(owners.items()) if o]}


def counts(graph: dict) -> dict:
    c = {t: 0 for t in NODE_TYPES}
    for n_ in graph["nodes"]:
        c[n_["type"]] = c.get(n_["type"], 0) + 1
    return {"nodes": len(graph["nodes"]), "edges": len(graph["edges"]), **c}
