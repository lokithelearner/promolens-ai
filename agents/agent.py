"""
PromoLens AI — ADK multi-agent system.
Four agents (Orchestrator + Analyst + Leakage&Integrity Auditor + Designer),
each wrapping the *proven* deterministic tools in engine/tools.py.

The LLM (Gemini via Vertex AI) decides WHICH tool to call and narrates results;
the numbers come from auditable Python, not the model.
"""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from engine import tools as E
from engine import semantic as S
from engine import scheme_rag as R
from google.adk.agents import Agent

MODEL = os.environ.get("PROMOLENS_MODEL", "gemini-2.5-flash")

# ---------------- tool functions (thin JSON-friendly wrappers) ----------------
def rank_schemes_by_roi(industry: str = "BLD") -> dict:
    """Rank active schemes for an industry by ROI (incremental value net of outflow,
    vs a 12-month baseline). industry one of BLD, PHA, REN. Returns ranked list."""
    return {"schemes": E.rank_schemes_by_roi(industry)}

def scheme_roi(scheme_id: str) -> dict:
    """Detailed ROI, baseline, incremental value and outflow for one scheme_id."""
    return E.scheme_roi(scheme_id)

def why_not_applied(scheme_id: str = "") -> dict:
    """Explain scheme applications that were SKIPPED (did not apply to an invoice)
    and the exact reason. Optionally filter by scheme_id."""
    return {"skipped": E.why_not_applied(scheme_id or None, only_skips=True)}

def scheme_state_view() -> dict:
    """Lifecycle view: how many schemes are active / draft / expired."""
    return {"states": E.scheme_state_view()}

def inventory_loading_leaks() -> dict:
    """Flag partner x SKU combos with high sell-in but flat sell-out (inventory loading)."""
    return {"leaks": E.inventory_loading_leaks()}

def overclaims() -> dict:
    """Find claims that exceed the recomputed earned entitlement; returns at-risk total."""
    return E.overclaims()

def stacked_effective_discount() -> dict:
    """True effective discount % on putty SKUs once multiple schemes stack on an invoice."""
    return E.stacked_effective_discount()

def data_trust_summary() -> dict:
    """Master/invoice sync health: failure rate and top error reasons in plain English."""
    return E.data_trust_summary()

def cannibalisation(push_sku: str, victim_sku: str) -> dict:
    """Change in a victim SKU's sales while a push SKU is promoted (cannibalisation)."""
    return E.cannibalisation(push_sku, victim_sku)

def whatif_simulator(region: str, skus: str, slab_pct: float, expected_growth_pct: float) -> dict:
    """Project payout & ROI for a PROPOSED scheme before launch.
    skus = comma-separated sku codes."""
    return E.whatif_simulator(region, [s.strip() for s in skus.split(",")], slab_pct, expected_growth_pct)

def find_similar_schemes(query: str, k: int = 3) -> dict:
    """Semantic (vector) search over historical schemes using Vertex AI text
    embeddings. Use to retrieve past schemes similar to a free-text description
    (archetype, region, product, incentive) before recommending a new design."""
    return S.find_similar_schemes(query, k)

def next_best_scheme(industry: str = "BLD") -> dict:
    """PRESCRIPTIVE: the Next-Best-Scheme leaderboard — for each channel partner,
    the single best scheme to push next with expected Rs uplift and ROI. It is
    constraint-aware: partners loading inventory or with open over-claims are
    flagged to fix first, not offered more buy-more incentives. Use for
    'what should I do next / who should I push which scheme to'."""
    return E.nba_recommendations(industry)

def missed_opportunities(industry: str = "BLD") -> dict:
    """Find partner x SKU GAPS: partners who under-index on an in-scheme SKU vs
    same-tier peers, where an active scheme already covers it (with est Rs uplift).
    Use for 'where am I leaving money on the table / untapped opportunities'."""
    return E.missed_opportunities(industry)

def whatif_band(region: str, skus: str, slab_pct: float, expected_growth_pct: float) -> dict:
    """Pre-launch what-if with a confidence band (conservative/base/optimistic
    uptake) so downside risk is visible. skus = comma-separated codes."""
    return E.whatif_band(region, [s.strip() for s in skus.split(",")], slab_pct, expected_growth_pct)

def scheme_terms(query: str) -> dict:
    """Answer a question about a scheme's TERMS (payout %, claim window, eligibility,
    product scope) grounded in the scheme circulars, WITH CITATIONS to the exact
    clause. Flags when a revised circular supersedes an older one. Uses Vertex AI
    Search when configured, else local retrieval. Never invents terms."""
    return R.answer_scheme_question(query)

# ---------------- specialist agents ----------------
analyst = Agent(
    name="scheme_analyst", model=MODEL,
    description="Answers performance questions: which schemes worked, ROI, stacking, cannibalisation.",
    instruction=("You analyse trade-promotion performance. Use rank_schemes_by_roi/scheme_roi for ROI, "
                 "stacked_effective_discount for true discount after stacking, cannibalisation for cross-SKU "
                 "impact. For questions about a scheme's TERMS (payout %, claim window, eligibility, product "
                 "scope), call scheme_terms and repeat its answer WITH the clause citation it returns; if it "
                 "flags a superseding revision, say which version is current. Always cite the numbers the tools "
                 "return; never invent figures. Be concise."),
    tools=[rank_schemes_by_roi, scheme_roi, stacked_effective_discount, cannibalisation, scheme_terms],
)
auditor = Agent(
    name="leakage_integrity_auditor", model=MODEL,
    description="Catches bad payouts and bad data: over-claims, inventory-loading leaks, schemes that didn't apply, sync failures.",
    instruction=("You are a trade-spend integrity auditor. Use overclaims for claim-vs-entitlement gaps, "
                 "inventory_loading_leaks for sell-in/sell-out leakage, why_not_applied + scheme_state_view "
                 "for 'did the scheme apply' questions, data_trust_summary for master/sync health. "
                 "Quote partner IDs, amounts and reasons as evidence."),
    tools=[overclaims, inventory_loading_leaks, why_not_applied, scheme_state_view, data_trust_summary],
)
designer = Agent(
    name="scheme_designer", model=MODEL,
    description="Prescriptive: Next-Best-Scheme recommendations, missed-opportunity gaps, semantic search over past schemes, and what-if payout/ROI projections with a confidence band.",
    instruction=("You are the prescriptive engine. For 'what should I do next / who to push': call "
                 "next_best_scheme for the constraint-aware leaderboard (act on inventory-loading / over-claim "
                 "flags FIRST). For 'untapped upside / where am I leaving money': call missed_opportunities. "
                 "For a new design: find_similar_schemes for precedents, then whatif_band to show downside "
                 "risk. Always cite the Rs uplift and ROI the tools return; never invent figures. Be concise."),
    tools=[next_best_scheme, missed_opportunities, find_similar_schemes, whatif_simulator, whatif_band],
)

# ---------------- orchestrator (root) ----------------
root_agent = Agent(
    name="promolens_orchestrator", model=MODEL,
    description="PromoLens AI — trade promotion intelligence copilot for manufacturers.",
    instruction=(
        "You are PromoLens AI, a trade-promotion intelligence copilot. Route each question to the right "
        "specialist: scheme_analyst (performance/ROI/stacking/cannibalisation, and scheme-term lookups with "
        "citations), leakage_integrity_auditor (over-claims, inventory-loading leaks, 'did the scheme apply', "
        "data/sync trust), scheme_designer (PRESCRIPTIVE: Next-Best-Scheme recommendations, missed-opportunity "
        "gaps, what-if projections, future scheme design). Synthesise a concise, decision-ready answer with the "
        "concrete numbers the tools return. When an answer quotes scheme terms, include the clause citation. "
        "All data is synthetic. Never fabricate figures."),
    sub_agents=[analyst, auditor, designer],
)
