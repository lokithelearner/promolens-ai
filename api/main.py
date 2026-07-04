import os, sys, uuid, json, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from agents.agent import root_agent
from engine import tools as E
from engine import semantic as S
from engine import scheme_rag as R
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

_GEMINI_MODEL = os.environ.get("PROMOLENS_MODEL", "gemini-2.5-flash")
_GEMINI_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
_GEMINI_PROJECT = os.environ.get("PROMOLENS_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")


def _gemini(prompt, image_bytes=None, mime=None):
    """Direct Gemini call (Vertex) for narration / vision. Raises on failure so
    callers can fall back to deterministic output."""
    import vertexai
    from vertexai.generative_models import GenerativeModel, Part
    vertexai.init(project=_GEMINI_PROJECT, location=_GEMINI_LOCATION)
    model = GenerativeModel(_GEMINI_MODEL)
    parts = []
    if image_bytes is not None:
        parts.append(Part.from_data(data=image_bytes, mime_type=mime or "image/png"))
    parts.append(prompt)
    return model.generate_content(parts).text

APP = "promolens"
session_service = InMemorySessionService()
runner = Runner(agent=root_agent, app_name=APP, session_service=session_service)
app = FastAPI(title="PromoLens AI")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

UI_PATH = os.path.join(os.path.dirname(__file__), "..", "ui", "public", "index.html")


class ChatIn(BaseModel):
    message: str
    session_id: str | None = None
    window: str | None = None


def _rupees(n):
    n = float(n or 0)
    if abs(n) >= 1e7: return f"Rs {n/1e7:.2f} Cr"
    if abs(n) >= 1e5: return f"Rs {n/1e5:.1f} L"
    return f"Rs {round(n):,}"


def deterministic_answer(msg: str, win: str | None = None) -> str:
    """Plain, decision-ready answers for business users: the number + what to do."""
    m = (msg or "").lower()
    try:
        if any(k in m for k in ["next best", "next-best", "who should", "push to", "which distributor", "which partner", "recommend a scheme", "recommend scheme", "prescrib", "next action", "what should i do"]):
            nba = E.nba_recommendations("BLD", win)
            if not nba["recommendations"]:
                return "No eligible next-best-scheme recommendations in this window yet."
            risk = [r for r in nba["recommendations"] if r["constraint"]]
            go = [r for r in nba["recommendations"] if not r["constraint"]]
            lead = go[0] if go else nba["recommendations"][0]
            out = (f"Next best action: {lead['action']} Total identified upside across partners: "
                   f"{_rupees(nba['total_upside'])}.")
            if risk:
                out += (f" First, fix {len(risk)} at-risk partner(s) — e.g. {risk[0]['name']} "
                        f"({'inventory loading' if risk[0]['constraint']=='inventory_loading' else 'open over-claim'}).")
            return out
        if any(k in m for k in ["missed", "untapped", "leaving money", "underperform", "opportunit", "white space", "gap to peer"]):
            mo = E.missed_opportunities("BLD", win)
            if not mo["opportunities"]:
                return "No clear missed-opportunity gaps versus peers in this window."
            o = mo["opportunities"][0]
            return (f"Biggest missed opportunity: {o['action']} Total identified upside across the top gaps: "
                    f"{_rupees(mo['total_upside'])}. → Do this: target these under-indexed partners with the covering scheme.")
        if any(k in m for k in ["entitle", "claim window", "eligible for", "terms of", "clause", "what does scheme", "payout does", "how much payout", "scheme terms", "circular"]):
            a = R.answer_scheme_question(msg)
            if not a["citations"]:
                return a["answer"]
            c = a["citations"][0]
            cite = f" [source: {c['scheme']} — {c['clause']}]"
            conflict = f" Note: {a['conflict']['note']}" if a.get("conflict") else ""
            return f"{a['answer']}{cite}{conflict}"
        if any(k in m for k in ["leak", "sell-in", "sell out", "sell-out", "inventory", "loading", "loading inventory"]):
            rows = E.inventory_loading_leaks(win=win)
            if not rows:
                return "Good news — no signs of inventory loading right now. Distributors are selling through what they buy."
            r = rows[0]
            return (f"{r['name']} ({r['state']}) is loading inventory: buying a lot of {r['sku_code']} but only "
                    f"{r['sellthrough']*100:.0f}% is actually selling through (stock piled up: {int(r['closing'])} units). "
                    f"They're buying to claim the incentive, not because there's demand. "
                    f"→ Do this: pause further dispatch to them and verify real sell-out before paying the scheme.")
        if any(k in m for k in ["claim", "entitlement", "paying", "pay"]):
            oc = E.overclaims()
            if oc["count"] == 0:
                return "No over-claims found — what partners are claiming matches what they earned."
            top = oc["rows"][0]
            return (f"Yes — {oc['count']} claim(s) are higher than what was actually earned, {_rupees(oc['total_at_risk'])} at risk. "
                    f"Largest: {top['name']} claimed {_rupees(top['claimed_amount'])} but earned only {_rupees(top['earned'])}. "
                    f"→ Do this: block or recover {_rupees(oc['total_at_risk'])} before the next payout run.")
        if any(k in m for k in ["stack", "effective discount", "putty", "real discount"]):
            s = E.stacked_effective_discount()
            return (f"On putty, several schemes pile onto the same invoice. The real discount works out to about "
                    f"{s['avg_effective_discount_pct']}% (up to {s['max_effective_discount_pct']}%) — even though each scheme looks like ~5%. "
                    f"That extra margin leaks away without anyone deciding it. → Do this: cap the total discount allowed per invoice.")
        if any(k in m for k in ["apply", "applied", "active", "expired", "didn't apply", "not apply", "live"]):
            skips = E.why_not_applied(only_skips=True)
            states = {x["status"]: x["schemes"] for x in E.scheme_state_view()}
            if skips:
                s0 = skips[0]
                return (f"{states.get('active',0)} schemes are live, {states.get('expired',0)} expired, {states.get('draft',0)} still in draft. "
                        f"One isn't applying: {s0['scheme_id']} skipped {s0['invoices_skipped']} invoices because {s0['skip_reason']}. "
                        f"→ Do this: fix that scheme's setup so customers actually get the offer.")
            return f"{states.get('active',0)} schemes are live and applying correctly; {states.get('expired',0)} expired, {states.get('draft',0)} in draft."
        if any(k in m for k in ["sync", "master", "data trust", "mismatch", "data quality"]):
            d = E.data_trust_summary()
            reason = d["top_reasons"][0]["reason"] if d.get("top_reasons") else ""
            return (f"{d['fail_rate_pct']}% of sales records didn't sync cleanly ({d['failed']} of {d['total']}), mostly: {reason}. "
                    f"Your scheme numbers are only as reliable as this data. → Do this: clean the master data and re-sync before trusting payouts.")
        if "cannibal" in m:
            c = E.cannibalisation("BLD-PUTTY-S", "BLD-PUTTY-W")
            return (f"Pushing {c['push_sku']} ({c['push_change_pct']:+}%) is eating into {c['victim_sku']} ({c['victim_change_pct']:+}%) — "
                    f"you're partly shifting sales, not adding them. → Do this: judge the scheme on total category growth, not one SKU.")
        if any(k in m for k in ["similar", "like this", "find scheme", "worked before", "precedent", "past scheme", "comparable", "find me a scheme"]):
            sim = S.find_similar_schemes(msg, k=3)
            if not sim["matches"]:
                return "No comparable past schemes found for that description yet."
            top = sim["matches"][0]
            others = ", ".join(f"{x['name']} ({x['region']})" for x in sim["matches"][1:])
            return (f"Closest past scheme: {top['name']} — a {top['archetype']} scheme on {top['skus']} in {top['region']} "
                    f"({top['channel']} channel). Other close matches: {others}. "
                    f"→ Do this: reuse this design as your starting template and adjust the slab for the new region.")
        if any(k in m for k in ["design", "what if", "what-if", "recommend", "propose", "budget", "launch", "next"]):
            w = E.whatif_simulator("Rajasthan", ["BLD-OPC53", "BLD-PPC"], 1.75, 12)
            verdict = "worth running" if w["projected_roi"] > 1 else "marginal — tighten it first"
            precedent = ""
            try:
                sim = S.find_similar_schemes("growth target scheme OPC cement Rajasthan", k=1)
                if sim["matches"]:
                    precedent = f" Closest precedent on record: {sim['matches'][0]['name']}."
            except Exception:
                pass
            return (f"For a Rajasthan OPC growth scheme (+12% target, ~1.75% payout): expected extra sales {_rupees(w['incremental_value'])}, "
                    f"cost {_rupees(w['projected_outflow'])}, so about Rs {w['projected_roi']} back per Rs 1. That's {verdict}.{precedent} "
                    f"→ Do this: launch in Rajasthan; copy the design that already works there.")
        rank = E.rank_schemes_by_roi("BLD")
        if not rank:
            return "No active building-materials schemes to assess yet."
        win, dud = rank[0], rank[-1]
        body = " | ".join(f"{r['name']}: Rs {r['roi']} back per Rs 1" for r in rank[:5])
        tail = ""
        if dud["roi"] < 0.3:
            tail = (f" Your weakest is {dud['name']} — it loses money (those sales would've happened anyway). "
                    f"→ Do this: scale {win['name']}, and stop or redesign {dud['name']}.")
        return f"Best scheme: {win['name']} — earns Rs {win['roi']} for every Rs 1 spent. Ranked: {body}.{tail}"
    except Exception as e:
        return f"(could not compute right now: {e})"


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def home():
    try:
        with open(UI_PATH, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return "<h1>PromoLens AI</h1><p>UI not found. API is at /chat.</p>"


@app.get("/api/windows")
def windows():
    try:
        return {"windows": E.list_windows()}
    except Exception:
        return {"windows": [{"key": "ttm", "label": "Last 12 months (benchmark)", "default": True}]}


@app.get("/api/dashboard")
def dashboard(win: str | None = None):
    E.set_default_window(win)
    label = E.resolve_window(win)[1]
    out = {"window": win or "ttm", "window_label": label}
    try:
        out["schemes"] = E.rank_schemes_by_roi("BLD", win)
    except Exception as e:
        out["schemes"] = []
        out["schemes_error"] = str(e)
    try:
        out["leaks"] = E.inventory_loading_leaks(win=win)[:5]
    except Exception:
        out["leaks"] = []
    try:
        out["overclaims"] = E.overclaims(win)
    except Exception:
        out["overclaims"] = {"total_at_risk": 0, "count": 0, "rows": []}
    try:
        out["trust"] = E.data_trust_summary(win)
    except Exception:
        out["trust"] = {}
    try:
        out["stacking"] = E.stacked_effective_discount(win=win)
    except Exception:
        out["stacking"] = {}
    return out


_ADV_CACHE: dict = {}   # in-process cache; data is static per container so this is safe


@app.get("/api/nba")
def nba(win: str | None = None):
    """Next-Best-Scheme leaderboard (prescriptive, constraint-aware). Cached per window."""
    E.set_default_window(win)
    key = ("nba", win or "ttm")
    if key in _ADV_CACHE:
        return _ADV_CACHE[key]
    try:
        r = E.nba_recommendations("BLD", win)
        _ADV_CACHE[key] = r
        return r
    except Exception as e:
        return {"recommendations": [], "error": str(e)}


@app.get("/api/missed")
def missed(win: str | None = None):
    """Missed-opportunity finder: under-indexed partner x SKU gaps vs peers. Cached per window."""
    E.set_default_window(win)
    key = ("missed", win or "ttm")
    if key in _ADV_CACHE:
        return _ADV_CACHE[key]
    try:
        r = E.missed_opportunities("BLD", win)
        _ADV_CACHE[key] = r
        return r
    except Exception as e:
        return {"opportunities": [], "error": str(e)}


@app.get("/api/scheme-search")
def scheme_search(q: str):
    """Grounded scheme-terms answer with clause citations (Vertex AI Search / local)."""
    try:
        return R.answer_scheme_question(q)
    except Exception as e:
        return {"answer": "", "citations": [], "error": str(e)}


@app.get("/api/schemes")
def schemes_catalog():
    """The scheme book: every scheme's definition, grouped by lifecycle status."""
    import json as _json
    sm = E.T["schemes_master"]
    def slab_summary(s):
        try:
            sl = _json.loads(s) if isinstance(s, str) else (s or [])
        except Exception:
            sl = []
        parts = []
        for x in sl:
            if not isinstance(x, dict):
                continue
            if "growth_pct" in x and "tier" not in x:
                parts.append(f"grow +{x['growth_pct']}% → pay {x.get('payout_pct','?')}%")
            elif "min_qty" in x:
                parts.append(f"buy ≥{x['min_qty']}u → {x.get('payout_pct','?')}%")
            elif "min_value" in x:
                parts.append(f"flat {x.get('payout_pct','?')}% in-bill")
            elif "buy" in x:
                parts.append(f"buy {x['buy']} get {x.get('free',1)} free")
            elif "target_qty" in x:
                parts.append(f"target {x['target_qty']}u → {x.get('payout_pct','?')}%")
            elif "target_value" in x:
                parts.append(f"target ₹{int(x['target_value']):,} → {x.get('payout_pct','?')}%")
            elif "tier" in x:
                parts.append(f"{x['tier']}: +{x.get('growth_pct','?')}% → {x.get('payout_pct','?')}%")
        return "  ·  ".join(parts) or "—"
    cp = E.T["channel_partners"]
    name_by = cp.set_index("partner_id")["name"].to_dict()
    st_by = cp.set_index("partner_id")["state"].to_dict()
    # completed schemes -> partners the scheme actually applied to (from applications)
    ps = E._promo_primary()
    apj = E.T["scheme_application"].merge(ps[["order_id", "partner_id"]], left_on="invoice_id", right_on="order_id")
    applied_by = {}
    for sid_, g in apj[apj.applied_flag].groupby("scheme_id"):
        applied_by[sid_] = list(dict.fromkeys(g["partner_id"].tolist()))
    # forward schemes -> eligible dealers with a trailing base in the scheme's SKUs (NBA targets)
    wmonths, _, _ = E.resolve_window(None)
    pw = ps[ps.month.isin(wmonths)]
    base_by_ps = pw.groupby(["partner_id", "sku_code"])["value"].sum()

    def partners_for(scid, status, skus, region, tier):
        rows = []
        if status in ("active", "planned", "approved", "draft"):
            for _, prow in cp.iterrows():
                if not E._partner_type_is_channel(prow.get("type")):
                    continue
                if not E._region_ok(region, prow.get("state")) or not E._tier_ok(tier, prow.get("tier")):
                    continue
                base = sum(float(base_by_ps.get((prow["partner_id"], s), 0.0)) for s in skus)
                if base > 0:
                    rows.append((prow["name"], prow.get("state"), round(base)))
            rows.sort(key=lambda x: -x[2])
        else:  # completed -> who it applied to
            for pid_ in applied_by.get(scid, []):
                rows.append((name_by.get(pid_, pid_), st_by.get(pid_, ""), 0))
        return [dict(name=n, state=s, base=b) for n, s, b in rows[:12]], len(rows)

    out = []
    for _, r in sm.iterrows():
        try:
            skus = _json.loads(r["sku_scope"]) if isinstance(r["sku_scope"], str) else list(r["sku_scope"])
        except Exception:
            skus = []
        status = str(r.get("status", "")).lower()
        plist, pn = partners_for(r["scheme_id"], status, skus, r.get("region_scope"), r.get("channel_tier"))
        out.append(dict(scheme_id=r["scheme_id"], name=r["name"], industry=r.get("industry_id"),
                        archetype=r.get("archetype"), mode=r.get("mode"), incentive=r.get("incentive_type"),
                        region=r.get("region_scope"), tier=r.get("channel_tier"), skus=skus,
                        slabs=slab_summary(r.get("slab_json")), start=str(r.get("start_date")),
                        end=str(r.get("end_date")), budget=int(float(r.get("budget") or 0)),
                        status=status, partners=plist, partner_count=pn))
    order = {"active": 0, "planned": 1, "draft": 2, "expired": 3}
    out.sort(key=lambda x: (order.get(x["status"], 9), x["scheme_id"]))
    return {"schemes": out, "count": len(out)}


@app.get("/api/whatif")
def whatif(scheme_id: str, win: str | None = None):
    """Forecast a NEW scheme modelled on an existing one: pull the template scheme's
    region, SKU scope and top slab, then project a conservative / base / optimistic
    confidence band (deterministic engine)."""
    E.set_default_window(win)
    try:
        import json as _json
        sc = E.T["schemes_master"].set_index("scheme_id").loc[scheme_id]
        region = sc["region_scope"] or "ALL"
        try:
            skus = _json.loads(sc["sku_scope"]) if isinstance(sc["sku_scope"], str) else list(sc["sku_scope"])
        except Exception:
            skus = []
        ask, pay = E._top_slab(sc)
        band = E.whatif_band(region, skus, pay, ask, win)
        return {"scheme_id": scheme_id, "template_name": sc["name"], "region": region,
                "skus": skus, "assumed_growth_pct": ask, "assumed_payout_pct": pay, **band}
    except Exception as e:
        return {"error": str(e)}


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


def _portfolio_facts(win: str | None = None):
    """Collect the key numbers the exec report / health score are built from.
    Every sub-call is guarded so the report can never 500 on one bad table."""
    rank = _safe(lambda: E.rank_schemes_by_roi("BLD", win), [])
    oc = _safe(lambda: E.overclaims(win), {"total_at_risk": 0, "count": 0, "rows": []})
    leaks = _safe(lambda: E.inventory_loading_leaks(win=win), [])
    stk = _safe(lambda: E.stacked_effective_discount(win=win), {})
    trust = _safe(lambda: E.data_trust_summary(win), {})
    win = rank[0] if rank else None
    dud = rank[-1] if rank else None
    profitable = sum(1 for r in rank if r["roi"] > 1)
    health = 0
    if rank:
        health = round(0.6 * (profitable / len(rank)) * 100 + 0.4 * max(0, 100 - trust.get("fail_rate_pct", 0) * 3))
    return dict(rank=rank, win=win, dud=dud, overclaims=oc, leaks=leaks,
                stacking=stk, trust=trust, profitable=profitable,
                total_schemes=len(rank), health=health)


@app.get("/api/report")
def exec_report(win: str | None = None):
    """One-click leadership narrative, written by Gemini from the engine numbers."""
    E.set_default_window(win)
    f = _portfolio_facts(win)
    facts = (
        f"Active schemes assessed: {f['total_schemes']}, of which {f['profitable']} are profitable (ROI>1).\n"
        f"Scheme Health Score: {f['health']}/100.\n"
        f"Best scheme: {f['win']['name']} at ROI {f['win']['roi']} (Rs back per Rs 1).\n" if f['win'] else ""
    )
    if f["dud"]:
        facts += f"Worst scheme: {f['dud']['name']} at ROI {f['dud']['roi']}.\n"
    facts += (f"Over-claims: {f['overclaims']['count']} claims totalling {_rupees(f['overclaims']['total_at_risk'])} at risk.\n"
              f"Inventory-loading signals: {len(f['leaks'])} partner-SKU combinations.\n"
              f"Putty discount stacking: true effective discount ~{f['stacking'].get('avg_effective_discount_pct','?')}% "
              f"(headline looks ~5%).\n"
              f"Data trust: {f['trust'].get('fail_rate_pct','?')}% of records failed to sync cleanly.\n")

    wlabel = "the trailing 12 months" if not win or win == "ttm" else f"the {win} window"
    prompt = ("You are PromoLens AI writing a trade-promotion summary for a manufacturer's National Sales Head. "
              f"ALL figures below cover {wlabel} (an annual view) — never say 'this week' or 'this month'; refer to "
              f"the analysis window as '{wlabel}'. Using ONLY these facts, write a crisp, confident 5-6 sentence "
              "executive briefing in plain business English: headline state of the portfolio, the single biggest win "
              "to scale, the biggest money leak to recover (with the rupee figure and that it is the exposure over "
              f"{wlabel}, not a weekly number), and one clear recommended action. No jargon, no bullet symbols. "
              f"FACTS:\n{facts}")
    mode = "llm"
    try:
        narrative = _gemini(prompt).strip()
    except Exception:
        mode = "engine"
        win = f["win"]; dud = f["dud"]
        narrative = (
            f"Over {wlabel}, {f['profitable']} of {f['total_schemes']} active schemes are profitable, giving a portfolio "
            f"health score of {f['health']}/100. The standout is {win['name'] if win else 'n/a'}, returning "
            f"Rs {win['roi'] if win else 0} for every Rs 1 spent — scale it. The most urgent leak is "
            f"{_rupees(f['overclaims']['total_at_risk'])} in over-claims across {f['overclaims']['count']} claims, "
            f"recoverable before the next payout run. Putty schemes are also stacking to an effective "
            f"~{f['stacking'].get('avg_effective_discount_pct','?')}% discount versus a ~5% headline. "
            f"Recommended action: recover the over-claims now, cap per-invoice discounts, and redesign "
            f"{dud['name'] if dud else 'the weakest scheme'}.")
    return {"mode": mode, "health": f["health"], "narrative": narrative,
            "headline_at_risk": _rupees(f["overclaims"]["total_at_risk"])}


@app.post("/api/claim-check")
async def claim_check(file: UploadFile = File(...)):
    """Multimodal: read an uploaded claim/invoice image with Gemini Vision and
    reconcile the claimed amount against the engine's earned entitlement."""
    data = await file.read()
    # Browsers often send application/octet-stream; Gemini needs a real image MIME.
    mime = (file.content_type or "").lower()
    _name = (file.filename or "").lower()
    if not mime.startswith("image/"):
        if _name.endswith((".jpg", ".jpeg")): mime = "image/jpeg"
        elif _name.endswith(".webp"): mime = "image/webp"
        elif _name.endswith(".gif"): mime = "image/gif"
        else: mime = "image/png"
    prompt = ("You are a trade-promotion claims auditor. From this claim/invoice document, extract a JSON object with "
              "keys: partner_name (string), scheme_id (string or null), claimed_amount (number, no currency symbol). "
              "Return ONLY the JSON object, nothing else.")
    try:
        txt = _gemini(prompt, image_bytes=data, mime=mime)
    except Exception as e:
        return {"mode": "unavailable", "note": "Vision model not reachable for this project.", "error": str(e)[:160]}
    ext = {}
    try:
        m = re.search(r"\{.*\}", txt, re.S)
        ext = json.loads(m.group(0)) if m else {}
    except Exception:
        ext = {}
    claimed = ext.get("claimed_amount")
    sid = ext.get("scheme_id")
    pname = (ext.get("partner_name") or "").lower()
    oc = E.overclaims()
    match = None
    for r in oc["rows"]:
        if (sid and str(sid) == str(r["scheme_id"])) or (pname and pname in str(r["name"]).lower()):
            match = r; break
    if match:
        verdict = ("OVER-CLAIM" if (claimed or match["claimed_amount"]) > match["earned"] else "OK")
        note = (f"{match['name']} claimed {_rupees(match['claimed_amount'])} against scheme {match['scheme_id']} but "
                f"earned only {_rupees(match['earned'])} — {_rupees(match['gap'])} over entitlement. "
                f"→ Do this: hold this claim and recover the gap before payout."
                if verdict == "OVER-CLAIM" else
                f"{match['name']}'s claim matches earned entitlement — clear to pay.")
    else:
        verdict = "REVIEW"
        note = ("Extracted the claim but couldn't auto-match it to a known scheme/partner. "
                "→ Do this: reconcile manually against the entitlement table.")
    return {"mode": "llm", "extracted": ext, "verdict": verdict, "note": note}


@app.post("/chat")
async def chat(inp: ChatIn):
    user_id = "demo-user"
    session_id = inp.session_id or ("s-" + uuid.uuid4().hex[:8])
    answer = ""
    mode = "llm"
    E.set_default_window(inp.window)   # agent tools honour the selected timeline
    try:
        await session_service.create_session(app_name=APP, user_id=user_id, session_id=session_id)
    except Exception:
        pass
    try:
        msg = types.Content(role="user", parts=[types.Part(text=inp.message)])
        async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=msg):
            if event.is_final_response() and event.content and event.content.parts:
                answer = "".join((p.text or "") for p in event.content.parts)
    except Exception:
        answer = ""
    if not answer.strip():
        answer = deterministic_answer(inp.message, inp.window)
        mode = "engine"
    return {"session_id": session_id, "answer": answer, "mode": mode}
