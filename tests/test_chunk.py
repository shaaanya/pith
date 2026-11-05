from infoparser.pipeline.chunk import chunk_text, chunk_timed
from infoparser.providers.ports import TimedText


def test_chunk_splits_on_headings_and_respects_max():
    text = "# A\n" + "alpha beta. " * 20 + "\n\n# B\n" + "gamma delta. " * 20 + "\n\n" + "x" * 500
    chunks = chunk_text(text, max_chars=300, overlap=30)
    assert all(len(t) <= 300 for t, _ in chunks)
    assert any(t.startswith("# B") for t, _ in chunks)  # heading starts a new chunk
    for t, loc in chunks:  # locator points at the chunk text
        a, b = map(int, loc.removeprefix("char=").split("-"))
        assert text[a:b].strip() == t
    assert chunk_text("") == []


def test_chunk_timed_locators():
    items = [TimedText(0, 5, "a" * 50), TimedText(5, 10.5, "b" * 50), TimedText(10.5, 20, "c" * 50)]
    out = chunk_timed(items, max_chars=110)
    assert [loc for _, loc in out] == ["t=0-10.5", "t=10.5-20"]
    assert out[0][0] == "a" * 50 + " " + "b" * 50
