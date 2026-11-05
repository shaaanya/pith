import io
import shutil
import zipfile

import pytest

from infoparser.pipeline import runner
from infoparser.pipeline.extractors import pdf
from infoparser.worker import Failed, NeedsClarification, Processed
from stubs.http_fixture_server import FIXTURES


def submit_file(svc, name, data=None):
    data = data if data is not None else (FIXTURES / name).read_bytes()
    return svc.inbox.submit(adapter="t", file=data, filename=name).id


def locs(svc):
    return [(r["locator"], r["text"]) for r in svc.conn.execute("SELECT locator, text FROM segments ORDER BY id")]


@pytest.mark.skipif(not pdf.available(), reason="neither pypdf nor pdftotext (poppler) is installed")
def test_pdf_pages_locators(svc):
    iid = submit_file(svc, "sample.pdf")
    assert isinstance(runner.process(svc, iid), Processed)
    got = locs(svc)
    assert [l for l, _ in got] == ["page=1", "page=2"]
    assert "retrieval augmented" in got[0][1] and "evaluation of chunking" in got[1][1]
    assert svc.inbox.get(iid)["content_type"] == "pdf"


def test_pdf_without_any_reader_needs_clarification(svc, monkeypatch):
    monkeypatch.setattr(pdf, "_pypdf_pages", lambda p: None)
    monkeypatch.setattr(shutil, "which", lambda n: None)
    out = runner.process(svc, submit_file(svc, "sample.pdf"))
    assert isinstance(out, NeedsClarification) and "pypdf" in out.reason and "pdftotext" in out.reason


@pytest.mark.skipif(not pdf.available(), reason="needs pypdf or pdftotext")
def test_corrupt_pdf_fails_original_kept(svc):
    iid = submit_file(svc, "bad.pdf", b"%PDF-1.4 not really")
    out = runner.process(svc, iid)
    assert isinstance(out, Failed)
    assert svc.blobs.exists(svc.inbox.get(iid)["blob_sha256"])


def test_docx_pptx_text(svc):
    iid = submit_file(svc, "sample.docx")
    assert isinstance(runner.process(svc, iid), Processed)
    text = "\n".join(t for _, t in locs(svc))
    assert "# Quarterly Plan" in text and "Ship the ingestion pipeline." in text
    assert svc.inbox.get(iid)["content_type"] == "document"
    iid = submit_file(svc, "sample.pptx")
    assert isinstance(runner.process(svc, iid), Processed)
    got = locs(svc)[-2:]
    assert [l for l, _ in got] == ["slide=1", "slide=2"]
    assert "Roadmap" in got[0][1] and "Model drift" in got[1][1]


def test_xlsx_text(svc):
    buf = io.BytesIO()
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{ns}"/>')
        z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{ns}"><si><t>Name</t></si><si><t>Widget</t></si></sst>')
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{ns}"><sheetData>'
                   '<row><c r="A1" t="s"><v>0</v></c><c r="B1" t="inlineStr"><is><t>Qty</t></is></c></row>'
                   '<row><c r="A2" t="s"><v>1</v></c><c r="B2"><v>42</v></c></row></sheetData></worksheet>')
    assert isinstance(runner.process(svc, submit_file(svc, "t.xlsx", buf.getvalue())), Processed)
    (loc, text), = locs(svc)
    assert loc == "sheet=1" and "Name\tQty" in text and "Widget\t42" in text


def test_office_zip_bomb_capped(svc):
    svc.cfg.max_fetch_bytes = 5_000
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", "<a>" + "x" * 1_000_000 + "</a>")
    out = runner.process(svc, submit_file(svc, "bomb.docx", buf.getvalue()))
    assert isinstance(out, (Failed, NeedsClarification))


def test_image_without_ocr_needs_clarification(svc):
    iid = submit_file(svc, "text_image.png")
    out = runner.process(svc, iid)
    assert isinstance(out, NeedsClarification) and "no OCR backend; install tesseract" in out.reason
    assert svc.blobs.exists(svc.inbox.get(iid)["blob_sha256"])


def test_image_with_ocr_backend(svc, monkeypatch):
    class FakeOCR:
        def read(self, image):
            assert image.exists()
            return "Invoice total 42 dollars"
    monkeypatch.setattr(svc.registry, "first", lambda task: FakeOCR() if task == "ocr" else None)
    iid = submit_file(svc, "text_image.png")
    assert isinstance(runner.process(svc, iid), Processed)
    assert "Invoice total 42" in locs(svc)[0][1]
