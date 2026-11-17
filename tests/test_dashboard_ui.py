"""Static guards on the built single-file UI (no browser in CI).

The page is now a React build (frontend/). The bundle legitimately contains React's own DOM code, so the
HTML-sink rule is enforced where we control it: on the frontend SOURCE (also by ESLint), while the
artifact is checked for the CSP-facing invariants the server depends on.
"""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
HTML = (ROOT / "src/pith/dashboard/static/index.html").read_text()
SRC = ROOT / "frontend/src"


def test_every_inline_tag_carries_the_nonce_placeholder():
    """The server swaps {{nonce}} per request; an un-nonced inline tag would be blocked by the CSP."""
    tags = re.findall(r"<(script|style)\b([^>]*)>", HTML)
    assert tags, "expected inline script and style"
    for name, attrs in tags:
        assert 'nonce="{{nonce}}"' in attrs, f"<{name}{attrs}> has no nonce"
        assert "src=" not in attrs, "no external script"


def test_no_external_resources_in_the_page():
    """connect/img/default are 'self'/'none': no links, no remote urls, no data: urls."""
    assert "<link" not in HTML
    assert not re.search(r"url\(\s*['\"]?(https?:|data:)", HTML)
    assert not re.search(r"""(src|href)=["']https?://""", HTML)


def test_frontend_source_has_no_html_injection_sinks():
    """Same rule as before, on the code we write (ESLint enforces it too)."""
    sinks = ("dangerouslySetInnerHTML", "innerHTML", "outerHTML", "insertAdjacentHTML",
             "document.write", "eval(", "new Function", "srcdoc")
    for f in SRC.rglob("*.ts*"):
        if f.name.endswith((".test.ts", ".test.tsx")):
            continue
        text = "\n".join(ln for ln in f.read_text().splitlines() if not ln.lstrip().startswith(("//", "*", "/*")))
        for sink in sinks:
            assert sink not in text, f"{sink} in {f.relative_to(ROOT)}"


def test_clarify_textarea_placeholder_says_pasted_text_replaces_content():
    """The clarify placeholder says pasted text replaces the content."""
    assert "replaces the content" in HTML
