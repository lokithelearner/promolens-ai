"""
PromoLens AI — Reasoning Engine (deterministic tools)
=====================================================
These are the auditable computations the ADK agents call as tools. The LLM
decides WHEN to call them and narrates the RESULT; the numbers come from here.

Pure pandas, no cloud dependency -> runs locally for proof, and the identical
logic is wrapped as BigQuery-backed tools in the deployed agents.

Every analytic function accepts an optional `win` (timeline window):
  None / "ttm"      -> trailing 12 months (industry-standard rolling benchmark)
  "FY2025-26" etc.  -> a specific financial year (India FY, Apr-Mar)
"""
import os, json
import pandas as pd
import numpy as np

DATA = os.path.join(os.path.dirname(__file__), "..", "data", "csv")

TABLES = ["industries","products","channel_partners","schemes_master","primary_sales",
          "secondary_sales","stock_position","scheme_application","scheme_claims",
          "baseline_sales","targets","master_sync_log"]

def load():
    """Load all tables. Backend = BigQuery if PROMOLENS_BACKEND=bigquery, else local CSV."""
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

# ---------------------------------------------------------------- column normaliser
# Some BigQuery loads land headerless (columns -> string_field_0..N). Re-map known tables.
_SCHEMAS = {
    "master_sync_log": ["entity_type","entity_id","source","status","error_reason","ts"],
}
def _norm(name):
    df = T[name].copy()
    if name in _SCHEMAS and "string_field_0" in df.columns:
        order = _SCHEMAS[name]
        df = df.rename(columns={f"string_field_{i}": order[i] for i in range(min(len(order), df.shape[1]))})
    return df

# ---------------------------------------------------------------- timeline window
def _all_months():
    p = _promo_primary()
    return sorted(p["month"].unique())

_DEFAULT_WIN = None
def set_default_window(w):
    """Set the window used when a tool is called without an explicit `win`
    (lets the Gemini agent tools honour the user's selected timeline)."""
    global _DEFAULT_WIN
    _DEFAULT_WIN = w if w and str(w).lower() != "ttm" else None

def resolve_window(win=None):
    """Map a selection to (set_of_month_strings, label, kind).
    win None/'ttm' -> trailing 12 months; 'FY2025-26' -> Apr2025..Mar2026."""
    win = win or _DEFAULT_WIN
    months = _all_months()
    if win and str(win).upper().startswith("FY"):
        s = str(win)
        try:
            yr = int(s[2:6])
            start, end = f"{yr}-04", f"{yr+1}-03"
            wm = [m for m in months if start <= m <= end]
            if wm:
                return set(wm), s, "fy"
        except Exception:
            pass
    return set(months[-12:]), "Last 12 months", "ttm"

def list_windows():
    """Available timeline options for the UI (default first).
    FYs are derived from real scheme periods so only fiscal years with promotion
    activity are offered (last 3)."""
    fys = set()
    sm = T["schemes_master"]
    for _, r in sm.iterrows():
        if str(r.get("status", "")) == "draft":   # skip not-yet-started FYs
            continue
        try:
            d = pd.to_datetime(r["start_date"])
            fy = d.year if d.month >= 4 else d.year - 1
            fys.add(fy)
        except Exception:
            pass
    out = [{"key": "ttm", "label": "Last 12 months (benchmark)", "default": True}]
    for k in [f"FY{y}-{str(y+1)[2:]}" for y in sorted(fys, reverse=True)][:3]:
        out.append({"key": k, "label": k, "default": False})
    return out

def _scheme_months(scid):
    sc = T["schemes_master"].set_index("scheme_id").loc[scid]
    try:
        rng = pd.period_range(pd.to_datetime(sc["start_date"]).to_period("M"),
                              pd.to_datetime(sc["end_date"]).to_period("M"), freq="M")
        return set(str(p) for p in rng)
    except Exception:
        return set()

# ---------------------------------------------------------------- helpers
def _promo_primary():
    p = T["primary_sales"].copy()
    p["month"] = pd.to_datetime(p["order_date"]).dt.to_period("M").astype(str)
    return p

# ---------------------------------------------------------------- 1. ROI / uplift
def scheme_roi(scheme_id, win=None):
    """Incremental uplift vs rolling baseline and ROI for a scheme, within the window."""
    wmonths, _, _ = resolve_window(win)
    sc = T["schemes_master"].set_index("scheme_id").loc[scheme_id]
    skus = json.loads(sc["sku_scope"]); region = sc["region_scope"]
    promo_months = _scheme_months(scheme_id) & wmonths
    if not promo_months:
        return None  # scheme not active in this window
    p = _promo_primary().merge(T["channel_partners"][["partner_id","state"]], on="partner_id")
    sub = p[p.sku_code.isin(skus)]
    if region != "ALL":
        sub = sub[sub.state == region]
    actual = sub[sub.month.isin(promo_months)]
    actual_val = actual["value"].sum()
    bl = T["baseline_sales"]
    bl = bl[bl.sku_code.isin(skus)]
    if region != "ALL":
        bl = bl[bl.region == region]
    base_val = bl[bl.month.isin(promo_months)]["baseline_value"].sum()
    incremental = actual_val - base_val
    ap = T["scheme_application"].merge(_promo_primary()[["order_id","month"]],
                                       left_on="invoice_id", right_on="order_id")
    outflow = ap[(ap.scheme_id == scheme_id) & (ap.applied_flag == True) &
                 (ap.month.isin(promo_months))]["computed_payout"].sum()
    roi = (incremental - outflow) / outflow if outflow else float("nan")
    return dict(scheme_id=scheme_id, name=sc["name"], region=region,
                actual_value=round(actual_val), baseline_value=round(base_val),
                incremental_value=round(incremental), scheme_outflow=round(outflow),
                roi=round(roi, 2), verdict=("WINNER" if roi and roi > 1 else
                ("DUD — paid for sales that would have happened anyway" if roi is not None and roi < 0.2 else "moderate")))

def rank_schemes_by_roi(industry="BLD", win=None):
    wmonths, _, _ = resolve_window(win)
    out = []
    sm = T["schemes_master"]
    for sid in sm[sm.industry_id == industry]["scheme_id"]:
        if not (_scheme_months(sid) & wmonths):
            continue
        try:
            r = scheme_roi(sid, win)
            if r and not np.isnan(r["roi"]):
                out.append(r)
        except Exception:
            pass
    return sorted(out, key=lambda x: -x["roi"])

# ---------------------------------------------------------------- 2. applicability
def why_not_applied(scheme_id=None, only_skips=True, win=None):
    wmonths, _, _ = resolve_window(win)
    ap = T["scheme_application"].merge(_promo_primary()[["order_id","month"]],
                                       left_on="invoice_id", right_on="order_id")
    ap = ap[ap.month.isin(wmonths)]
    if scheme_id:
        ap = ap[ap.scheme_id == scheme_id]
    if only_skips:
        ap = ap[ap.applied_flag == False]
    g = ap.groupby(["scheme_id", "skip_reason"]).size().reset_index(name="invoices_skipped")
    return g.to_dict("records")

def scheme_state_view(win=None):
    wmonths, _, _ = resolve_window(win)
    s = T["schemes_master"]
    s = s[s["scheme_id"].apply(lambda x: bool(_scheme_months(x) & wmonths))] if len(wmonths) else s
    if len(s) == 0:
        s = T["schemes_master"]
    return s.groupby("status").agg(schemes=("scheme_id","count"),
            names=("name", lambda x: ", ".join(list(x)[:3]))).reset_index().to_dict("records")

# ---------------------------------------------------------------- 3. primary vs secondary leak
def inventory_loading_leaks(min_gap=0.4, min_sellin=300, win=None):
    """Flag partner x SKU combos with high sell-in but flat sell-out within the window."""
    wmonths, _, _ = resolve_window(win)
    p = _promo_primary()
    prim = p[p.month.isin(wmonths)].groupby(["partner_id","sku_code"]).agg(sell_in=("qty","sum")).reset_index()
    s = T["secondary_sales"].copy()
    s["month"] = pd.to_datetime(s["sale_date"]).dt.to_period("M").astype(str)
    sec = (s[s.month.isin(wmonths)].groupby(["from_partner_id","sku_code"]).agg(sell_out=("qty","sum"))
           .reset_index().rename(columns={"from_partner_id":"partner_id"}))
    st = T["stock_position"]
    st = st[st.month.isin(wmonths)].groupby(["partner_id","sku_code"]).agg(closing=("closing_stock","sum")).reset_index()
    m = (prim.merge(sec, on=["partner_id","sku_code"], how="left")
             .merge(st, on=["partner_id","sku_code"], how="left").fillna(0))
    m["sellthrough"] = m["sell_out"] / m["sell_in"].replace(0, np.nan)
    flagged = m[(m["sellthrough"] < (1 - min_gap)) & (m["sell_in"] >= min_sellin)].copy()
    flagged = flagged.merge(T["channel_partners"][["partner_id","name","state","type"]], on="partner_id", how="left")
    flagged["at_risk_signal"] = ("sell-out only " + (flagged["sellthrough"]*100).round().astype(int).astype(str)
                                 + "% of sell-in; closing stock " + flagged["closing"].round().astype(int).astype(str))
    return flagged.sort_values("sellthrough")[["partner_id","name","state","sku_code","sell_in","sell_out","closing","sellthrough","at_risk_signal"]].to_dict("records")

# ---------------------------------------------------------------- 4. claim recon / over-claim
def overclaims(win=None):
    """Compare claimed amount to earned entitlement within the window; flag gaps."""
    wmonths, _, _ = resolve_window(win)
    ap = T["scheme_application"]
    ap = ap[ap.applied_flag == True].merge(
        _promo_primary()[["order_id","partner_id","month"]], left_on="invoice_id", right_on="order_id")
    ap = ap[ap.month.isin(wmonths)]
    earned = ap.groupby(["partner_id","scheme_id"]).agg(earned=("computed_payout","sum")).reset_index()
    # only consider schemes that have earnings in this window
    cl = T["scheme_claims"].merge(earned, on=["partner_id","scheme_id"], how="inner")
    cl["gap"] = cl["claimed_amount"] - cl["earned"]
    flagged = cl[cl["gap"] > 1].copy()
    flagged = flagged.merge(T["channel_partners"][["partner_id","name"]], on="partner_id", how="left")
    return dict(total_at_risk=round(flagged["gap"].sum()),
                count=len(flagged),
                rows=flagged.sort_values("gap", ascending=False)
                    [["claim_id","partner_id","name","scheme_id","claimed_amount","earned","gap"]]
                    .head(15).to_dict("records"))

# ---------------------------------------------------------------- 5. stacked outflow
def stacked_effective_discount(skus=("BLD-PUTTY-W","BLD-PUTTY-S"), win=None):
    """For invoices where multiple schemes stack, compute the true effective discount %."""
    wmonths, _, _ = resolve_window(win)
    ap = T["scheme_application"]
    ap = ap[ap.applied_flag == True].merge(
        _promo_primary()[["order_id","partner_id","sku_code","value","month"]],
        left_on="invoice_id", right_on="order_id")
    ap = ap[(ap.sku_code.isin(list(skus))) & (ap.month.isin(wmonths))]
    g = ap.groupby("invoice_id").agg(value=("value","first"),
            total_payout=("computed_payout","sum"),
            n_schemes=("scheme_id","nunique")).reset_index()
    if len(g) == 0:
        return dict(skus=list(skus), invoices_with_stacking=0, avg_schemes_per_invoice=0,
                    avg_effective_discount_pct=0, max_effective_discount_pct=0)
    g["effective_pct"] = (g["total_payout"]/g["value"]*100).round(2)
    stacked = g[g["n_schemes"] >= 2]
    return dict(skus=list(skus),
                invoices_with_stacking=len(stacked),
                avg_schemes_per_invoice=round(g["n_schemes"].mean(),2),
                avg_effective_discount_pct=round(stacked["effective_pct"].mean(),2) if len(stacked) else 0,
                max_effective_discount_pct=round(stacked["effective_pct"].max(),2) if len(stacked) else 0)

# ---------------------------------------------------------------- 6. slab-accrual engine
def slab_accrual(sale_qty, slabs, slab_type="running"):
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
    total = 0.0
    for s in slabs:
        if sale_qty >= s["min_qty"]:
            band = (slabs[slabs.index(s)+1]["min_qty"] if slabs.index(s)+1 < len(slabs) and
                    sale_qty >= slabs[slabs.index(s)+1]["min_qty"] else sale_qty) - s["min_qty"]
            total += s.get("free_per_slab", s.get("payout_pct",0)) * (band / max(s["min_qty"],1))
    return round(total, 2)

# ---------------------------------------------------------------- 7. data-trust
def data_trust_summary(win=None):
    wmonths, _, _ = resolve_window(win)
    s = _norm("master_sync_log")
    if "ts" in s.columns and len(wmonths):
        s = s.copy()
        s["month"] = pd.to_datetime(s["ts"], errors="coerce").dt.to_period("M").astype(str)
        sw = s[s.month.isin(wmonths)]
        if len(sw):
            s = sw
    if "status" not in s.columns or len(s) == 0:
        return dict(total=len(s), failed=0, fail_rate_pct=0.0, top_reasons=[], affected_master_entities=0)
    fails = s[s["status"] == "fail"]
    if "error_reason" in fails.columns and len(fails):
        by_reason = fails["error_reason"].fillna("unspecified").value_counts()
        top = [{"reason": str(r), "count": int(c)} for r, c in by_reason.head(6).items()]
    else:
        top = []
    affected = 0
    if "entity_type" in fails.columns and len(fails):
        affected = int(fails["entity_type"].astype(str).str.contains("master").sum())
    return dict(total=len(s), failed=len(fails),
                fail_rate_pct=round(len(fails)/len(s)*100, 1),
                top_reasons=top, affected_master_entities=affected)

# ---------------------------------------------------------------- 8. cannibalisation
def cannibalisation(push_sku, victim_sku, region="ALL", win=None):
    wmonths, _, _ = resolve_window(win)
    p = _promo_primary().merge(T["channel_partners"][["partner_id","state"]], on="partner_id")
    all_m = sorted(p["month"].unique())
    promo = sorted(wmonths)
    pre = [m for m in all_m if m < promo[0]][-6:] if promo else []
    def avg(sku, months):
        if not months: return float("nan")
        d = p[(p.sku_code==sku) & (p.month.isin(months))]
        if region!="ALL": d = d[d.state==region]
        g = d.groupby("month")["qty"].sum()
        return g.mean() if len(g) else float("nan")
    pp, pv = avg(push_sku,promo), avg(victim_sku,promo)
    rp, rv = avg(push_sku,pre), avg(victim_sku,pre)
    return dict(push_sku=push_sku, victim_sku=victim_sku,
                push_change_pct=round((pp/rp-1)*100,1) if rp and not np.isnan(rp) else None,
                victim_change_pct=round((pv/rv-1)*100,1) if rv and not np.isnan(rv) else None)

# ---------------------------------------------------------------- IN-BUILD: what-if
def whatif_simulator(region, skus, slab_pct, expected_growth_pct, win=None):
    """Project payout & ROI for a proposed scheme before launch (uses recent baseline)."""
    wmonths, _, _ = resolve_window(win)
    bl = T["baseline_sales"]
    bl = bl[bl.sku_code.isin(skus)]
    if region!="ALL": bl = bl[bl.region==region]
    months = sorted(wmonths)
    base = bl[bl.month.isin(months)].groupby("month")["baseline_value"].sum().sum()
    if not base:
        base = bl.groupby("month")["baseline_value"].sum().tail(6).sum()
    projected = base * (1 + expected_growth_pct/100)
    incremental = projected - base
    outflow = projected * slab_pct/100
    roi = (incremental - outflow)/outflow if outflow else float("nan")
    return dict(region=region, projected_value=round(projected), incremental_value=round(incremental),
                projected_outflow=round(outflow), projected_roi=round(roi,2),
                guidance=("Attractive" if roi>1 else "Marginal — tighten slab or target"))

# ================================================================
# ADVANCED (v2) — prescriptive tools ported from the AI Sales Engine POC
# Next-Best-Scheme (constraint-aware NBA), Missed-Opportunity finder,
# and a what-if confidence band. Deterministic; Gemini narrates the result.
# ================================================================
def _partner_type_is_channel(t):
    return str(t).lower() in ("distributor", "dealer", "stockist", "channel_partner")

def _top_slab(sc):
    """Return (ask_growth_pct, payout_pct) from a scheme's slab_json (best slab)."""
    try:
        slabs = json.loads(sc["slab_json"]) if isinstance(sc["slab_json"], str) else (sc["slab_json"] or [])
    except Exception:
        slabs = []
    ask, pay = 10.0, 2.0  # sensible defaults for free-goods / missing slabs
    gvals = [s.get("growth_pct") for s in slabs if isinstance(s, dict) and s.get("growth_pct") is not None]
    pvals = [s.get("payout_pct") for s in slabs if isinstance(s, dict) and s.get("payout_pct") is not None]
    if gvals: ask = float(max(gvals))
    if pvals: pay = float(max(pvals))
    return ask, pay

def _tier_ok(channel_tier, tier):
    ct = str(channel_tier or "")
    if not ct or ct.upper() in ("ALL", "NAN"): return True
    tset = {x.strip().upper() for x in ct.split("/")}
    tt = str(tier or "").strip().upper()
    if tt in ("", "-", "NAN"): return True   # untiered partners are broadly eligible
    return tt in tset

def _region_ok(region_scope, state):
    rs = str(region_scope or "")
    return rs.upper() in ("ALL", "", "NAN") or rs.strip().lower() == str(state or "").strip().lower()

def _eligible_schemes(partner_row, wmonths):
    """Schemes a partner is eligible for and that are active in the window."""
    sm = T["schemes_master"]
    out = []
    for _, sc in sm.iterrows():
        if str(sc.get("status", "")) == "draft":
            continue
        if not (_scheme_months(sc["scheme_id"]) & wmonths):
            continue
        if not _region_ok(sc.get("region_scope"), partner_row.get("state")):
            continue
        if not _tier_ok(sc.get("channel_tier"), partner_row.get("tier")):
            continue
        out.append(sc)
    return out

def _partner_applied_propensity(partner_id):
    """How often this partner's scheme applications actually applied (0.3..0.9)."""
    ap = T["scheme_application"].merge(
        _promo_primary()[["order_id", "partner_id"]], left_on="invoice_id", right_on="order_id")
    mine = ap[ap.partner_id == partner_id]
    if len(mine) == 0:
        return 0.6
    return float(min(0.9, max(0.3, mine["applied_flag"].mean())))

def _leaky_partner_ids(win=None):
    try:
        return {r["partner_id"] for r in inventory_loading_leaks(win=win)}
    except Exception:
        return set()

def _overclaim_partner_ids(win=None):
    try:
        return {r["partner_id"] for r in overclaims(win)["rows"]}
    except Exception:
        return set()

def next_best_scheme(partner_id, win=None, leaky=None, ocids=None):
    """Constraint-aware Next-Best-Scheme for one partner: rank eligible in-window
    schemes by expected incremental value, net of projected payout. Flags partners
    that are loading inventory / over-claiming (act on that first)."""
    wmonths, _, _ = resolve_window(win)
    cp = T["channel_partners"]
    prow = cp[cp.partner_id == partner_id]
    if len(prow) == 0:
        return None
    prow = prow.iloc[0].to_dict()
    leaky = _leaky_partner_ids(win) if leaky is None else leaky
    ocids = _overclaim_partner_ids(win) if ocids is None else ocids
    p = _promo_primary()
    pw = p[(p.partner_id == partner_id) & (p.month.isin(wmonths))]
    prop = _partner_applied_propensity(partner_id)
    recs = []
    for sc in _eligible_schemes(prow, wmonths):
        try:
            skus = json.loads(sc["sku_scope"]) if isinstance(sc["sku_scope"], str) else sc["sku_scope"]
        except Exception:
            skus = []
        base = pw[pw.sku_code.isin(skus)]["value"].sum()
        if base <= 0:
            continue  # no existing base with these SKUs -> handled by missed_opportunities
        ask, pay = _top_slab(sc)
        exp_incr = base * (ask / 100.0) * prop
        proj_payout = base * (1 + ask / 100.0 * prop) * (pay / 100.0)
        roi = (exp_incr - proj_payout) / proj_payout if proj_payout else float("nan")
        recs.append(dict(scheme_id=sc["scheme_id"], scheme=sc["name"], archetype=sc["archetype"],
                         base_value=round(base), ask_growth_pct=ask, payout_pct=pay,
                         expected_incremental=round(exp_incr), projected_payout=round(proj_payout),
                         expected_roi=round(roi, 2)))
    recs.sort(key=lambda x: -x["expected_incremental"])
    constraint = None
    if partner_id in leaky:
        constraint = "inventory_loading"
    elif partner_id in ocids:
        constraint = "over_claim"
    return dict(partner_id=partner_id, name=prow.get("name"), state=prow.get("state"),
                tier=prow.get("tier"), type=prow.get("type"), propensity=round(prop, 2),
                constraint=constraint, recommendations=recs[:3])

def nba_recommendations(industry="BLD", win=None, limit=12):
    """Portfolio Next-Best-Action leaderboard: for each channel partner, the single
    best scheme to push next (expected Rs uplift), constraint-aware with a plain action."""
    wmonths, _, _ = resolve_window(win)
    cp = T["channel_partners"]
    cp = cp[cp.industry_id == industry] if "industry_id" in cp.columns else cp
    leaky = _leaky_partner_ids(win); ocids = _overclaim_partner_ids(win)
    out = []
    for _, prow in cp.iterrows():
        if not _partner_type_is_channel(prow.get("type")):
            continue
        nb = next_best_scheme(prow["partner_id"], win, leaky=leaky, ocids=ocids)
        if not nb or not nb["recommendations"]:
            continue
        top = nb["recommendations"][0]
        if nb["constraint"] == "inventory_loading":
            action = (f"Hold new buy-more offers — {nb['name']} is loading inventory. Fix sell-through "
                      f"first, then run '{top['scheme']}'.")
        elif nb["constraint"] == "over_claim":
            action = (f"Clear the open over-claim with {nb['name']} before enrolling them in '{top['scheme']}'.")
        else:
            action = (f"Push '{top['scheme']}' to {nb['name']} ({nb['state']}, tier {nb['tier']}): "
                      f"~Rs {top['expected_incremental']:,} extra sales at ~{top['expected_roi']}x ROI.")
        out.append(dict(partner_id=nb["partner_id"], name=nb["name"], state=nb["state"], tier=nb["tier"],
                        scheme_id=top["scheme_id"], scheme=top["scheme"],
                        base_value=top["base_value"], ask_growth_pct=top["ask_growth_pct"],
                        payout_pct=top["payout_pct"],
                        expected_incremental=top["expected_incremental"], expected_roi=top["expected_roi"],
                        constraint=nb["constraint"], action=action))
    out.sort(key=lambda x: (0 if x["constraint"] else 1, -x["expected_incremental"]))
    # surface constrained (risky) ones near the top so they're not missed, then biggest upside
    go = [o for o in out if not o["constraint"]]
    risk = [o for o in out if o["constraint"]]
    go.sort(key=lambda x: -x["expected_incremental"])
    return dict(window=win or "ttm", count=len(out),
                recommendations=(risk[:3] + go)[:limit],
                total_upside=round(sum(o["expected_incremental"] for o in go)))

def missed_opportunities(industry="BLD", win=None, limit=12):
    """Find partner x SKU gaps a dashboard can't: partners who under-index on an
    in-scheme SKU vs same-tier peers, where an active scheme already covers it."""
    wmonths, _, _ = resolve_window(win)
    cp = T["channel_partners"]
    cp = cp[cp.industry_id == industry] if "industry_id" in cp.columns else cp
    prods = T["products"].set_index("sku_code")
    p = _promo_primary()
    pw = p[p.month.isin(wmonths)]
    # partners active in the category (bought anything in window)
    active_partners = set(pw["partner_id"].unique())
    # eligible in-window schemes with their SKU scope
    sm = T["schemes_master"]
    scheme_for_sku = {}   # sku -> (scheme_id, name)
    for _, sc in sm.iterrows():
        if str(sc.get("status", "")) == "draft":
            continue
        if not (_scheme_months(sc["scheme_id"]) & wmonths):
            continue
        try:
            skus = json.loads(sc["sku_scope"]) if isinstance(sc["sku_scope"], str) else sc["sku_scope"]
        except Exception:
            skus = []
        for s in skus:
            scheme_for_sku.setdefault(s, (sc["scheme_id"], sc["name"], sc.get("region_scope"), sc.get("channel_tier")))
    # offtake qty per (partner, sku) in window
    ot = pw.groupby(["partner_id", "sku_code"]).agg(qty=("qty", "sum")).reset_index()
    opps = []
    cpi = cp.set_index("partner_id")
    for sku, (sid, sname, rscope, ctier) in scheme_for_sku.items():
        sku_rows = ot[ot.sku_code == sku]
        # peer set = eligible partners of the industry with positive offtake for this SKU
        peers = sku_rows[sku_rows.qty > 0]["qty"]
        if len(peers) < 3:
            continue
        peer_median = float(peers.median())
        if peer_median <= 0:
            continue
        asp = float(prods.loc[sku]["asp"]) if sku in prods.index else 0.0
        for pid in active_partners:
            if pid not in cpi.index:
                continue
            prow = cpi.loc[pid]
            if isinstance(prow, pd.DataFrame):
                prow = prow.iloc[0]
            if not _partner_type_is_channel(prow.get("type")):
                continue
            if not (_region_ok(rscope, prow.get("state")) and _tier_ok(ctier, prow.get("tier"))):
                continue
            cur = float(sku_rows[sku_rows.partner_id == pid]["qty"].sum())
            if cur >= 0.5 * peer_median:
                continue  # not under-indexed
            gap_qty = peer_median - cur
            gap_val = gap_qty * asp
            if gap_val < 1000:
                continue
            opps.append(dict(partner_id=pid, name=prow.get("name"), state=prow.get("state"),
                             tier=prow.get("tier"), sku_code=sku, current_qty=round(cur),
                             peer_median_qty=round(peer_median), gap_qty=round(gap_qty),
                             est_uplift_value=round(gap_val), scheme_id=sid, scheme=sname,
                             action=(f"Push {sku} to {prow.get('name')} — they pull {round(cur)} vs peer median "
                                     f"{round(peer_median)}; '{sname}' already covers it. Est +Rs {round(gap_val):,}.")))
    opps.sort(key=lambda x: -x["est_uplift_value"])
    # dedupe by partner (one best opp each) for a cleaner leaderboard
    seen, dedup = set(), []
    for o in opps:
        if o["partner_id"] in seen:
            continue
        seen.add(o["partner_id"]); dedup.append(o)
    return dict(window=win or "ttm", count=len(dedup),
                opportunities=dedup[:limit],
                total_upside=round(sum(o["est_uplift_value"] for o in dedup[:limit])))

def whatif_band(region, skus, slab_pct, expected_growth_pct, win=None):
    """What-if with a confidence band: low / base / high growth scenarios so the
    user sees downside risk, not just a point estimate."""
    base = whatif_simulator(region, skus, slab_pct, expected_growth_pct, win)
    low = whatif_simulator(region, skus, slab_pct, expected_growth_pct * 0.5, win)
    high = whatif_simulator(region, skus, slab_pct, expected_growth_pct * 1.5, win)
    return dict(base=base, low=low, high=high,
                summary=(f"Base case ~Rs {base['projected_roi']} back per Rs 1 "
                         f"(range {low['projected_roi']}-{high['projected_roi']} across "
                         f"conservative-to-optimistic uptake)."))
