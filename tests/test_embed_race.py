"""embed_pending/reindex never store a vector for text that changed while the embedder ran."""
import numpy as np
from stubs.hash_embedder import HashEmbedder

from pith.pipeline import runner
from pith.retrieval import index, vectors
from pith.store import knowledge

TEXT = "Retrieval augmented generation combines search with generation.\n\nChunking matters."


class _Editing(HashEmbedder):  # pylint: disable=too-few-public-methods  # test double
    """Edits the first item (as the dashboard would) while the first real batch is in flight."""

    def __init__(self, svc):
        super().__init__()
        self.svc, self.fired = svc, False

    def embed(self, texts):
        """Embed; on the first batch of real text, edit an item behind the caller's back."""
        if texts != ["."] and not self.fired:
            self.fired = True
            row = self.svc.conn.execute(
                "SELECT id FROM knowledge_items WHERE deleted_at IS NULL LIMIT 1").fetchone()
            knowledge.update_item(self.svc.conn, row["id"], body="completely different words now")
        return super().embed(texts)


def _vector_text_matches(svc):
    """True when every stored item vector equals the embedding of the item's current text."""
    emb = HashEmbedder()
    for r in svc.conn.execute(
            "SELECT id, title, body FROM knowledge_items WHERE deleted_at IS NULL"):
        stored = svc.conn.execute("SELECT count(*) FROM embeddings WHERE owner_type='item'"
                                  " AND owner_id=?", (r["id"],)).fetchone()[0]
        if stored:
            want = emb.embed([r["title"] + "\n" + r["body"]]).vectors[0]
            ids, mat = vectors.load(svc.conn, emb.model_id, "item")
            got = mat[ids.index(r["id"])]
            cos = got @ np.array(want) / (np.linalg.norm(got) * np.linalg.norm(want))
            if cos < 0.9999:
                return False
    return True


def test_embed_pending_drops_vectors_of_text_edited_meanwhile(svc, use_embedder):
    """The edit invalidated the vector; the next embed_pending refills it for the new text."""
    runner.process(svc, svc.inbox.submit(adapter="t", text=TEXT).id)
    svc.conn.execute("DELETE FROM embeddings")
    use_embedder(svc, _Editing(svc))
    index.embed_pending(svc)
    assert _vector_text_matches(svc)
    use_embedder(svc, HashEmbedder())
    index.embed_pending(svc)
    assert _vector_text_matches(svc)


def test_reindex_drops_vectors_of_text_edited_meanwhile(svc, use_embedder):
    """Same guarantee for a full reindex."""
    runner.process(svc, svc.inbox.submit(adapter="t", text=TEXT).id)
    use_embedder(svc, _Editing(svc))
    index.reindex(svc)
    assert _vector_text_matches(svc)
