"""
PromoLens AI — Synthetic scheme-notification document generator.
Turns each row of schemes_master into a natural-language scheme *circular* (the
kind distributors actually receive), with labelled clauses. This is the RAG
corpus for Vertex AI Search. Fully synthetic; fictional companies.

It also plants ONE amended/superseding circular (a payout revision) so the RAG
can demonstrate citing the CURRENT clause and flagging a conflicting older one.
"""
import os, json, pandas as pd

HERE = os.path.dirname(__file__)
CSV = os.path.join(HERE, "csv")
OUT = os.path.join(HERE, "scheme_docs")
os.makedirs(OUT, exist_ok=True)

COMPANY = {"BLD": "DuraBuild", "PHA": "NovaCure", "REN": "SunPeak"}

def slab_table(sc):
    try:
        slabs = json.loads(sc["slab_json"]) if isinstance(sc["slab_json"], str) else (sc["slab_json"] or [])
    except Exception:
        slabs = []
    if not slabs:
        return "As per annexure."
    rows = []
    for s in slabs:
        if "growth_pct" in s:
            rows.append(f"- Growth over baseline >= {s['growth_pct']}%  ->  payout {s.get('payout_pct','?')}% of eligible turnover")
        elif "min_qty" in s:
            rows.append(f"- Purchase >= {s['min_qty']} {sc.get('uom','units')}  ->  {s.get('free_per_slab', s.get('payout_pct','?'))} free/payout")
        else:
            rows.append(f"- {json.dumps(s)}")
    return "\n".join(rows)

def circular(sc, revision=None, override_slab=None):
    co = COMPANY.get(sc["industry_id"], "the Company")
    try:
        skus = ", ".join(json.loads(sc["sku_scope"])) if isinstance(sc["sku_scope"], str) else str(sc["sku_scope"])
    except Exception:
        skus = str(sc.get("sku_scope"))
    title = sc["name"] + (f" — Revised (Amendment {revision})" if revision else "")
    slab = override_slab or slab_table(sc)
    doc = f"""# Scheme Circular: {title}

**Scheme ID:** {sc['scheme_id']}{('-R'+str(revision)) if revision else ''}
**Issued by:** {co} Trade Marketing
**Status:** {'SUPERSEDES earlier circular for '+sc['scheme_id'] if revision else str(sc.get('status',''))}
**Effective period:** {sc.get('start_date','')} to {sc.get('end_date','')}

## 1. Eligibility
This scheme is open to channel partners of tier {sc.get('channel_tier','ALL')} operating in {sc.get('region_scope','ALL')}. Partners must have an active trading account and no unresolved claim disputes.

## 2. Scope of products
Applicable SKUs: {skus}.

## 3. Incentive structure ({sc.get('mode','')} mode, {sc.get('slab_type','')} slab, {sc.get('incentive_type','')})
{slab}

## 4. Baseline & measurement
Uplift is measured against the {sc.get('baseline_ref','trailing 12-month')} baseline for the eligible SKUs and region. Only secondary-verified sell-out counts towards slab achievement.

## 5. Claim process
Claims must be raised within 30 days of period close with supporting sell-out evidence. Payout is by {sc.get('incentive_type','cash')}. Over-claims beyond earned entitlement will be recovered from the next settlement.

## 6. Budget & caps
Total scheme budget: Rs {int(sc.get('budget',0)):,}. The company may cap total per-invoice discount where multiple schemes apply.
"""
    return doc

def main():
    sm = pd.read_csv(os.path.join(CSV, "schemes_master.csv"))
    n = 0
    for _, sc in sm.iterrows():
        with open(os.path.join(OUT, f"{sc['scheme_id']}.md"), "w") as f:
            f.write(circular(sc)); n += 1
    # planted conflict: amend the known winner scheme's payout (current > old)
    tgt = sm[sm.scheme_id == "SCHBLD001"]
    if len(tgt):
        sc = tgt.iloc[0]
        amended = ("- Growth over baseline >= 5%  ->  payout 1.25% of eligible turnover\n"
                   "- Growth over baseline >= 10% ->  payout 2.00% of eligible turnover\n"
                   "- Growth over baseline >= 18% ->  payout 3.00% of eligible turnover  "
                   "(revised upward from 2.5% w.e.f. amendment)")
        with open(os.path.join(OUT, f"{sc['scheme_id']}-R2.md"), "w") as f:
            f.write(circular(sc, revision=2, override_slab=amended)); n += 1
    print(f"wrote {n} scheme circulars to {OUT}")

if __name__ == "__main__":
    main()
