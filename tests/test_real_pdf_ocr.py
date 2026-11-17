"""REAL binaries (pdftotext, tesseract, ffmpeg, pdftoppm) on documents generated at test time.

Genuine external evidence, not stubs: skipped cleanly when a binary is missing. The pypdf branch
is checked in tests/optional/pypdf_checks.py (needs `uv run --with pypdf`).
"""
import pytest
from realtools import ffmpeg, image_pdf, make_pdf, needs, pdf_page_png

from pith.pipeline import runner
from pith.pipeline.extractors import pdf
from pith.providers.registry import Registry
from pith.providers.tesseract import TesseractBackend
from pith.worker import NeedsClarification, Processed

PAGES = [["Hello Sourdough World", "second line here"], ["Page two Fermentation notes"],
         ["Third page starter hydration"]]


def _submit(svc, name, data):
    return svc.inbox.submit(adapter="t", file=data, filename=name).id


def _segments(svc):
    return [(r["locator"], r["text"]) for r in svc.conn.execute(
        "SELECT locator, text FROM segments ORDER BY id")]


def _ocr(svc):
    svc.cfg.backends = {"tess": {"type": "tesseract"}}
    svc.cfg.tasks = {"ocr": ["tess"]}
    svc.registry = Registry.from_config(svc.cfg)


@needs("pdftotext")
def test_pdftotext_path_on_real_multipage_pdf(svc, monkeypatch):
    """pypdf forced absent: the real pdftotext yields one locator per page with the exact text."""
    monkeypatch.setattr(pdf, "_pypdf_pages", lambda p: None)
    iid = _submit(svc, "doc.pdf", make_pdf(PAGES))
    assert isinstance(runner.process(svc, iid), Processed)
    assert _segments(svc) == [
        ("page=1", "Hello Sourdough World\nsecond line here"),
        ("page=2", "Page two Fermentation notes"), ("page=3", "Third page starter hydration")]
    assert svc.inbox.get(iid)["content_type"] == "pdf"


@needs("pdftotext", "pdftoppm", "ffmpeg")
def test_pdf_without_text_layer_asks_for_pasted_text(svc, tmp_path, monkeypatch):
    """A scanned (image-only) PDF: documented behaviour is needs_clarification, no OCR for PDFs."""
    monkeypatch.setattr(pdf, "_pypdf_pages", lambda p: None)
    page = tmp_path / "page.pdf"
    page.write_bytes(make_pdf([PAGES[0]]))
    scan = image_pdf(pdf_page_png(page, tmp_path / "p.png"), tmp_path / "scan.pdf")
    out = runner.process(svc, _submit(svc, "scan.pdf", scan.read_bytes()))
    assert isinstance(out, NeedsClarification) and "no text layer" in out.reason
    assert "OCR for PDFs is not supported" in out.reason


@pytest.fixture(name="png")
def png_fixture(tmp_path):
    """A rendered page: 'Hello Sourdough World / second line here' (36pt, 150 dpi)."""
    src = tmp_path / "t.pdf"
    src.write_bytes(make_pdf([PAGES[0]]))
    return pdf_page_png(src, tmp_path / "plain.png")


def _variant(png, name, vf):
    out = png.with_name(name)
    ffmpeg("-i", png, "-vf", vf, "-update", "1", out)
    return out


@needs("tesseract", "pdftoppm", "ffmpeg")
def test_tesseract_reads_rendered_text_exactly(png):
    """Clean render: the recognised text is exactly what was drawn."""
    assert TesseractBackend("t").read(png) == "Hello Sourdough World\nsecond line here"


@needs("tesseract", "pdftoppm", "ffmpeg")
@pytest.mark.parametrize("name,vf", [
    ("rot90.png", "transpose=1"),  # page rotated a quarter turn: tesseract's orientation detection
    ("lowcontrast.png", "eq=contrast=0.08:brightness=0.4"),  # pale grey on near-white
])
def test_tesseract_rotated_and_low_contrast_still_recognised(png, name, vf):
    """Measured with tesseract 5.5.2: both are still read correctly (report, not a guarantee)."""
    assert "sourdough world" in TesseractBackend("t").read(_variant(png, name, vf)).lower()


@needs("tesseract", "pdftoppm", "ffmpeg")
def test_tesseract_tilted_text_degrades(png):
    """Characterisation: 10 degree tilt garbles the text and 30 degrees yields (almost) nothing.

    There is no deskew step; this documents the limit. If a newer tesseract reads these, the
    assertions below flip and the docs should be revised, not the test silently loosened."""
    tess = TesseractBackend("t")
    assert "sourdough world" not in tess.read(
        _variant(png, "tilt10.png", "rotate=0.1745:fillcolor=white:ow=iw:oh=ih")).lower()
    assert "sourdough world" not in tess.read(
        _variant(png, "tilt30.png", "rotate=0.5236:fillcolor=white:ow=iw:oh=ih")).lower()


@needs("tesseract", "pdftoppm", "ffmpeg")
def test_image_item_ocr_end_to_end_and_blank_image(svc, png, tmp_path):
    """Image item through the real registry+tesseract; a blank image asks for clarification."""
    _ocr(svc)
    assert isinstance(runner.process(svc, _submit(svc, "shot.png", png.read_bytes())), Processed)
    assert "sourdough world" in " ".join(t for _, t in _segments(svc)).lower()
    blank = tmp_path / "blank.png"
    ffmpeg("-f", "lavfi", "-i", "color=c=white:s=200x100:d=1", "-frames:v", "1", blank)
    out = runner.process(svc, _submit(svc, "blank.png", blank.read_bytes()))
    assert isinstance(out, NeedsClarification) and "no text found" in out.reason
