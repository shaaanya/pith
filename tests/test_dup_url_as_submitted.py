"""A duplicate URL submission is logged in provenance_log exactly as submitted."""


def test_duplicate_url_provenance_records_url_as_submitted(svc):
    """Canonical form is only the dedupe key; provenance_log keeps the URL as the user sent it."""
    first = svc.inbox.submit(adapter="t", text="https://example.com/p/?utm_source=x")
    again = "http://www.Example.com/p"
    dup = svc.inbox.submit(adapter="t", text=f"  {again}\n")
    assert dup.duplicate_of == first.id
    urls = [r["url"] for r in svc.conn.execute("SELECT url FROM provenance_log").fetchall()]
    assert urls == [again]
