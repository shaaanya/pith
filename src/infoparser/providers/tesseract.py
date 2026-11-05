"""OCR via the tesseract CLI (`tesseract <img> stdout -l <lang>`). Verified locally (real binary in tests).

Spec keys: type = "tesseract"; binary (default "tesseract"); lang (default "eng"); timeout (seconds, 120).
"""
import subprocess
from pathlib import Path

from .ports import Capabilities, ProviderError


class TesseractBackend:
    locality = "local"
    capabilities = Capabilities(ocr=True)

    def __init__(self, name, binary="tesseract", lang="eng", timeout=120):
        self.name, self.binary, self.lang, self.timeout = name, binary, lang, timeout

    @classmethod
    def from_spec(cls, name, spec):
        return cls(name, spec.get("binary", "tesseract"), spec.get("lang", "eng"), spec.get("timeout", 120))

    def read(self, image: Path) -> str:
        try:
            p = subprocess.run([self.binary, str(image), "stdout", "-l", self.lang],
                               capture_output=True, text=True, timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ProviderError(f"{self.name}: {e}") from e
        if p.returncode != 0:
            raise ProviderError(f"{self.name}: exit {p.returncode}: {p.stderr.strip()[:300]}")
        return p.stdout.strip()
