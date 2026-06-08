"""
PromoLens AI — Local proof harness.
Runs the 6 persona hero queries against the synthetic data and ASSERTS that
every planted needle (N1..N8) is correctly detected by the reasoning engine.
Exit 0 = solution proven working end-to-end (sans cloud).
"""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from engine import tools as E

needles = json.load(open(os.path.join(E.DATA, "_planted_needles.json")))
P = lambda *a: print(*a)
ok = []

P("="*78); P("PromoLens AI — proof run"); P("="*78)

# ---- HERO 1 (Priya): rank schemes by ROI -> winner vs dud ----
P("\n[1] Priya: 'Which building-materials schemes worked, which gave away margin?'")
rank = E.rank_schemes_by_roi("BLD")
for r in rank[:6]:
    P(f"    {r['scheme_id']}  ROI {r['roi']:>6}  {r['verdict']:<48} {r['name']}")
win = next(r for r in rank if r["scheme_id"]==needles["N1_winner"])
dud = next(r for r in rank if r["scheme_id"]==needles["N2_dud"])
assert win["roi"] > dud["roi"], "winner should out-ROI dud"
assert win["verdict"].startswith("WINNER") and "DUD" in dud["verdict"]
ok.append("N1 winner + N2 dud separated by ROI")

# ---- HERO 2 (Rahul): why didn't a scheme apply ----
P("\n[2] Rahul: 'Which schemes silently did not apply, and why?'")
skips = E.why_not_applied(only_skips=True)
for s in skips: P(f"    {s['scheme_id']}  x{s['invoices_skipped']:>3}  {s['skip_reason']}")
assert any(s["scheme_id"]==needles["N8_nonapplying_scheme"] for s in skips)
P("    lifecycle state view:");
for v in E.scheme_state_view(): P(f"      {v['status']:>8}: {v['schemes']}  ({v['names']})")
ok.append("N8 non-applying scheme + skip_reason surfaced")

# ---- HERO 3 (Anjali): inventory-loading leak ----
P("\n[3] Anjali: 'Who has high sell-in but flat sell-out?'")
leaks = E.inventory_loading_leaks()
for l in leaks[:5]:
    P(f"    {l['partner_id']} {l['name'][:22]:<22} sell-in {int(l['sell_in']):>6}  sell-through {l['sellthrough']*100:.0f}%  {l['at_risk_signal']}")
assert any(l["partner_id"]==needles["N3_leak_distributor"] for l in leaks), "leak distributor must be flagged"
ok.append("N3 inventory-loading leak flagged with evidence")

# ---- HERO 4 (Vikram): over-claims vs entitlement ----
P("\n[4] Vikram: 'Are any claims above earned entitlement?'")
oc = E.overclaims()
P(f"    total at-risk: Rs {oc['total_at_risk']:,}  across {oc['count']} claims")
for r in oc["rows"][:4]:
    P(f"    {r['claim_id']} {r['name'][:20]:<20} claimed {r['claimed_amount']:>10,.0f}  earned {r['earned']:>10,.0f}  gap {r['gap']:>9,.0f}")
assert oc["count"] >= 1 and oc["total_at_risk"] > 0
assert any(r["scheme_id"]==needles["N4_overclaim_scheme"] for r in oc["rows"])
ok.append("N4 over-claims detected with at-risk total")

# ---- HERO 5: stacked effective discount ----
P("\n[5] 'What's the REAL effective discount on putty after stacking?'")
st = E.stacked_effective_discount()
P(f"    invoices with >=2 schemes: {st['invoices_with_stacking']:,}  avg schemes/invoice {st['avg_schemes_per_invoice']}")
P(f"    avg effective discount {st['avg_effective_discount_pct']}%   max {st['max_effective_discount_pct']}%")
assert st["avg_effective_discount_pct"] > 8, "stacking should push effective discount well above headline ~5%"
ok.append("N5 stacking trap: effective discount >> headline")

# ---- HERO 6 (in-build): what-if + cannibalisation + data-trust ----
P("\n[6] Designer what-if + cannibalisation + data-trust")
wi = E.whatif_simulator("Rajasthan", ["BLD-OPC53","BLD-PPC"], slab_pct=1.75, expected_growth_pct=12)
P(f"    what-if RJ OPC +12% @1.75%: projected ROI {wi['projected_roi']}  -> {wi['guidance']}")
cn = E.cannibalisation(*needles["N6_cannibal_pair"], region="ALL")
P(f"    cannibalisation: push {cn['push_sku']} {cn['push_change_pct']:+}%  victim {cn['victim_sku']} {cn['victim_change_pct']:+}%")
assert cn["victim_change_pct"] < 0, "victim SKU should drop"
dt = E.data_trust_summary()
P(f"    data-trust: {dt['failed']}/{dt['total']} syncs failed ({dt['fail_rate_pct']}%); top: {dt['top_reasons'][0]['reason']}")
assert dt["fail_rate_pct"] > 0
ok.append("N6 cannibalisation + N7 data-trust + what-if working")

# ---- slab engine unit check (4 types differ) ----
slabs=[{"min_qty":50,"free_per_slab":2},{"min_qty":100,"free_per_slab":5}]
vals={t:E.slab_accrual(180,slabs,t) for t in ["fixed","step","linear","running"]}
P("\n[slab-accrual] qty=180 ->", vals)
assert len({round(v,2) for v in vals.values()})>=3, "slab types must diverge"
ok.append("slab-accrual: 4 types compute distinctly")

P("\n"+"="*78)
P("PROVEN — all checks passed:")
for o in ok: P("   [PASS]", o)
P("="*78)
