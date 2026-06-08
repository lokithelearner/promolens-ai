"""
PromoLens AI — Reasoning Engine (deterministic tools)
=====================================================
These are the auditable computations the ADK agents call as tools. The LLM
decides WHEN to call them and narrates the RESULT; the numbers come from here.

Pure pandas, no cloud dependency -> runs locally for proof, and the identical
logic is wrapped as BigQuery-backed tools in the deployed agents.
"""
import os, json
import pandas as pd
import numpy as np

DATA = os.path.join(os.path.dirname(__file__), "..", "data", "csv")

TABLES = ["industries","products","channel_partners","schemes_master","primary_sales",
          "secondary_sales","stock_position","scheme_application","scheme_claims",
          "baseline_sales","targets","master_sync_log"]

def load():
    """Load all tables. Backend = BigQuery if PROMOLENS_BACKEND=bigquery, else local CSV.
    Loading from BigQuery lets the deployed Cloud Run service reuse this EXACT engine,
    so cloud behaviour matches the locally-proven results."""
    backend = os.environ.get("PROMOLENS_BACKEND", "csv").lower()
    if backend == "bigquery":
        from google.cloud import bigquery
        project = os.environ["PROMOLENS_PROJECT"]
        dataset = os.environ.get("PROMOLENS_BQ_DATASET", "promolens_db")
        client = bigquery.Client(project=project)
        t = {}
        for name in TABLES:
            t[name] = client.query(f"SELECT * FROM `{project}.{dataset}.{name}`").to_dataframe()
        return t
    t = {}
    for f in os.listdir(DATA):
        if f.endswith(".csv"):
            t[f[:-4]] = pd.read_csv(os.path.join(DATA, f))
    return t

T = load()

# ---------------------------------------------------------------- helpers
def _promo_primary():
    p = T["primary_sales"].copy()
    p["month"] = pd.to_datetime(p["order_date"]).dt.to_period("M").astype(str)
    return p

# ---------------------------------------------------------------- 1. ROI / uplift
def scheme_roi(scheme_id):
    """Incremental uplift vs baseline and ROI for a scheme."""
    sc = T["schemes_master"].set_index("scheme_id").loc[scheme_id]
    skus = json.loads(sc["sku_scope"]); region = sc["region_scope"]
    p = _promo_primary().merge(T["channel_partners"][["partner_id","state"]], on="partner_id")
    sub = p[p.sku_code.isin(skus)]
    if region != "ALL":
        sub = sub[sub.state == region]
    promo_months = sorted(sub["month"].unique())[-6:]
    actual = sub[sub.month.isin(promo_months)]
    actual_val = actual["value"].sum()
    # baseline value over the same months/skus/region
    bl = T["baseline_sales"]
    bl = bl[bl.sku_code.isin(skus)]
    if region != "ALL":
        bl = bl[bl.region == region]
    base_val = bl[bl.month.isin(promo_months)]["baseline_value"].sum()
    incremental = actual_val - base_val
    # outflow = sum of computed payouts applied for this scheme
    ap = T["scheme_application"]
    outflow = ap[(ap.scheme_id == scheme_id) & (ap.applied_flag == True)]["computed_payout"].sum()
    roi = (incremental - outflow) / outflow if outflow else float("nan")
    return dict(scheme_id=scheme_id, name=sc["name"], region=region,
                actual_value=round(actual_val), baseline_value=round(base_val),
                incremental_value=round(incremental), scheme_outflow=round(outflow),
                roi=round(roi, 2), verdict=("WINNER" if roi and roi > 1 else
                ("DUD — paid for sales that would have happened anyway" if roi is not None and roi < 0.2 else "moderate")))

def rank_schemes_by_roi(industry="BLD"):
    out = []
    for sid in T["schemes_master"].query("industry_id==@industry and status=='active'")["scheme_id"]:
        try:
            out.append(scheme_roi(sid))
        except Exception:
            pass
    return sorted([o for o in out if not np.isnan(o["roi"])], key=lambda x: -x["roi"])

# ---------------------------------------------------------------- 2. applicability
def why_not_applied(scheme_id=None, only_skips=True):
    """Explain scheme applications that were skipped, with the reason."""
    ap = T["scheme_application"]
    if scheme_id:
        ap = ap[ap.scheme_id == scheme_id]
    if only_skips:
        ap = ap[ap.applied_flag == False]
    g = ap.groupby(["scheme_id", "skip_reason"]).size().reset_index(name="invoices_skipped")
    return g.to_dict("records")

def scheme_state_view():
    s = T["schemes_master"]
    return s.groupby("status").agg(schemes=("scheme_id","count"),
            names=("name", lambda x: ", ".join(list(x)[:3]))).reset_index().to_dict("records")

# ---------------------------------------------------------------- 3. primary vs secondary leak
def inventory_loading_leaks(min_gap=0.4, min_sellin=300):
    """Flag partner x SKU combinations with high sell-in but flat sell-out
    (the inventory-loading signature). Grain is partner x SKU, not pooled,
    so a loaded SKU isn't masked by the partner's healthy SKUs."""
    p = _promo_primary()
    pm = sorted(p["month"].unique())[-6:]
    prim = p[p.month.isin(pm)].groupby(["partner_id","sku_code"]).agg(sell_in=("qty","sum")).reset_index()
    s = T["secondary_sales"].copy()
    s["month"] = pd.to_datetime(s["sale_date"]).dt.to_period("M").astype(str)
    sec = (s[s.month.isin(pm)].groupby(["from_partner_id","sku_code"]).agg(sell_out=("qty","sum"))
           .reset_index().rename(columns={"from_partner_id":"partner_id"}))
    st = T["stock_position"]
    st = st[st.month.isin(pm)].groupby(["partner_id","sku_code"]).agg(closing=("closing_stock","sum")).reset_index()
    m = (prim.merge(sec, on=["partner_id","sku_code"], how="left")
             .merge(st, on=["partner_id","sku_code"], how="left").fillna(0))
    m["sellthrough"] = m["sell_out"] / m["sell_in"].replace(0, np.nan)
    flagged = m[(m["sellthrough"] < (1 - min_gap)) & (m["sell_in"] >= min_sellin)].copy()
    flagged = flagged.merge(T["channel_partners"][["partner_id","name","state","type"]], on="partner_id", how="left")
    flagged["at_risk_signal"] = ("sell-out only " + (flagged["sellthrough"]*100).round().astype(int).astype(str)
                                 + "% of sell-in; closing stock " + flagged["closing"].round().astype(int).astype(str))
    return flagged.sort_values("sellthrough")[["partner_id","name","state","sku_code","sell_in","sell_out","closing","sellthrough","at_risk_signal"]].to_dict("records")

# ---------------------------------------------------------------- 4. claim recon / over-claim
def overclaims():
    """Compare claimed amount to earned entitlement; flag gaps."""
    ap = T["scheme_application"]
    ap = ap[ap.applied_flag == True].merge(
        T["primary_sales"][["order_id","partner_id"]], left_on="invoice_id", right_on="order_id")
    earned = ap.groupby(["partner_id","scheme_id"]).agg(earned=("computed_payout","sum")).reset_index()
    cl = T["scheme_claims"].merge(earned, on=["partner_id","scheme_id"], how="left").fillna({"earned":0})
    cl["gap"] = cl["claimed_amount"] - cl["earned"]
    flagged = cl[cl["gap"] > 1].copy()
    flagged = flagged.merge(T["channel_partners"][["partner_id","name"]], on="partner_id", how="left")
    return dict(total_at_risk=round(flagged["gap"].sum()),
                count=len(flagged),
                rows=flagged.sort_values("gap", ascending=False)
                    [["claim_id","partner_id","name","scheme_id","claimed_amount","earned","gap"]]
                    .head(15).to_dict("records"))

# ---------------------------------------------------------------- 5. stacked outflow
def stacked_effective_discount(skus=("BLD-PUTTY-W","BLD-PUTTY-S")):
    """For invoices where multiple schemes stack, compute the true effective discount %."""
    ap = T["scheme_application"]
    ap = ap[ap.applied_flag == True].merge(
        T["primary_sales"][["order_id","partner_id","sku_code","value"]],
        left_on="invoice_id", right_on="order_id")
    ap = ap[ap.sku_code.isin(list(skus))]
    g = ap.groupby("invoice_id").agg(value=("value","first"),
            total_payout=("computed_payout","sum"),
            n_schemes=("scheme_id","nunique")).reset_index()
    g["effective_pct"] = (g["total_payout"]/g["value"]*100).round(2)
    stacked = g[g["n_schemes"] >= 2]
    return dict(skus=list(skus),
                invoices_with_stacking=len(stacked),
                avg_schemes_per_invoice=round(g["n_schemes"].mean(),2),
                avg_effective_discount_pct=round(stacked["effective_pct"].mean(),2),
                max_effective_discount_pct=round(stacked["effective_pct"].max(),2))

# ---------------------------------------------------------------- 6. slab-accrual engine
def slab_accrual(sale_qty, slabs, slab_type="running"):
    """Compute earned free/payout qty for the 4 standard slab types.
    slabs: list of dicts with 'min_qty' and 'free_per_slab' (or payout_pct)."""
    slabs = sorted(slabs, key=lambda s: s["min_qty"])
    applicable = [s for s in slabs if sale_qty >= s["min_qty"]]
    if not applicable:
        return 0.0
    top = applicable[-1]
    per = top.get("free_per_slab", top.get("payout_pct", 0))
    base = top["min_qty"]
    if slab_type == "fixed":
        return float(per)
    if slab_type == "step":
        return float(per * (sale_qty // base))
    if slab_type == "linear":
        return float(per * (sale_qty / base))
    # running: successive passes through each slab band
    total, remaining, prev = 0.0, sale_qty, 0
    for s in slabs:
        if sale_qty >= s["min_qty"]:
            band = (slabs[slabs.index(s)+1]["min_qty"] if slabs.index(s)+1 < len(slabs) and
                    sale_qty >= slabs[slabs.index(s)+1]["min_qty"] else sale_qty) - s["min_qty"]
            total += s.get("free_per_slab", s.get("payout_pct",0)) * (band / max(s["min_qty"],1))
    return round(total, 2)

# ---------------------------------------------------------------- 7. data-trust
def data_trust_summary():
    s = T["master_sync_log"]
    fails = s[s.status == "fail"]
    by_reason = fails.groupby("error_reason").size().sort_values(ascending=False)
    return dict(total=len(s), failed=len(fails),
                fail_rate_pct=round(len(fails)/len(s)*100,1),
                top_reasons=[{"reason":r,"count":int(c)} for r,c in by_reason.head(6).items()],
                affected_master_entities=int(fails[fails.entity_type.str.contains("master")].shape[0]))

# ---------------------------------------------------------------- 8. cannibalisation
def cannibalisation(push_sku, victim_sku, region="ALL"):
    p = _promo_primary().merge(T["channel_partners"][["partner_id","state"]], on="partner_id")
    pm = sorted(p["month"].unique())
    promo, pre = pm[-6:], pm[:-6]
    def avg(sku, months):
        d = p[(p.sku_code==sku) & (p.month.isin(months))]
        if region!="ALL": d = d[d.state==region]
        return d.groupby("month")["qty"].sum().mean()
    return dict(push_sku=push_sku, victim_sku=victim_sku,
                push_change_pct=round((avg(push_sku,promo)/avg(push_sku,pre)-1)*100,1),
                victim_change_pct=round((avg(victim_sku,promo)/avg(victim_sku,pre)-1)*100,1))

# ---------------------------------------------------------------- IN-BUILD: what-if
def whatif_simulator(region, skus, slab_pct, expected_growth_pct):
    """Project payout & ROI for a proposed scheme before launch."""
    bl = T["baseline_sales"]
    bl = bl[bl.sku_code.isin(skus)]
    if region!="ALL": bl = bl[bl.region==region]
    base = bl.groupby("month")["baseline_value"].sum().tail(6).sum()
    projected = base * (1 + expected_growth_pct/100)
    incremental = projected - base
    outflow = projected * slab_pct/100
    roi = (incremental - outflow)/outflow if outflow else float("nan")
    return dict(region=region, projected_value=round(projected), incremental_value=round(incremental),
                projected_outflow=round(outflow), projected_roi=round(roi,2),
                guidance=("Attractive" if roi>1 else "Marginal — tighten slab or target"))
