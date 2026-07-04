"""
PromoLens AI — Scheme-document RAG with citations
=================================================
Answers plain-English questions about scheme *terms* ("what does scheme X
entitle?", "what's the claim window?") grounded in the scheme circulars in
data/scheme_docs, and RETURNS CITATIONS (scheme id + clause) so answers are
auditable — never invented.

Primary path : Vertex AI Search (Discovery Engine) datastore, if
               PROMOLENS_SEARCH_DATASTORE is set. This is the managed
               enterprise-search path (Gen App Builder / Vertex AI Search).
Fallback path: deterministic lexical retrieval over the same local documents,
               chunked by clause — so the copilot always cites a real clause,
               even with no cloud. Mirrors the vertex->lexical fallback in
               semantic.py. Every result carries mode = "vertex_search" | "local".

Conflict handling: if a scheme has an amended circular (…-R2), the revised one
supersedes the original; the answer cites the CURRENT clause and flags the
older conflicting version (the planted M8-style test from the AI Sales Engine POC).
"""
import os, re, math, glob

HERE = os.path.dirname(__file__)
DOCS = os.path.join(HERE, "..", "data", "scheme_docs")

_WORD = re.compile(r"[a-z0-9%\-]+")
def _tokens(t): return [w for w in _WORD.findall(t.lower()) if len(w) > 1]

def _chunks():
    """Split every circular into (scheme_id, revision, clause_title, text) chunks."""
    out = []
    for path in sorted(glob.glob(os.path.join(DOCS, "*.md"))):
        fn = os.path.basename(path)[:-3]           # e.g. SCHBLD001-R2
        base = fn.split("-R")[0]
        rev = int(fn.split("-R")[1]) if "-R" in fn else 1
        txt = open(path, encoding="utf-8").read()
        # split on level-2 headings
        parts = re.split(r"\n##\s+", txt)
        header = parts[0]
        title_m = re.search(r"Scheme Circular:\s*(.+)", header)
        title = title_m.group(1).strip() if title_m else base
        for part in parts[1:]:
            line0, _, body = part.partition("\n")
            out.append(dict(scheme_id=base, revision=rev, doc_id=fn, scheme_title=title,
                            clause=line0.strip(), text=(line0 + "\n" + body).strip()))
    return out

_INDEX = None
def _build():
    global _INDEX
    ch = _chunks()
    vocab = {}
    for c in ch:
        for w in set(_tokens(c["text"])):
            vocab.setdefault(w, len(vocab))
    for c in ch:
        v = [0.0] * len(vocab)
        for w in _tokens(c["text"]):
            v[vocab[w]] += 1.0
        c["_vec"] = v
    _INDEX = dict(chunks=ch, vocab=vocab)
    return _INDEX

def _cos(a, b):
    dot = sum(x*y for x, y in zip(a, b)); na = math.sqrt(sum(x*x for x in a)); nb = math.sqrt(sum(y*y for y in b))
    return dot/(na*nb) if na and nb else 0.0

_INTENT = [
    (("claim","window","process","recover","settle","raise"), "5. Claim"),
    (("eligib","tier","who","partner","qualify","account"),    "1. Eligibility"),
    (("payout","growth","slab","incentive","percent","%","free","earn","rate"), "3. Incentive"),
    (("product","sku","scope","applicable","cover"),            "2. Scope"),
    (("baseline","measure","sell-out","uplift"),                "4. Baseline"),
    (("budget","cap","discount","limit"),                       "6. Budget"),
]
def _intent_clause(query):
    q = query.lower()
    for kws, clause in _INTENT:
        if any(kw in q for kw in kws):
            return clause
    return None

def _local_search(query, k=4):
    idx = _INDEX or _build()
    qtoks = _tokens(query)
    qv = [0.0]*len(idx["vocab"])
    for w in qtoks:
        if w in idx["vocab"]:
            qv[idx["vocab"][w]] += 1.0
    intent = _intent_clause(query)
    qset = set(qtoks)
    scored = []
    for c in idx["chunks"]:
        s = _cos(qv, c["_vec"])
        # clause-intent boost: strongly prefer the clause the user is asking about
        if intent and c["clause"].startswith(intent):
            s += 0.6
        # scheme relevance boost: query words matching the scheme title/SKUs
        title_overlap = len(qset & set(_tokens(c["scheme_title"]))) 
        s += 0.15 * title_overlap
        if s > 0:
            scored.append((s, c))
    scored.sort(key=lambda x: -x[0])
    return scored[:k]

def _vertex_search(query, k=4):
    """Vertex AI Search (Discovery Engine) — managed enterprise search over the
    ingested scheme circulars. Returns (score, chunk-like dict) list or raises."""
    from google.cloud import discoveryengine_v1 as de
    project = os.environ.get("PROMOLENS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
    location = os.environ.get("PROMOLENS_SEARCH_LOCATION", "global")
    datastore = os.environ["PROMOLENS_SEARCH_DATASTORE"]  # data store ID
    serving = (f"projects/{project}/locations/{location}/collections/default_collection/"
               f"dataStores/{datastore}/servingConfigs/default_config")
    client = de.SearchServiceClient()
    req = de.SearchRequest(
        serving_config=serving, query=query, page_size=k,
        content_search_spec=de.SearchRequest.ContentSearchSpec(
            summary_spec=de.SearchRequest.ContentSearchSpec.SummarySpec(summary_result_count=k),
            snippet_spec=de.SearchRequest.ContentSearchSpec.SnippetSpec(return_snippet=True)))
    resp = client.search(req)
    out = []
    for i, r in enumerate(resp.results):
        d = r.document
        struct = dict(d.derived_struct_data) if d.derived_struct_data else {}
        title = struct.get("title") or d.id
        snippet = ""
        snips = struct.get("snippets") or []
        if snips:
            snippet = snips[0].get("snippet", "")
        out.append((1.0 - i*0.1, dict(scheme_id=str(title).split("-R")[0], doc_id=str(title),
                    scheme_title=str(title), clause="(matched passage)", text=snippet or str(title),
                    revision=(2 if "-R2" in str(title) else 1))))
    # attach the model summary if present
    _vertex_search.last_summary = getattr(resp.summary, "summary_text", "") if resp.summary else ""
    return out

def answer_scheme_question(query, k=4):
    """Grounded answer to a scheme-terms question, with citations to the exact
    clause(s). Uses Vertex AI Search when configured, else local retrieval."""
    mode = "local"; summary = ""
    hits = []
    if os.environ.get("PROMOLENS_SEARCH_DATASTORE"):
        try:
            hits = _vertex_search(query, k); mode = "vertex_search"
            summary = getattr(_vertex_search, "last_summary", "")
        except Exception:
            hits = []
    if not hits:
        hits = _local_search(query, k); mode = "local"
    if not hits:
        return dict(mode=mode, query=query, answer="No scheme circular matches that question yet.",
                    citations=[], conflict=None)
    # conflict / supersession: same base scheme appearing with revision > 1
    by_scheme = {}
    for s, c in hits:
        by_scheme.setdefault(c["scheme_id"], []).append(c)
    conflict = None
    top_sid = hits[0][1]["scheme_id"]
    cs = by_scheme.get(top_sid, [])
    revs = sorted({c["revision"] for c in cs})
    if len(revs) > 1:
        conflict = dict(scheme_id=top_sid, current_revision=max(revs),
                        note=(f"Scheme {top_sid} has an amended circular (R{max(revs)}) that supersedes the "
                              f"original — the current terms below are cited; the older version is out of date."))
    # prefer highest-revision chunk of the top scheme
    top_score, top = hits[0]
    same = [c for s, c in hits if c["scheme_id"] == top["scheme_id"]]
    if same:
        top = max(same, key=lambda c: c["revision"])
    citations = []
    seen = set()
    for s, c in hits:
        key = (c["doc_id"], c["clause"])
        if key in seen:
            continue
        seen.add(key)
        citations.append(dict(scheme_id=c["scheme_id"], doc_id=c["doc_id"],
                              scheme=c["scheme_title"], clause=c["clause"],
                              excerpt=c["text"][:280]))
    answer = summary or (f"{top['scheme_title']} — {top['clause']}: " + top["text"].split("\n", 1)[-1].strip()[:400])
    return dict(mode=mode, query=query, answer=answer.strip(), citations=citations[:k], conflict=conflict)
