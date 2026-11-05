"""Stdlib main-content extraction (no trafilatura dependency; ponytail: heuristic, upgrade to trafilatura if quality matters)."""
from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin

_VOID = {"br", "img", "hr", "input", "meta", "link", "source", "wbr", "area", "base", "col", "embed", "track"}
_DROP = {"nav", "header", "footer", "aside", "script", "style", "form", "noscript", "svg", "iframe", "template"}
_JUNK_TOKENS = {"ad", "ads", "advert", "advertisement", "sponsored", "promo", "cookie", "cookies", "banner",
                "newsletter", "sidebar", "share", "social", "popup", "modal"}
_BLOCK = {"p", "div", "section", "article", "main", "li", "ul", "ol", "tr", "table", "blockquote", "pre",
          "figure", "figcaption", "dd", "dt", "dl"}
_HEADING = {f"h{i}": "#" * i for i in range(1, 7)}


class _Node:
    __slots__ = ("tag", "attrs", "kids", "parent")

    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.kids, self.parent = tag, attrs, [], parent


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = self.cur = _Node("#root", {}, None)
        self.title = ""
        self.meta: dict[str, str] = {}
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            k = (a.get("name") or a.get("property") or "").lower()
            if k and a.get("content"):
                self.meta.setdefault(k, a["content"].strip())
        n = _Node(tag, a, self.cur)
        self.cur.kids.append(n)
        if tag == "title":
            self._in_title = True
        if tag not in _VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        self.cur.kids.append(data)


def _junk(n: _Node) -> bool:
    if n.tag in _DROP or "hidden" in n.attrs or n.attrs.get("aria-hidden") == "true":
        return True
    toks = re.split(r"[\s_-]+", f"{n.attrs.get('class') or ''} {n.attrs.get('id') or ''}".lower())
    return any(t in _JUNK_TOKENS for t in toks)


def _render(n: _Node, out: list[str], links: list[tuple[str, str]] | None, base: str) -> None:
    for k in n.kids:
        if isinstance(k, str):
            out.append(re.sub(r"\s+", " ", k))
            continue
        if _junk(k):
            continue
        if k.tag in _HEADING:
            out.append(f"\n\n{_HEADING[k.tag]} ")
            inner: list[str] = []
            _render(k, inner, links, base)
            out.append(re.sub(r"\s+", " ", "".join(inner)).strip() + "\n\n")
        elif k.tag == "br":
            out.append("\n")
        else:
            if k.tag == "li":
                out.append("\n- ")
            elif k.tag in _BLOCK:
                out.append("\n\n")
            start = len(out)
            _render(k, out, links, base)
            if k.tag == "a" and links is not None and k.attrs.get("href", "").strip():
                href = k.attrs["href"].strip()
                if not href.startswith(("#", "javascript:", "mailto:")):
                    label = re.sub(r"\s+", " ", "".join(out[start:])).strip()
                    links.append((label, urljoin(base, href)))
            if k.tag in _BLOCK:
                out.append("\n\n")


def _clean(parts: list[str]) -> str:
    t = "".join(parts)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n[ \t]+", "\n", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return re.sub(r"(?m)^(- )\n+(?=- )", r"\1", t).strip()


def _text_of(n: _Node) -> tuple[int, int]:
    """(total chars, link chars) of visible text under n."""
    tot = lnk = 0
    for k in n.kids:
        if isinstance(k, str):
            tot += len(k.strip())
        elif not _junk(k):
            t, l = _text_of(k)
            tot += t
            lnk += t if k.tag == "a" else l
    return tot, lnk


def _walk(n: _Node):
    for k in n.kids:
        if isinstance(k, _Node):
            if _junk(k):
                continue
            yield k
            yield from _walk(k)


def extract_main(html: str, base_url: str) -> tuple[str, str, list[tuple[str, str]], dict]:
    b = _Builder()
    b.feed(html)
    b.close()
    cands = [(n, *_text_of(n)) for n in _walk(b.root) if n.tag in ("article", "main", "div", "section", "body")]
    best = None
    sem = [c for c in cands if c[0].tag in ("article", "main") and c[1] >= 200]
    if sem:
        best = max(sem, key=lambda c: c[1])[0]
    else:
        scored = [(t * (1 - l / t), n) for n, t, l in cands if t >= 80]
        scored = [(s, n) for s, n in scored if s > 0]
        # prefer the densest smaller container over <body> unless nothing else qualifies
        inner = [x for x in scored if x[1].tag != "body"]
        pick = inner or scored
        best = max(pick, key=lambda x: x[0])[1] if pick else b.root
    out: list[str] = []
    links: list[tuple[str, str]] = []
    _render(best, out, links, base_url)
    h1 = next((n for n in _walk(best) if n.tag == "h1"), None)
    title = re.sub(r"\s+", " ", b.title).strip() or b.meta.get("og:title", "")
    if not title and h1:
        tmp: list[str] = []
        _render(h1, tmp, None, base_url)
        title = re.sub(r"\s+", " ", "".join(tmp)).strip()
    meta = {"author": b.meta.get("author") or b.meta.get("article:author"),
            "published": b.meta.get("article:published_time"), "description": b.meta.get("description")}
    return title, _clean(out), links, {k: v for k, v in meta.items() if v}
