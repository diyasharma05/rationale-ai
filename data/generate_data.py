"""Seeded synthetic data generator for the Rationale.AI V0 prototype.

Planted narrative (July 2026, North-West region):
  - NW enterprise revenue collapses: 2 accounts churn (Meridian, Kalinga),
    remaining NW enterprise accounts order ~25% less.
  - NW fulfilment degrades from ~June 25 (warehouse WH-07 conveyor failure):
    SLA breach rate 8% -> 20%, delivery days 2.6 -> 3.5.
  - NW complaints +~50% during July-Aug.
  - Competitor "SwiftKart" launches 2-day express delivery July 1 (market event).
  - Marketing conversions under-count from July 1 (analytics tagging bug):
    spend/sessions UP, conversions DOWN -> contradictory-evidence scenario.
  - "home-decor" category launches 2026-07-15 -> sparse-history scenario.

Run:  python data/generate_data.py
"""
import json
import os
from datetime import date, timedelta

import numpy as np
import pandas as pd

rng = np.random.default_rng(42)

HERE = os.path.dirname(os.path.abspath(__file__))
START = date(2025, 8, 1)
END = date(2026, 8, 25)

REGIONS = {"North": 0.18, "North-West": 0.30, "South": 0.22, "East": 0.12, "West": 0.18}
CATEGORIES = {"electronics": 0.36, "grocery": 0.32, "fashion": 0.32}
HOME_DECOR_LAUNCH = date(2026, 7, 15)

ENT_ACCOUNTS_PER_REGION = {"North": 7, "North-West": 12, "South": 9, "East": 5, "West": 7}
CHURNED = {"Meridian Retail Group": date(2026, 7, 8), "Kalinga Mart": date(2026, 7, 19)}

ACCOUNT_NAMES = [
    "Meridian Retail Group", "Kalinga Mart", "Aster Distributors", "Bluepeak Traders",
    "Cascade Retail", "Deccan Supplies", "Everline Stores", "Fortuna Wholesale",
    "Girnar Trading Co", "Horizon Mart", "Indus Retail", "Juniper Stores",
    "Kaveri Traders", "Lotus Wholesale", "Mantra Retail", "Nimbus Distributors",
    "Orchid Mart", "Pinnacle Traders", "Quantum Retail", "Ridgeline Stores",
    "Sagar Wholesale", "Tulip Mart", "Umber Trading", "Vertex Retail",
    "Willow Stores", "Xenia Traders", "Yamuna Mart", "Zephyr Retail",
    "Anvil Supplies", "Beacon Mart", "Corbett Traders", "Dhruv Retail",
    "Ember Stores", "Falcon Wholesale", "Gulmohar Mart", "Havelock Retail",
    "Iris Trading", "Jubilee Stores", "Koyna Mart", "Ladakh Traders",
]


def daterange(a, b):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def in_july_impact(d):
    """Demand-side plant window: churn + reduced ordering from July 1 onward."""
    return d >= date(2026, 7, 1)


def build_accounts():
    accts, i = [], 0
    for region, n in ENT_ACCOUNTS_PER_REGION.items():
        for _ in range(n):
            accts.append({"account_id": f"ENT-{i+1:03d}", "account_name": ACCOUNT_NAMES[i], "region": region})
            i += 1
    return accts


def gen_sales_orders():
    accounts = build_accounts()
    # Force the two churned accounts into North-West.
    for a in accounts:
        if a["account_name"] in CHURNED:
            a["region"] = "North-West"
    rows = []
    oid = 100000
    for d in daterange(START, END):
        for region, share in REGIONS.items():
            plant = region == "North-West" and in_july_impact(d)
            # --- consumer orders ---
            n_cons = rng.poisson(190 * share * (0.90 if plant else 1.0))
            # --- SMB orders ---
            n_smb = rng.poisson(22 * share * (0.90 if plant else 1.0))
            for seg, n, mean_v, sd in (("consumer", n_cons, 2400, 900), ("smb", n_smb, 18000, 5200)):
                if n <= 0:
                    continue
                vals = np.maximum(rng.normal(mean_v, sd, n), 300)
                cats = list(CATEGORIES)
                p = list(CATEGORIES.values())
                if d >= HOME_DECOR_LAUNCH:
                    cats = cats + ["home-decor"]
                    ramp = min((d - HOME_DECOR_LAUNCH).days / 30, 1.0)
                    hd = 0.04 + 0.06 * ramp  # ramping share with volatility
                    p = [w * (1 - hd) for w in p] + [hd]
                cat_pick = rng.choice(cats, size=n, p=np.array(p) / np.sum(p))
                for v, c in zip(vals, cat_pick):
                    oid += 1
                    rows.append((f"ORD-{oid}", d.isoformat(), region, seg, c, "", round(float(v), 2)))
        # --- enterprise orders (per account) ---
        for a in accounts:
            churn_dt = CHURNED.get(a["account_name"])
            if churn_dt and in_july_impact(d):
                continue  # stopped ordering from July 1 (churn logged in CRM later)
            lam = 5.5 / 30
            if a["region"] == "North-West" and in_july_impact(d):
                lam *= 0.70  # remaining NW enterprise accounts order less
            n = rng.poisson(lam)
            for _ in range(n):
                oid += 1
                v = max(rng.normal(85000, 22000), 20000)
                c = rng.choice(list(CATEGORIES), p=list(CATEGORIES.values()))
                rows.append((f"ORD-{oid}", d.isoformat(), a["region"], "enterprise", c,
                             a["account_id"] + "|" + a["account_name"], round(float(v), 2)))
    df = pd.DataFrame(rows, columns=["order_id", "order_date", "region", "segment", "category", "account", "order_value"])
    df.to_csv(os.path.join(HERE, "sales_orders.csv"), index=False)
    return df


def gen_ops(df_orders):
    daily = df_orders.groupby(["order_date", "region"]).size().reset_index(name="orders")
    rows = []
    for _, r in daily.iterrows():
        d = date.fromisoformat(r["order_date"])
        region = r["region"]
        shipments = int(round(r["orders"] * 0.98))
        degraded = region == "North-West" and d >= date(2026, 6, 25)
        p_breach = 0.20 if degraded else 0.08
        avg_days = rng.normal(3.5 if degraded else 2.6, 0.15)
        breaches = int(rng.binomial(shipments, p_breach)) if shipments else 0
        rows.append((r["order_date"], region, shipments, round(float(avg_days), 2), breaches))
    pd.DataFrame(rows, columns=["ship_date", "region", "shipments", "avg_delivery_days", "sla_breaches"]) \
        .to_csv(os.path.join(HERE, "ops_fulfilment.csv"), index=False)


def gen_crm(df_orders):
    rows = []
    eid = 5000
    daily = df_orders.groupby(["order_date", "region"]).size().reset_index(name="orders")
    for _, r in daily.iterrows():
        d = date.fromisoformat(r["order_date"])
        region = r["region"]
        rate = 0.012 * (2.5 if (region == "North-West" and d >= date(2026, 7, 1)) else 1.0)
        n = rng.poisson(r["orders"] * rate)
        for _ in range(n):
            eid += 1
            reason = rng.choice(["late delivery", "damaged item", "billing issue", "wrong item"],
                                p=[0.65, 0.15, 0.1, 0.1] if (region == "North-West" and d >= date(2026, 6, 25))
                                else [0.3, 0.3, 0.2, 0.2])
            rows.append((f"EVT-{eid}", r["order_date"], region, "complaint", "", "", reason))
    for name, dt in CHURNED.items():
        eid += 1
        rows.append((f"EVT-{eid}", dt.isoformat(), "North-West", "churn", name, "",
                     "Account closed. Cited repeated SLA misses and competitor express-delivery offer."))
    # monthly NPS per region
    m = pd.period_range("2025-08", "2026-08", freq="M")
    for p in m:
        for region in REGIONS:
            v = rng.normal(42, 2.5)
            if region == "North-West" and str(p) in ("2026-07", "2026-08"):
                v = rng.normal(33, 1.5)
            eid += 1
            rows.append((f"EVT-{eid}", (p.to_timestamp() + pd.offsets.MonthEnd(0)).date().isoformat(),
                         region, "nps", "", round(float(v), 1), "monthly NPS survey"))
    pd.DataFrame(rows, columns=["event_id", "event_date", "region", "event_type", "account_name", "value", "note"]) \
        .to_csv(os.path.join(HERE, "crm_events.csv"), index=False)


def gen_marketing():
    rows = []
    d = START
    while d.weekday() != 0:
        d += timedelta(days=1)
    while d <= END:
        for region, share in REGIONS.items():
            bug = d >= date(2026, 7, 1)  # tagging bug under-counts conversions
            sessions = rng.normal(52000 * share * (1.05 if bug else 1.0), 1600 * share)
            spend = rng.normal(410000 * share * (1.08 if bug else 1.0), 14000 * share)
            conv_rate = rng.normal(0.032, 0.0008) * (0.84 if bug else 1.0)
            rows.append((d.isoformat(), region, round(float(spend), 0), int(sessions),
                         int(sessions * conv_rate)))
        d += timedelta(days=7)
    pd.DataFrame(rows, columns=["week_start", "region", "spend", "sessions", "conversions"]) \
        .to_csv(os.path.join(HERE, "marketing_weekly.csv"), index=False)


UNSTRUCTURED = {
    "ticket_2026-07-08_NW-4411.txt": (
        "SUPPORT TICKET NW-4411 | 2026-07-08 | Region: North-West | Priority: High\n"
        "Customer: consumer order ORD-7741xx.\n"
        "Order promised in 2 days, delivered on day 6. Customer states this is the second late "
        "delivery this month and asked for a refund of delivery charges. Agent notes warehouse "
        "dispatch was delayed at WH-07."
    ),
    "ticket_2026-07-15_NW-4467.txt": (
        "SUPPORT TICKET NW-4467 | 2026-07-15 | Region: North-West | Priority: High\n"
        "Repeat complaint from SMB customer. Delivery 4 days late. Customer explicitly said: "
        "'SwiftKart now does 2-day express for business orders, why should we wait a week?' "
        "Flagging churn risk."
    ),
    "transcript_2026-07-19_meridian_exit_call.txt": (
        "EXIT CALL TRANSCRIPT | 2026-07-19 | Account: Meridian Retail Group (enterprise, North-West)\n"
        "AM: We noticed you paused orders this month.\n"
        "Client: Three of our last five deliveries missed SLA in June. We escalated twice. "
        "SwiftKart launched a 2-day express program for enterprise on July 1 and offered us "
        "onboarding credits. We have moved our replenishment volume to them.\n"
        "AM: Is there anything that would bring the volume back?\n"
        "Client: A reliable 3-day SLA on the North-West lanes, in writing."
    ),
    "ticket_2026-07-22_NW-4502.txt": (
        "SUPPORT TICKET NW-4502 | 2026-07-22 | Region: North-West | Priority: Medium\n"
        "Order stuck in 'packed' state for 3 days. Ops confirms backlog at WH-07 due to "
        "conveyor outage and peak-season staffing shortfall."
    ),
    "ops_note_2026-06-28_warehouse.txt": (
        "INTERNAL OPS NOTE | 2026-06-28 | Author: NW Ops Lead\n"
        "WH-07 main conveyor failed on June 25; running on manual sortation at ~60% throughput. "
        "Spare part ETA 3 weeks. Peak staffing plan short 14 pickers. Expect SLA breaches on "
        "North-West lanes until resolved. Requested approval for temporary 3PL overflow capacity."
    ),
    "postmortem_2025-11_delayed_dispatch.txt": (
        "INCIDENT POSTMORTEM | 2025-11 | East region dispatch delays\n"
        "Symptom: SLA breaches rose from 8% to 15% over three weeks.\n"
        "Root cause: sorter capacity during festive peak.\n"
        "Action that worked: contracted temporary 3PL overflow capacity for 6 weeks and "
        "re-routed 30% of volume; SLA recovered to baseline in 12 days. Cost: ~9L. "
        "Recommendation: pre-approve 3PL overflow playbook for any hub exceeding 12% breach rate."
    ),
    "crm_note_2026-07-10_kalinga.txt": (
        "CRM NOTE | 2026-07-10 | Account: Kalinga Mart (enterprise, North-West)\n"
        "QBR went poorly. Customer cited June delivery misses on 4 POs and said procurement is "
        "evaluating SwiftKart's new express program. Renewal at risk."
    ),
    "slack_2026-07-03_ops_channel.txt": (
        "SLACK THREAD #ops-northwest | 2026-07-03\n"
        "@ravi: backlog at WH-07 now 1,900 orders, oldest 5 days.\n"
        "@priya: manual sortation holding at 60%. escalated 3PL request again.\n"
        "@ravi: CS says complaint volume is climbing, mostly late delivery."
    ),
    "redherring_2026-07-05_office_move.txt": (
        "FACILITIES MEMO | 2026-07-05\n"
        "The Gurugram office will move to Tower B in September. Parking allocations will be "
        "reassigned. No impact to customer operations is expected."
    ),
    "redherring_2026-06-20_brand_refresh.txt": (
        "MARKETING MEMO | 2026-06-20\n"
        "Brand refresh phase 2: updated logo colorway and typography ship across the storefront "
        "at end of June. Purely visual change; no checkout or tracking changes are part of this scope."
    ),
}

MARKET_EVENTS = [
    {"date": "2026-07-01", "headline": "SwiftKart launches 2-day Express Delivery for business customers across North and North-West India",
     "tags": ["competitor", "delivery", "express", "enterprise", "sla"], "regions": ["North-West", "North"],
     "source": "NewsWire (simulated)"},
    {"date": "2026-07-18", "headline": "Monsoon disruption slows road freight along the Eastern corridor",
     "tags": ["logistics", "weather"], "regions": ["East"], "source": "NewsWire (simulated)"},
    {"date": "2026-06-10", "headline": "RBI holds policy rates; consumer sentiment index flat",
     "tags": ["macro"], "regions": [], "source": "NewsWire (simulated)"},
]


def main():
    os.makedirs(os.path.join(HERE, "unstructured"), exist_ok=True)
    os.makedirs(os.path.join(HERE, "state"), exist_ok=True)
    print("generating sales_orders...")
    df = gen_sales_orders()
    print(f"  {len(df):,} orders")
    print("generating ops_fulfilment...")
    gen_ops(df)
    print("generating crm_events...")
    gen_crm(df)
    print("generating marketing_weekly...")
    gen_marketing()
    for fname, text in UNSTRUCTURED.items():
        with open(os.path.join(HERE, "unstructured", fname), "w", encoding="utf-8") as f:
            f.write(text)
    with open(os.path.join(HERE, "market_events.json"), "w", encoding="utf-8") as f:
        json.dump(MARKET_EVENTS, f, indent=2)
    # reset the decision ledger to its seed (powers the "Recall" step)
    import sys
    sys.path.insert(0, os.path.dirname(HERE))
    import feedback
    feedback.reset_ledger()
    print("done. files written to data/")


if __name__ == "__main__":
    main()
