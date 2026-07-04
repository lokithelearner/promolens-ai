"""
PromoLens AI — Semantic scheme search (Vertex AI Vector Search)
================================================================
Powers the Scheme Designer: "find past schemes like X" via vector similarity.

Primary path : embed every historical scheme with Vertex AI text embeddings
               (text-embedding-005), embed the query the same way, rank by
               cosine similarity. Embeddings are cached to disk so we embed
               the corpus once.

Fallback path : if Vertex embeddings are unavailable (no creds / quota / region),
                fall back to a deterministic lexical (TF) cosine over the same
                documents — so the Designer never breaks in a demo. This mirrors
                the Gemini -> deterministic-engine fallback used elsewhere.

Every result carries a `mode` flag ("vertex" or "lexical") so callers can be
transparent about which path produced the answer.
"""
import os, json, math, re
from engine.tools import T  # reuse the already-loaded tables (CSV or BigQuery)

_EMBED_MODEL = os.environ.get("PROMOLENS_EMBED_MODEL", "text-embedding-005")
_EMBED_LOCATION = os.environ.get("PROMOLENS_EMBED_LOCATION",
                                 os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
_CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "scheme_embeddings.json")

_INDEX = None  # built lazily: {"mode","ids","meta","docs","vectors"}


# ---------------------------------------------------------------- corpus
def _scheme_documents():
    """Turn each scheme row into a short natural-language document + metadata."""
    s = T["schemes_master"]
    docs, ids, meta = [], [], []
    for _, r in s.iterrows():
        try:
            skus = ", ".join(json.loads(r["sku_scope"])) if isinstance(r["sku_scope"], str) else str(r["sku_scope"])
        except Exception:
            skus = str(r.get("sku_scope", ""))
        text = (f"{r['name']}. {r['archetype']} scheme, {r['mode']} mode, "
                f"{r['slab_type']} slab, incentive {r['incentive_type']}. "
                f"Region {r['region_scope']}, channel {r['channel_tier']}, "
                f"products {skus}. Status {r['status']}.")
        docs.append(text)
        ids.append(r["scheme_id"])
        meta.append(dict(scheme_id=r["scheme_id"], name=r["name"], archetype=r["archetype"],
                         mode=r["mode"], slab_type=r["slab_type"], region=r["region_scope"],
                         channel=r["channel_tier"], incentive=r["incentive_type"],
                         status=r["status"], skus=skus, industry=r.get("industry_id", "")))
    return ids, docs, meta


# ---------------------------------------------------------------- vertex embeddings
def _vertex_embed(texts):
    """Return a list of embedding vectors via Vertex AI, or raise on any failure."""
    import vertexai
    from vertexai.language_models import TextEmbeddingModel
    project = os.environ.get("PROMOLENS_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    vertexai.init(project=project, location=_EMBED_LOCATION)
    model = TextEmbeddingModel.from_pretrained(_EMBED_MODEL)
    out = []
    for i in range(0, len(texts), 50):  # batch
        for e in model.get_embeddings(texts[i:i + 50]):
            out.append(list(e.values))
    return out


# ---------------------------------------------------------------- lexical fallback
_WORD = re.compile(r"[a-z0-9\-]+")

def _tokens(text):
    return [w for w in _WORD.findall(text.lower()) if len(w) > 1]

def _lexical_vectors(docs):
    """Plain term-frequency vectors over a shared vocabulary (deterministic)."""
    vocab = {}
    tokenised = []
    for d in docs:
        toks = _tokens(d)
        tokenised.append(toks)
        for w in toks:
            vocab.setdefault(w, len(vocab))
    vecs = []
    for toks in tokenised:
        v = [0.0] * len(vocab)
        for w in toks:
            v[vocab[w]] += 1.0
        vecs.append(v)
    return vecs, vocab

def _lexical_query_vector(query, vocab):
    v = [0.0] * len(vocab)
    for w in _tokens(query):
        if w in vocab:
            v[vocab[w]] += 1.0
    return v


# ---------------------------------------------------------------- math
def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# ---------------------------------------------------------------- index build
def _build_index():
    global _INDEX
    ids, docs, meta = _scheme_documents()

    # 1) try cached vertex embeddings
    if os.path.exists(_CACHE):
        try:
            cached = json.load(open(_CACHE))
            if cached.get("ids") == ids and cached.get("model") == _EMBED_MODEL:
                _INDEX = dict(mode="vertex", ids=ids, meta=meta, docs=docs,
                              vectors=cached["vectors"], vocab=None)
                return _INDEX
        except Exception:
            pass

    # 2) try live vertex embeddings
    try:
        vectors = _vertex_embed(docs)
        try:
            json.dump({"model": _EMBED_MODEL, "ids": ids, "vectors": vectors}, open(_CACHE, "w"))
        except Exception:
            pass
        _INDEX = dict(mode="vertex", ids=ids, meta=meta, docs=docs, vectors=vectors, vocab=None)
        return _INDEX
    except Exception:
        pass

    # 3) deterministic lexical fallback
    vectors, vocab = _lexical_vectors(docs)
    _INDEX = dict(mode="lexical", ids=ids, meta=meta, docs=docs, vectors=vectors, vocab=vocab)
    return _INDEX


# ---------------------------------------------------------------- public API
def find_similar_schemes(query, k=3):
    """Semantic search over historical schemes. Returns top-k by cosine similarity.

    query : free-text description, e.g. "volume free-goods scheme on cement in Rajasthan"
    k     : number of matches to return
    """
    idx = _INDEX or _build_index()
    if idx["mode"] == "vertex":
        try:
            qv = _vertex_embed([query])[0]
        except Exception:
            # vertex went away mid-session -> rebuild as lexical
            ids, docs, meta = _scheme_documents()
            vectors, vocab = _lexical_vectors(docs)
            idx = dict(mode="lexical", ids=ids, meta=meta, docs=docs, vectors=vectors, vocab=vocab)
            globals()["_INDEX"] = idx
            qv = _lexical_query_vector(query, vocab)
    else:
        qv = _lexical_query_vector(query, idx["vocab"])

    scored = []
    for i, vec in enumerate(idx["vectors"]):
        s = _cosine(qv, vec)
        if s > 0:
            m = dict(idx["meta"][i]); m["score"] = round(s, 4)
            scored.append(m)
    scored.sort(key=lambda x: -x["score"])
    return dict(mode=idx["mode"], query=query, count=len(scored), matches=scored[:k])
