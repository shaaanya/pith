"""OCR via the tesseract CLI (`tesseract <img> stdout -l <lang>`). Verified locally (real binary
in tests).

Spec keys: type = "tesseract"; binary (default "tesseract"); lang (default "eng"); timeout
(seconds, 120).
"""
from pathlib import Path

from .ports import Capabilities, run_cli


class TesseractBackend:
    """OCR backend that shells out to tesseract."""

    locality = "local"
    capabilities = Capabilities(ocr=True)

    def __init__(self, name, binary="tesseract", lang="eng", timeout=120):
        self.name, self.binary, self.lang, self.timeout = name, binary, lang, timeout

    @classmethod
    def from_spec(cls, name, spec):
        """Build from a `[backends.<name>]` spec."""
        return cls(name, spec.get("binary", "tesseract"), spec.get("lang", "eng"),
                   spec.get("timeout", 120))

    def read(self, image: Path) -> str:
        """OCR text of the image; ProviderError on failure or timeout."""
        argv = [self.binary, str(image), "stdout", "-l", self.lang]
        return run_cli(self.name, argv, self.timeout).stdout.strip()
