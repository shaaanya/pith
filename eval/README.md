# Evaluation harness

Reproducible measurement of retrieval, dedupe and extraction against REAL local models. Results are
written next to the harness. Not collected by pytest
(`tests/test_eval_metrics.py` only tests the helpers and the dataset's sanity).

    uv run python eval/run_eval.py            # needs Ollama + qwen2.5:0.5b + nomic-embed-text already pulled

Writes `eval/results/<UTC date>-<chat model>.json` (everything, incl. per-query rankings and per-run
extraction records) and a `.md` summary. Uses a temporary home; it asserts `~/Pith` is untouched.

## Dataset composition (`eval/data/`)

All text is written for this evaluation: no copyrighted text, no scraped data, no personal data. People,
places, organisations and products are fictional.

- `retrieval.json`: 64 short documents (2 sentences each) in 8 topics (astronomy, cooking, personal
  finance, cycling, gardening, databases/software, local history of a fictional town, home networking),
  8 per topic, so every document has 7 same-topic near-distractors. 64 queries, 16 per category, each with
  exactly one relevant document id:
  - `keyword`: shares content words with the document ("tyre pressure road bike").
  - `entity`: a rare proper name ("Alderwick Gran Fondo").
  - `numeric`: a number or date fact ("railway arrived 4 August 1862").
  - `paraphrase`: NO shared content word with its document (enforced by a test against the product's
    stopword list), e.g. "keeping money aside for unexpected job loss" for the emergency-fund document.
- `dedupe.json`: 120 labelled pairs, 40 per class. `duplicate` = 24 reworded (same facts, different
  sentences) + 16 same text wrapped in web boilerplate (header/footer/cookie lines). `related` = two
  different documents of the same topic (different facts), sampled with a fixed seed. `unrelated` = two
  documents from different topics. The texts are the retrieval documents (or rewrites of them), so
  the two sets are not independent.
- `extraction.json`: 12 realistic documents of 100-170 words (meeting notes, news item, recipe, how-to,
  release notes, e-mail, lecture notes, trip report, policy memo, FAQ, product review, incident report),
  each with 5-7 facts that must appear (names, numbers, dates; each is a verbatim phrase of the
  document, asserted by a test).

## Shelf placement (`eval/notes/run_placement_eval.py`)

`uv run python eval/notes/run_placement_eval.py --model gemma4:e4b` scores shelf placement on the 36 labelled
notes in `eval/notes/placement_cases.json` (every shelf, no-reason notes, reason vs site disagreements, and
cases where the content type would mislead). Strategies: rules only, model only, model with the rule's
suggestion, and that with a rule overriding the model's "other". On gemma4:e4b: rules 81%, all model
strategies 94%, so `place.decide` uses the model with rules as the fallback. Results are in
`eval/notes/results/`.
