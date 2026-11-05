"""pypdf path of the PDF extractor, against the real pypdf and the real pdftotext.

Opt-in (the file name does not match `test_*.py`, so the default suite never collects it; pypdf
is deliberately not a dependency). Run:

    uv run --with pypdf pytest tests/optional/pypdf_checks.py -q
"""
import pytest
from realtools import image_pdf, make_pdf, needs, pdf_page_png

pypdf = pytest.importorskip("pypdf")

from infoparser.pipeline import runner  # noqa: E402  # pylint: disable=wrong-import-position
from infoparser.pipeline.extractors import pdf  # noqa: E402  # pylint: disable=wrong-import-position
from infoparser.worker import NeedsClarification, Processed  # noqa: E402  # pylint: disable=wrong-import-position

PAGES = [["Hello Sourdough World", "second line here"], ["Page two Fermentation notes"],
         ["Third page starter hydration"]]


def _segments(svc):
    return [(r["locator"], r["text"]) for r in svc.conn.execute(
        "SELECT locator, text FROM segments ORDER BY id")]


def test_pypdf_is_the_branch_that_runs(svc, monkeypatch):
    """pdftotext is made to explode: a Processed result proves pypdf produced the text."""
    def boom(_path):
        raise AssertionError("pdftotext branch must not run when pypdf is installed")
    monkeypatch.setattr(pdf, "_pdftotext_pages", boom)
    iid = svc.inbox.submit(adapter="t", file=make_pdf(PAGES), filename="d.pdf").id
    assert isinstance(runner.process(svc, iid), Processed)
    assert [loc for loc, _ in _segments(svc)] == ["page=1", "page=2", "page=3"]
    assert pdf.available()


@needs("pdftotext")
def test_pypdf_and_pdftotext_agree_on_text_and_locators(tmp_path):
    """Same PDF through both readers: same page count and the same text modulo whitespace."""
    path = tmp_path / "d.pdf"
    path.write_bytes(make_pdf(PAGES))
    via_pypdf, via_poppler = pdf._pypdf_pages(path), pdf._pdftotext_pages(path)  # pylint: disable=protected-access
    assert len(via_pypdf) == len(via_poppler) == 3
    assert [" ".join(p.split()) for p in via_pypdf] == [" ".join(p.split()) for p in via_poppler]
    assert " ".join(via_pypdf[0].split()) == "Hello Sourdough World second line here"


@needs("pdftoppm", "ffmpeg")
def test_pypdf_on_scanned_pdf_same_documented_behaviour(svc, tmp_path):
    """Image-only PDF: pypdf finds no text, so the item asks for pasted text (no OCR for PDFs)."""
    page = tmp_path / "page.pdf"
    page.write_bytes(make_pdf([PAGES[0]]))
    scan = image_pdf(pdf_page_png(page, tmp_path / "p.png"), tmp_path / "scan.pdf")
    iid = svc.inbox.submit(adapter="t", file=scan.read_bytes(), filename="scan.pdf").id
    out = runner.process(svc, iid)
    assert isinstance(out, NeedsClarification) and "no text layer" in out.reason
