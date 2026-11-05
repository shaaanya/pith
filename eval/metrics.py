"""Pure metric helpers for the evaluation harness (stdlib only, no I/O, no models)."""
import math
import random
import re
import statistics


def unique(items):
    """`items` without repeats, keeping the first occurrence of each."""
    return list(dict.fromkeys(items))


def recall_at_k(ranked, relevant, k):
    """Fraction of `relevant` ids found in the first k of `ranked`."""
    return len(set(ranked[:k]) & set(relevant)) / len(relevant)


def reciprocal_rank(ranked, relevant):
    """1/rank of the first relevant id in `ranked` (1-based), 0.0 when absent."""
    return next((1 / (i + 1) for i, r in enumerate(ranked) if r in relevant), 0.0)


def wilson(k, n, z=1.96):
    """95% Wilson score interval for k successes in n trials."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def bootstrap_ci(values, *, iters=2000, seed=0, alpha=0.05):
    """Percentile bootstrap CI of the mean (deterministic for a seed)."""
    if not values:
        return 0.0, 0.0
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(rng.choices(values, k=n)) / n for _ in range(iters))
    return means[int(alpha / 2 * iters)], means[int((1 - alpha / 2) * iters) - 1]


def _norm(text):
    return re.sub(r"\s+", " ", text).strip().casefold()


def fact_found(fact, texts, *, loose=False):
    """Matching rule. exact: the case/whitespace-normalised fact is a substring of ONE item's
    text. loose: every \\w+ token of the fact occurs in ONE item's text (order and punctuation
    ignored)."""
    if loose:
        want = set(re.findall(r"\w+", fact.casefold()))
        return any(want <= set(re.findall(r"\w+", t.casefold())) for t in texts)
    return any(_norm(fact) in _norm(t) for t in texts)


def summarize(values):
    """n / min / median / max of a list of floats."""
    if not values:
        return {"n": 0, "min": None, "median": None, "max": None}
    return {"n": len(values), "min": min(values), "median": statistics.median(values),
            "max": max(values)}


def precision_recall(scores, positive, lower, upper=None):
    """Precision (None when nothing is predicted) and recall of 'lower <= score < upper' against
    the boolean `positive` labels."""
    pred = [lower <= s and (upper is None or s < upper) for s in scores]
    tp = sum(p and y for p, y in zip(pred, positive))
    npred, npos = sum(pred), sum(positive)
    return (tp / npred if npred else None), (tp / npos if npos else 0.0)
