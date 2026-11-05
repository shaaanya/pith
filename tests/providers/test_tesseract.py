import shutil
from pathlib import Path

import pytest

from infoparser.providers.ports import ProviderError
from infoparser.providers.registry import Registry
from infoparser.providers.tesseract import TesseractBackend

IMG = Path(__file__).parent.parent / "fixtures" / "ocr_text.png"  # real render of "Hello Sourdough World"
needs_tess = pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract binary not installed")


@needs_tess
def test_tesseract_reads_fixture_image():
    b = TesseractBackend("t")
    assert b.capabilities.ocr and b.locality == "local"
    assert "sourdough" in b.read(IMG).lower()


def test_tesseract_missing_binary_and_file(tmp_path):
    with pytest.raises(ProviderError):
        TesseractBackend("t", binary="/no/such/tesseract").read(IMG)
    if shutil.which("tesseract"):
        with pytest.raises(ProviderError):
            TesseractBackend("t").read(tmp_path / "missing.png")


@needs_tess
def test_image_end_to_end_through_ocr_backend(svc, drain):
    svc.cfg.backends = {"tess": {"type": "tesseract"}}
    svc.cfg.tasks = {"ocr": ["tess"]}
    svc.registry = Registry.from_config(svc.cfg)
    iid = svc.inbox.submit(adapter="t", file=IMG.read_bytes(), filename="shot.png").id
    drain(svc)
    assert svc.inbox.get(iid)["status"] == "processed"
    text = " ".join(r[0] for r in svc.conn.execute("SELECT text FROM segments")).lower()
    assert "sourdough" in text and "hello" in text
