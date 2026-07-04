"""
PromoLens AI — Synthetic Trade-Promotion Dataset Generator
==========================================================
Generates a fully fictional, multi-industry trade-promotion dataset with
deliberately planted analytical "needles" so the copilot demo always lands.

NO real or customer data is used. Companies, partners and SKUs are invented.
Deterministic (seeded) -> reproducible.

Tables emitted as CSV into ./csv :
  industries, products, channel_partners, schemes_master,
  primary_sales, secondary_sales, stock_position,
  scheme_application, scheme_claims, baseline_sales, targets, master_sync_log

Planted needles (see PLANTED_NEEDLES dict + data_dictionary.md):
  N1 winner scheme   N2 dud scheme       N3 inventory-loading leak
  N4 over-claim      N5 stacking trap    N6 cannibalisation
  N7 master mismatch / failed syncs      N8 scheme that didn't apply (skip_reason)
"""
import os, json, math, random
import numpy as np
import pandas as pd
from datetime import date, timedelta
from faker import Faker

SEED = 42
np.random.seed(SEED); random.seed(SEED)
fake = Faker("en_IN"); Faker.seed(SEED)

OUT = os.path.join(os.path.dirname(__file__), "csv")
os.makedirs(OUT, exist_ok=True)

# ---- time frame: realized data Apr 2023 - Jun 2026, India FY = Apr-Mar ----
# "Today" sits in Q1 of the running FY2026-27; its H2 promo season (Oct-Mar) is upcoming.
MONTHS = pd.period_range("2023-04", "2026-06", freq="M")          # 39 months of realized sales
TODAY = date(2026, 7, 4)

# Each financial year runs a 6-month promotion season (H2: Oct-Mar).
# Only these three FYs have a COMPLETED promo season with realized data (ROI/leakage).
FYS = [
    dict(key="FY2023-24", promo=pd.period_range("2023-10", "2024-03", freq="M")),
    dict(key="FY2024-25", promo=pd.period_range("2024-10", "2025-03", freq="M")),
    dict(key="FY2025-26", promo=pd.period_range("2025-10", "2026-03", freq="M")),
]
# The running year's promo season is in the future — no realized sales yet.
FY_NEXT_PROMO = pd.period_range("2026-10", "2027-03", freq="M")
# Union of every promo month across FYs (needle uplifts apply in any promo season).
ALL_PROMO = pd.PeriodIndex(sorted(set(m for fy in FYS for m in fy["promo"])))
PROMO_MONTHS = FYS[-1]["promo"]    # latest season (kept for backward-compat references)

PLANTED_NEEDLES = {}

# -----------------------------------------------------------------------------
# 1. INDUSTRIES
# -----------------------------------------------------------------------------
industries = pd.DataFrame([
    {"industry_id":"BLD","name":"Building Materials","company":"DuraBuild","uom":"bag","currency":"INR"},
    {"industry_id":"PHA","name":"Pharma","company":"NovaCure","uom":"strip","currency":"INR"},
    {"industry_id":"REN","name":"Renewables","company":"SunPeak","uom":"panel","currency":"INR"},
])

# -----------------------------------------------------------------------------
# 2. PRODUCTS  (18 SKUs)
# -----------------------------------------------------------------------------
prod_rows = []
bld = [("BLD-OPC53","OPC 53 Grade","DuraBuild Cement","Cement",420,300),
       ("BLD-PPC","PPC Cement","DuraBuild Cement","Cement",390,280),
       ("BLD-PUTTY-W","Wall Putty White","DuraBuild Finish","Putty",640,430),
       ("BLD-PUTTY-S","Wall Putty Super","DuraBuild Finish","Putty",720,500),
       ("BLD-TILE-ADH","Tile Adhesive","DuraBuild Bond","Adhesive",560,360),
       ("BLD-WPROOF","Waterproof Compound","DuraBuild Bond","Adhesive",980,640),
       ("BLD-AAC","AAC Block Adhesive","DuraBuild Bond","Adhesive",430,300),
       ("BLD-PRIMER","Cement Primer","DuraBuild Finish","Putty",1150,760)]
for c,n,b,cat,mrp,cost in bld:
    prod_rows.append(dict(sku_code=c,industry_id="BLD",brand=b,sub_brand=cat,mrp=mrp,
                          category=cat,uom="bag",asp=round(mrp*0.86,2),unit_cost=cost))
pha = [("PHA-CARD10","Cardio-Pril 10","NovaCure Cardio","Cardiac",118,70),
       ("PHA-CARD5","Cardio-Pril 5","NovaCure Cardio","Cardiac",96,58),
       ("PHA-TELS80","Telsa-LN 80","NovaCure Cardio","Cardiac",142,82),
       ("PHA-ATOR10","Atorva-R 10","NovaCure Metabolic","Lipid",86,48),
       ("PHA-GLIM2","Glimisure 2","NovaCure Metabolic","Diabetes",64,36),
       ("PHA-PANTO40","Panto-Sure 40","NovaCure Gastro","Gastro",78,40)]
for c,n,b,cat,mrp,cost in pha:
    prod_rows.append(dict(sku_code=c,industry_id="PHA",brand=b,sub_brand=cat,mrp=mrp,
                          category=cat,uom="strip",asp=round(mrp*0.78,2),unit_cost=cost))
ren = [("REN-PNL540","Mono PERC 540W","SunPeak Modules","Panel",14500,10800),
       ("REN-PNL450","Mono PERC 450W","SunPeak Modules","Panel",11800,8900),
       ("REN-INV5K","Hybrid Inverter 5kW","SunPeak Power","Inverter",42000,31000),
       ("REN-INV10K","Hybrid Inverter 10kW","SunPeak Power","Inverter",78000,58000)]
for c,n,b,cat,mrp,cost in ren:
    prod_rows.append(dict(sku_code=c,industry_id="REN",brand=b,sub_brand=cat,mrp=mrp,
                          category=cat,uom="panel",asp=round(mrp*0.9,2),unit_cost=cost))
products = pd.DataFrame(prod_rows)

# -----------------------------------------------------------------------------
# 3. CHANNEL PARTNERS  (distributors -> dealers/retailers)
# -----------------------------------------------------------------------------
BLD_STATES = [("Rajasthan","West"),("Uttar Pradesh","North"),("Maharashtra","West"),
              ("Gujarat","West"),("Karnataka","South")]
PHA_HQ = [("Patna","East"),("Mumbai","West"),("Vijayawada","South"),("Bhubaneswar","East")]
REN_ZONES = [("North","Uttar Pradesh"),("West","Maharashtra"),("South","Karnataka"),("East","West Bengal")]

partners = []; pid = 1000
def add_partner(ind, ptype, parent, region, state, zone, tier, channel):
    global pid; pid += 1
    partners.append(dict(partner_id=f"P{pid}", name=fake.company()[:28], type=ptype,
                         parent_id=parent, industry_id=ind, region=region, state=state,
                         zone=zone, tier=tier, channel=channel,
                         active_since=fake.date_between(date(2018,1,1),date(2023,1,1)).isoformat()))
    return f"P{pid}"

# Building materials: 5 states x ~3 distributors -> each 3 dealers
for state,region in BLD_STATES:
    for _ in range(3):
        tier = np.random.choice(["A","B","C"],p=[.3,.4,.3])
        dist = add_partner("BLD","distributor",None,region,state,region,tier,"Direct")
        for _ in range(np.random.randint(2,4)):
            add_partner("BLD","dealer",dist,region,state,region,
                        np.random.choice(["B","C"]),"Direct")
# Pharma: 4 HQ x ~3 stockists -> each 2 chemists
for hq,region in PHA_HQ:
    for _ in range(3):
        stk = add_partner("PHA","stockist",None,region,hq,region,
                          np.random.choice(["A","B","C"]),"Direct")
        for _ in range(2):
            add_partner("PHA","chemist",stk,region,hq,region,"C","Direct")
# Renewables: 4 zones x ~2 partners (CP vs Direct), club tiers
for zone,state in REN_ZONES:
    for _ in range(2):
        ch = np.random.choice(["CP","Direct"],p=[.6,.4])
        club = np.random.choice(["Gold","Silver","-"],p=[.25,.45,.30])
        add_partner("REN","channel_partner",None,zone,state,zone,club,ch)
channel_partners = pd.DataFrame(partners)
dist_bld = channel_partners[(channel_partners.industry_id=="BLD")&(channel_partners.type=="distributor")].partner_id.tolist()
stk_pha  = channel_partners[(channel_partners.industry_id=="PHA")&(channel_partners.type=="stockist")].partner_id.tolist()
cp_ren   = channel_partners[channel_partners.industry_id=="REN"].partner_id.tolist()

# -----------------------------------------------------------------------------
# 4. SCHEMES MASTER
# -----------------------------------------------------------------------------
schemes = []; sid = 0
def add_scheme(ind, name, archetype, mode, qps_basis, slab_type, sku_scope, region_scope,
               channel_tier, slab, incentive_type, start, end, budget, status="active"):
    global sid; sid += 1
    scid = f"SCH{ind}{sid:03d}"
    schemes.append(dict(scheme_id=scid, industry_id=ind, name=name, archetype=archetype,
        mode=mode, qps_basis=qps_basis, slab_type=slab_type,
        sku_scope=json.dumps(sku_scope), region_scope=region_scope, channel_tier=channel_tier,
        baseline_ref="trailing_12m", slab_json=json.dumps(slab), incentive_type=incentive_type,
        start_date=str(start), end_date=str(end), budget=budget, status=status))
    return scid

def _status_for(start, end):
    if end < TODAY: return "expired"
    if start > TODAY: return "draft"
    return "active"

# Build the full scheme bundle for EVERY financial year, so each FY view is rich.
# fy_scheme_ids[fy_key] = dict naming the key schemes for that year (for needle wiring).
fy_scheme_ids = {}
yr_short = {"FY2023-24": "FY24", "FY2024-25": "FY25", "FY2025-26": "FY26"}
for fy in FYS:
    k = fy["key"]; tag = yr_short[k]
    p0, p1 = fy["promo"][0].start_time.date(), fy["promo"][-1].end_time.date()
    st = _status_for(p0, p1)
    win = add_scheme("BLD", f"Growth Booster - OPC RJ {tag}", "growth", "QPS", "value", "running",
        ["BLD-OPC53","BLD-PPC"], "Rajasthan", "A/B/C",
        [{"growth_pct":5,"payout_pct":1.0},{"growth_pct":10,"payout_pct":1.75},{"growth_pct":18,"payout_pct":2.5}],
        "cash", p0, p1, 4200000, status=st)
    dud = add_scheme("BLD", f"Monsoon Growth - OPC UP {tag}", "growth", "QPS", "value", "running",
        ["BLD-OPC53","BLD-PPC"], "Uttar Pradesh", "A/B/C",
        [{"growth_pct":4,"payout_pct":1.25},{"growth_pct":8,"payout_pct":2.0}],
        "cash", p0, p1, 3800000, status=st)
    st1 = add_scheme("BLD", f"In-Bill Discount - Putty {tag}", "value", "instant", None, "fixed",
        ["BLD-PUTTY-W","BLD-PUTTY-S"], "ALL", "A/B/C", [{"min_value":0,"payout_pct":2.0}], "discount", p0, p1, 1500000, status=st)
    st2 = add_scheme("BLD", f"Width Scheme - Putty {tag}", "volume", "instant", None, "step",
        ["BLD-PUTTY-W","BLD-PUTTY-S"], "ALL", "A/B/C", [{"min_qty":50,"payout_pct":1.5}], "discount", p0, p1, 1200000, status=st)
    st3 = add_scheme("BLD", f"Core Growth - Putty {tag}", "growth", "QPS", "qty", "running",
        ["BLD-PUTTY-W","BLD-PUTTY-S"], "ALL", "A/B/C", [{"growth_pct":6,"payout_pct":4.5}], "cash", p0, p1, 2600000, status=st)
    st4 = add_scheme("BLD", f"Cementitious Booster - Putty {tag}", "value", "instant", None, "fixed",
        ["BLD-PUTTY-W","BLD-PUTTY-S"], "ALL", "A/B/C", [{"min_value":0,"payout_pct":4.0}], "discount", p0, p1, 1800000, status=st)
    fg = add_scheme("BLD", f"Buy-10-Get-1 Tile Adhesive {tag}", "volume_freegoods", "instant", None, "step",
        ["BLD-TILE-ADH"], "ALL", "A/B/C", [{"buy":10,"free":1}], "free_goods", p0, p1, 900000, status=st)
    pha_oc = add_scheme("PHA", f"Cardio QPS - West {tag}", "target", "QPS", "qty", "step",
        ["PHA-CARD10","PHA-CARD5","PHA-TELS80"], "Mumbai", "A/B/C",
        [{"target_qty":800,"payout_pct":2.0},{"target_qty":1500,"payout_pct":3.5}], "cash", p0, p1, 2200000, status=st)
    pha_ok = add_scheme("PHA", f"Metabolic QPS - South {tag}", "target", "QPS", "value", "linear",
        ["PHA-ATOR10","PHA-GLIM2"], "Vijayawada", "A/B/C",
        [{"target_value":500000,"payout_pct":2.5}], "cash", p0, p1, 1600000, status=st)
    ren = add_scheme("REN", f"Elite Club {tag}", "club", "QPS", "value", "fixed",
        ["REN-PNL540","REN-PNL450","REN-INV5K","REN-INV10K"], "ALL", "Gold/Silver",
        [{"tier":"Silver","growth_pct":10,"payout_pct":1.0},{"tier":"Gold","growth_pct":20,"payout_pct":2.0}],
        "credit_note", p0, p1, 5000000, status=st)
    fy_scheme_ids[k] = dict(win=win, dud=dud, stacking=[st1,st2,st3,st4], fg=fg, pha_oc=pha_oc, pha_ok=pha_ok, ren=ren)

# ---- FY2026-27 (the running year): live now + approved-for-next-season + pipeline ----
# These are what a National Sales Head can ACT on today; NBA recommends from these,
# never from the expired past-year schemes.
# (a) ACTIVE now — an off-season Q1/Q2 volume push on putty (Apr-Sep 2026, live in July).
add_scheme("BLD","Monsoon Volume Push - Putty FY27","volume","instant",None,"step",
    ["BLD-PUTTY-W","BLD-PUTTY-S"],"ALL","A/B/C",[{"min_qty":40,"payout_pct":1.5}],"discount",
    date(2026,4,1),date(2026,9,30),1400000,status="active")
# (b) PLANNED / approved for the upcoming H2 season (Oct 2026 - Mar 2027) — proven archetypes re-run.
p0n, p1n = date(2026,10,1), date(2027,3,31)
add_scheme("BLD","Growth Booster - OPC RJ FY27","growth","QPS","value","running",
    ["BLD-OPC53","BLD-PPC"],"Rajasthan","A/B/C",
    [{"growth_pct":5,"payout_pct":1.0},{"growth_pct":10,"payout_pct":1.75},{"growth_pct":18,"payout_pct":2.5}],
    "cash",p0n,p1n,4600000,status="planned")
add_scheme("BLD","Width Scheme - Putty FY27","volume","instant",None,"step",
    ["BLD-PUTTY-W","BLD-PUTTY-S"],"ALL","A/B/C",[{"min_qty":50,"payout_pct":1.5}],"discount",
    p0n,p1n,1300000,status="planned")
add_scheme("BLD","Core Growth - Putty FY27","growth","QPS","qty","running",
    ["BLD-PUTTY-W","BLD-PUTTY-S"],"ALL","A/B/C",[{"growth_pct":6,"payout_pct":4.5}],"cash",
    p0n,p1n,2700000,status="planned")
add_scheme("REN","Elite Club FY27","club","QPS","value","fixed",
    ["REN-PNL540","REN-PNL450","REN-INV5K","REN-INV10K"],"ALL","Gold/Silver",
    [{"tier":"Silver","growth_pct":10,"payout_pct":1.0},{"tier":"Gold","growth_pct":20,"payout_pct":2.0}],
    "credit_note",p0n,p1n,5200000,status="planned")
# (c) DRAFT / pipeline — not yet approved (excluded from recommendations).
add_scheme("BLD","Q2 Draft Proposal - PPC","growth","QPS","value","running",["BLD-PPC"],"Gujarat","A/B/C",
    [{"growth_pct":6,"payout_pct":1.25}],"cash",date(2026,7,1),date(2026,9,30),2500000,status="draft")
schemes_master = pd.DataFrame(schemes)

# Needles point at the latest FY's schemes (what the default trailing-12m view surfaces).
_latest = fy_scheme_ids[FYS[-1]["key"]]
SC_FG = _latest["fg"]; SC_PHA_OC = _latest["pha_oc"]
PLANTED_NEEDLES.update(dict(N1_winner=_latest["win"], N2_dud=_latest["dud"],
    N5_stacking=_latest["stacking"], N4_overclaim_scheme=SC_PHA_OC,
    per_fy={k: v["win"] for k, v in fy_scheme_ids.items()}))

# -----------------------------------------------------------------------------
# 5. SALES (primary + secondary), STOCK, BASELINE
# -----------------------------------------------------------------------------
prim, sec, stock, base = [], [], [], []
oid = 0; tid = 0
def seasonal(m):
    # building-materials demand: monsoon trough (Jul-Aug), winter construction crest (Dec-Jan)
    return 1.0 + 0.06*math.cos((m.month-1)/12*2*math.pi)
_M0 = MONTHS[0]
def yoy_growth(m):
    # ~9%/yr compounding top-line growth so FY24 < FY25 < FY26 < FY27 (a real, growing business)
    yrs = (m.year - _M0.year) + (m.month - _M0.month) / 12.0
    return 1.09 ** yrs

# choose the leak distributor (N3) and cannibalisation pair (N6)
LEAK_DIST = dist_bld[0]                       # high sell-in, flat sell-out
CANN_PUSH, CANN_VICTIM = "BLD-PUTTY-S","BLD-PUTTY-W"   # pushing S depresses W

prod_by_ind = {i:products[products.industry_id==i].sku_code.tolist() for i in ["BLD","PHA","REN"]}
children = {p:channel_partners[channel_partners.parent_id==p].partner_id.tolist() for p in channel_partners.partner_id}

def base_qty(sku, tier):
    mult = {"A":1.6,"B":1.0,"C":0.6,"Gold":1.8,"Silver":1.1,"-":0.7,"CP":1.0,"Direct":1.0}.get(tier,1.0)
    anchor = {"BLD":140,"PHA":90,"REN":6}[products.set_index("sku_code").loc[sku,"industry_id"]]
    return max(1, anchor*mult)

cp_idx = channel_partners.set_index("partner_id")
for _,d in channel_partners.iterrows():
    if d.type not in ("distributor","stockist","channel_partner"): continue
    ind = d.industry_id
    for sku in prod_by_ind[ind]:
        b = base_qty(sku, d.tier)
        for m in MONTHS:
            s = seasonal(m)
            promo = m in ALL_PROMO
            # primary qty
            mult = 1.0
            if promo:
                mult = 1.12                                   # general promotional lift (most schemes work modestly)
                if d.state=="Rajasthan" and sku in ("BLD-OPC53","BLD-PPC"): mult = 1.34   # N1 winner (star)
                elif d.state=="Uttar Pradesh" and sku in ("BLD-OPC53","BLD-PPC"): mult = 0.84  # N2 dud: paid out yet sales FELL vs run-rate
                if ind=="BLD" and sku==CANN_PUSH: mult *= 1.10   # N6 push SKU
                if ind=="BLD" and sku==CANN_VICTIM: mult *= 0.90 # N6 victim SKU (net category still positive)
            q = np.random.normal(b*s, b*0.16) * mult * yoy_growth(m)
            # NEEDLE N3 leak: this distributor over-buys OPC during promo (sell-in spike)
            if promo and d.partner_id==LEAK_DIST and sku in ("BLD-OPC53","BLD-PPC"): q *= 1.7
            q = max(0, round(q))
            asp = float(products.set_index("sku_code").loc[sku,"asp"])
            if q>0:
                oid += 1
                prim.append(dict(order_id=f"PO{oid:06d}",partner_id=d.partner_id,sku_code=sku,
                    qty=q,value=round(q*asp,2),order_date=str(m.start_time.date()+timedelta(days=int(np.random.randint(0,27)))),
                    region=d.state))
            # ---- secondary (sell-out) ----
            so = q*np.random.uniform(0.85,0.98)
            if promo and d.partner_id==LEAK_DIST and sku in ("BLD-OPC53","BLD-PPC"):
                so = q*0.42          # NEEDLE N3: sell-out stays flat -> loading
            so = max(0, round(so))
            kids = children.get(d.partner_id,[])
            to = random.choice(kids) if kids else d.partner_id
            if so>0:
                tid += 1
                sec.append(dict(txn_id=f"SO{tid:06d}",from_partner_id=d.partner_id,to_partner_id=to,
                    sku_code=sku,qty=so,value=round(so*asp*1.05,2),
                    sale_date=str(m.start_time.date()+timedelta(days=int(np.random.randint(0,27))))))
            # ---- stock ----
            opening = max(0, round(b*0.4))
            closing = max(0, opening + q - so)
            if promo and d.partner_id==LEAK_DIST and sku in ("BLD-OPC53","BLD-PPC"):
                closing = round(opening + q - so)   # balloons
            stock.append(dict(partner_id=d.partner_id,sku_code=sku,month=str(m),
                opening_stock=opening,closing_stock=closing,
                stock_in_transit=max(0,round(np.random.normal(b*0.1,b*0.05)))))

primary_sales = pd.DataFrame(prim)
secondary_sales = pd.DataFrame(sec)
stock_position = pd.DataFrame(stock)

# Rolling baseline (industry standard): for each (sku,state,month), the baseline is
# the trailing average of NON-PROMOTIONAL months (the true "what would have sold
# anyway" counterfactual) ending before month m — so promo uplift is measured
# against un-promoted run-rate, not against prior inflated promo seasons.
pre = primary_sales.merge(channel_partners[["partner_id","state"]],on="partner_id")
pre["month"]=pd.PeriodIndex(pd.to_datetime(pre.order_date).dt.to_period("M"))
mtot = pre.groupby(["sku_code","state","month"]).agg(q=("qty","sum"),v=("value","sum")).reset_index()
month_list = list(MONTHS)
nonpromo = set(m for m in month_list if m not in ALL_PROMO)
rows=[]
for (sku,state),g in mtot.groupby(["sku_code","state"]):
    gm = g.set_index("month")
    npm_all = [m for m in month_list if m in nonpromo and m in gm.index]
    for m in month_list:
        prior_np = [mm for mm in npm_all if mm < m][-12:]      # trailing non-promo months
        use = prior_np if prior_np else npm_all                # fallback: all non-promo
        qv = [gm.loc[pm,"q"] for pm in use]
        vv = [gm.loc[pm,"v"] for pm in use]
        if qv:
            bq, bv = float(np.mean(qv)), float(np.mean(vv))
        else:
            bq = float(gm.loc[m,"q"]) if m in gm.index else 0.0
            bv = float(gm.loc[m,"v"]) if m in gm.index else 0.0
        rows.append(dict(sku_code=sku,region=state,month=str(m),
                         baseline_qty=round(bq,1),baseline_value=round(bv,1)))
baseline_sales = pd.DataFrame(rows)

# -----------------------------------------------------------------------------
# 6. SCHEME APPLICATION (stacking + applied_flag/skip_reason)  &  CLAIMS
# -----------------------------------------------------------------------------
appl = []
sm = schemes_master.set_index("scheme_id")
def scheme_skus(scid): return set(json.loads(sm.loc[scid,"sku_scope"]))
def scheme_state(scid): return sm.loc[scid,"region_scope"]

prim_m = primary_sales.copy()
prim_m["month"]=pd.PeriodIndex(pd.to_datetime(prim_m.order_date).dt.to_period("M"))
prim_m = prim_m.merge(channel_partners[["partner_id","state","tier","industry_id"]],on="partner_id")

# Apply each FY's schemes to invoices within that FY's promo season.
overclaim_schemes = set()
for fy in FYS:
    ids = fy_scheme_ids[fy["key"]]
    fy_scheme_list = [ids["win"],ids["dud"],*ids["stacking"],ids["fg"],ids["pha_oc"],ids["pha_ok"],ids["ren"]]
    overclaim_schemes.add(ids["pha_oc"])
    fg_id = ids["fg"]; skip_month = fy["promo"][2]
    inv_fy = prim_m[prim_m.month.isin(list(fy["promo"]))]
    for _,inv in inv_fy.iterrows():
        for scid in fy_scheme_list:
            if inv.sku_code not in scheme_skus(scid): continue
            stt = scheme_state(scid)
            if stt!="ALL" and stt!=inv.state: continue
            slabset = json.loads(sm.loc[scid,"slab_json"])
            pct = max([s.get("payout_pct",0) for s in slabset]+[0])/100.0
            payout = round(inv.value*pct,2) if pct else 0.0
            applied, skip = True, ""
            # NEEDLE N8: free-goods scheme silently not applying for one SKU/month
            if scid==fg_id and inv.month==skip_month:
                applied, skip, payout = False, "scope_mismatch: SKU flagged inactive in master during sync", 0.0
            appl.append(dict(invoice_id=inv.order_id,scheme_id=scid,applied_qty=inv.qty,
                computed_payout=payout,effective_pct=round(pct*100,3),
                applied_flag=applied,skip_reason=skip))
scheme_application = pd.DataFrame(appl)

# claims = aggregate computed payout per partner x scheme, then perturb (over-claim needle)
ap = scheme_application[scheme_application.applied_flag].merge(
        primary_sales[["order_id","partner_id"]],left_on="invoice_id",right_on="order_id")
earned = ap.groupby(["partner_id","scheme_id"]).agg(earned=("computed_payout","sum")).reset_index()
claims=[]; cid=0
sc_end = {sid: sm.loc[sid,"end_date"] for sid in sm.index}
_oc_seen = {}    # inflate ~every 2nd claimant on each FY's pharma over-claim scheme
for _,r in earned.iterrows():
    cid+=1
    claimed = r.earned; status="ok"
    if r.scheme_id in overclaim_schemes:
        _oc_seen[r.scheme_id] = _oc_seen.get(r.scheme_id, 0) + 1
        if _oc_seen[r.scheme_id] % 2 == 1 and r.earned > 0:   # NEEDLE N4 over-claim
            claimed = round(r.earned*1.6,2); status="over_claim"
    claims.append(dict(claim_id=f"CLM{cid:05d}",partner_id=r.partner_id,scheme_id=r.scheme_id,
        claimed_qty=0,claimed_amount=round(claimed,2),claim_date=str(sc_end.get(r.scheme_id,"")),status=status))
scheme_claims = pd.DataFrame(claims)

# -----------------------------------------------------------------------------
# 7. TARGETS  &  MASTER SYNC LOG (N7 dirty data)
# -----------------------------------------------------------------------------
tgt=[]
for pid_ in dist_bld+stk_pha+cp_ren:
    tgt.append(dict(partner_id=pid_,scheme_id="",period="2026-Q1",
        target_qty=int(np.random.randint(500,3000)),target_value=int(np.random.randint(8,40))*100000,
        base_year_value=int(np.random.randint(6,30))*100000))
targets=pd.DataFrame(tgt)

sync=[]; n_ok=0
SYNC_N = 3000
sync_start = MONTHS[0].start_time.date(); sync_end = MONTHS[-1].end_time.date()
errors = ["invoice number already exists","material no. does not exist in the system",
          "invalid ship-to / sold-to party","net amount cannot be zero for the item",
          "stock not available for the given period","retailer master mismatch between source and DMS",
          "decimal place not allowed for the UOM"]
for i in range(SYNC_N):
    fail = np.random.rand()<0.07          # ~7% failures
    et = np.random.choice(["invoice","retailer_master","material_master"],p=[.7,.2,.1])
    sync.append(dict(entity_type=et,entity_id=f"{et[:3].upper()}{i:05d}",source="ERP/Tally",
        status="fail" if fail else "ok",
        error_reason=(np.random.choice(errors) if fail else ""),
        ts=str(fake.date_time_between(start_date=sync_start,end_date=sync_end))))
    n_ok += (0 if fail else 1)
# NEEDLE N7: a specific retailer master mismatch tied to a real partner
sync.append(dict(entity_type="retailer_master",entity_id=LEAK_DIST,source="ERP/Tally",status="fail",
    error_reason="retailer master mismatch between source and DMS",ts=str(sync_end)))
master_sync_log=pd.DataFrame(sync)
PLANTED_NEEDLES.update(dict(N3_leak_distributor=LEAK_DIST,N6_cannibal_pair=[CANN_PUSH,CANN_VICTIM],
    N7_sync_fail_rate=round(1-n_ok/SYNC_N,3),N8_nonapplying_scheme=SC_FG))

# -----------------------------------------------------------------------------
# WRITE
# -----------------------------------------------------------------------------
tables = dict(industries=industries,products=products,channel_partners=channel_partners,
    schemes_master=schemes_master,primary_sales=primary_sales,secondary_sales=secondary_sales,
    stock_position=stock_position,scheme_application=scheme_application,scheme_claims=scheme_claims,
    baseline_sales=baseline_sales,targets=targets,master_sync_log=master_sync_log)
for name,df in tables.items():
    df.to_csv(os.path.join(OUT,f"{name}.csv"),index=False)

with open(os.path.join(OUT,"_planted_needles.json"),"w") as f:
    json.dump(PLANTED_NEEDLES,f,indent=2)

print("=== PromoLens synthetic data generated ===")
for name,df in tables.items():
    print(f"  {name:22s} {len(df):>7,} rows")
print("\nPlanted needles:")
print(json.dumps(PLANTED_NEEDLES,indent=2))
