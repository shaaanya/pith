"""Static guards on the single-file UI (no browser in CI): no HTML-injection sinks, null-safe rendering."""
import re
from pathlib import Path

HTML = (Path(__file__).parent.parent / "src/infoparser/dashboard/static/index.html").read_text()
JS = re.search(r'<script nonce="\{\{nonce\}\}">(.*)</script>', HTML, re.S).group(1)


def test_no_html_injection_sinks():
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "srcdoc"):
        assert sink not in JS, sink
    assert not re.search(r"https?://(?!\\)", HTML.replace("https?://", "")), "no external URLs in the page"
    assert "<link" not in HTML and "src=" not in HTML.replace('script nonce', "")


def test_raw_append_and_replace_only_inside_render_helpers():
    # Element.append stringifies null ("null" shows up on screen): everything goes through put()/clear()
    lines = [ln.strip() for ln in JS.splitlines() if re.search(r"\.(append|replaceChildren|prepend)\(", ln)]
    assert len(lines) == 2, lines
    assert any(ln.startswith("parent.append(") for ln in lines) and any("parent.replaceChildren()" in ln for ln in lines)


def test_put_helper_skips_null_and_false():
    m = re.search(r"function put\(.*?\n}\n", JS, re.S).group(0)
    assert "!= null" in m and "!== false" in m


def test_clarify_textarea_placeholder_says_pasted_text_replaces_content():
    from pathlib import Path
    html = (Path(__file__).parent.parent / "src/infoparser/dashboard/static/index.html").read_text()
    assert "replaces the content" in html
