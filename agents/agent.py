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
from google.adk.agents import Agent

MODEL = os.environ.get("PROMOLENS_MODEL", "gemini-2.0-flash")

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

# ---------------- specialist agents ----------------
analyst = Agent(
    name="scheme_analyst", model=MODEL,
    description="Answers performance questions: which schemes worked, ROI, stacking, cannibalisation.",
    instruction=("You analyse trade-promotion performance. Use rank_schemes_by_roi/scheme_roi for ROI, "
                 "stacked_effective_discount for true discount after stacking, cannibalisation for cross-SKU "
                 "impact. Always cite the numbers the tools return; never invent figures. Be concise."),
    tools=[rank_schemes_by_roi, scheme_roi, stacked_effective_discount, cannibalisation],
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
    description="Recommends future scheme parameters and runs what-if payout/ROI projections.",
    instruction=("You design future schemes. Use whatif_simulator to project payout and ROI before launch. "
                 "Give clear guidance on slab %, target and risk. Be concise."),
    tools=[whatif_simulator],
)

# ---------------- orchestrator (root) ----------------
root_agent = Agent(
    name="promolens_orchestrator", model=MODEL,
    description="PromoLens AI — trade promotion intelligence copilot for manufacturers.",
    instruction=(
        "You are PromoLens AI, a trade-promotion intelligence copilot. Route each question to the right "
        "specialist: scheme_analyst (performance/ROI/stacking/cannibalisation), leakage_integrity_auditor "
        "(over-claims, inventory-loading leaks, 'did the scheme apply', data/sync trust), scheme_designer "
        "(what-if / future scheme recommendations). Synthesise a concise, decision-ready answer with the "
        "concrete numbers the tools return. All data is synthetic. Never fabricate figures."),
    sub_agents=[analyst, auditor, designer],
)
