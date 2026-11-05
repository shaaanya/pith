RRF_K = 60


def rrf(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """Reciprocal rank fusion: score(d) = sum over lists of 1/(k + rank), rank from 1. Ties keep first-seen order."""
    score: dict[str, float] = {}
    for ranking in rankings:
        for rank, key in enumerate(dict.fromkeys(ranking), 1):
            score[key] = score.get(key, 0.0) + 1.0 / (k + rank)
    return sorted(score.items(), key=lambda kv: -kv[1])
