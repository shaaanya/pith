import json
from pathlib import Path

from infoparser.pipeline import runner
from infoparser.retrieval.search import search
from stubs.concept_embedder import ConceptEmbedder

FIX = Path(__file__).parent / "fixtures"


def build(svc, use_embedder):
    use_embedder(svc, ConceptEmbedder())
    for f in sorted((FIX / "corpus").glob("*.md")):
        runner.process(svc, svc.inbox.submit(adapter="t", file=f.read_bytes(), filename=f.name).id)


def doc_of(svc, hit):
    return svc.conn.execute("SELECT original_filename FROM inbox_items WHERE source_id=?", (hit.source_id,)).fetchone()[0]


def evaluate(svc, mode):
    qs = json.loads((FIX / "queries.json").read_text())
    hit5, rr = 0, 0.0
    for q in qs:
        docs = []
        for h in search(svc, q["q"], limit=10, filters=None, mode=mode):
            d = doc_of(svc, h)
            if d not in docs:
                docs.append(d)
        if q["doc"] in docs[:5]:
            hit5 += 1
        if q["doc"] in docs:
            rr += 1 / (docs.index(q["doc"]) + 1)
    return hit5 / len(qs), rr / len(qs)


def test_retrieval_quality_thresholds(svc, use_embedder):
    build(svc, use_embedder)
    fts_r, fts_mrr = evaluate(svc, "fts")
    hyb_r, hyb_mrr = evaluate(svc, "hybrid")
    print(f"\nrecall@5 fts={fts_r:.2f} hybrid={hyb_r:.2f}  MRR fts={fts_mrr:.2f} hybrid={hyb_mrr:.2f}")
    assert fts_r >= 0.6 and hyb_r >= 0.85 and hyb_r > fts_r
