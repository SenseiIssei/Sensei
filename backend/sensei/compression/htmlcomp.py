"""HTML pages: the readable content, not the markup around it.

A fetched page is mostly ``<script>``, ``<style>``, navigation and attribute
soup. This keeps the title, headings, paragraphs, list items, table cells,
code blocks and link targets of the main content, as plain text with light
Markdown, using only the standard library's HTML parser.

Main content: when the page has ``<main>`` or ``<article>``, only that is
kept; otherwise ``<nav>``, ``<header>``, ``<footer>``, ``<aside>`` and
``<form>`` are dropped. Scripts, styles, SVG and comments always go. All of
it is a cut, so the result carries a marker with the CCR id.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from sensei.compression.markers import Context

_SKIP = {"script", "style", "noscript", "svg", "template", "iframe", "canvas", "head"}
_CHROME = {"nav", "header", "footer", "aside", "form", "dialog"}
_BLOCK = {
    "p", "div", "section", "article", "main", "br", "tr", "table", "ul", "ol", "dl",
    "blockquote", "figure", "figcaption", "hr", "body", "html",
}  # fmt: skip
_HEADINGS = {"h1": "# ", "h2": "## ", "h3": "### ", "h4": "#### ", "h5": "##### ", "h6": "###### "}
_VOID = {
    "br",
    "hr",
    "img",
    "input",
    "meta",
    "link",
    "area",
    "base",
    "col",
    "embed",
    "source",
    "wbr",
}


def detect(text: str) -> bool:
    head = text[:3000].lower()
    if head.lstrip().startswith(("<!doctype html", "<html")):
        return True
    tags = len(re.findall(r"<(?:div|span|p|a|li|td|script|meta|link)\b", head))
    return tags >= 15 and head.count("<") > len(head) / 60


class _Extractor(HTMLParser):
    def __init__(self, main_only: bool) -> None:
        super().__init__(convert_charrefs=True)
        self.main_only = main_only
        self.skip = 0
        self.chrome = 0
        self.main = 0
        self.pre = 0
        self.title = ""
        self.in_title = False
        self.parts: list[str] = []
        self.href: str | None = None
        self.link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID:
            if tag == "br":
                self._emit("\n")
            return
        if tag == "title":
            self.in_title = True
        if tag in _SKIP:
            self.skip += 1
            return
        if tag in ("main", "article"):
            self.main += 1
        if tag in _CHROME:
            self.chrome += 1
        if tag == "pre":
            self.pre += 1
            self._emit("\n```\n")
        elif tag in _HEADINGS:
            self._emit("\n\n" + _HEADINGS[tag])
        elif tag == "li":
            self._emit("\n- ")
        elif tag in ("td", "th"):
            self._emit(" | ")
        elif tag in _BLOCK:
            self._emit("\n\n")
        elif tag == "a":
            href = dict(attrs).get("href") or ""
            if href.startswith(("http://", "https://", "/")) and not href.startswith("//"):
                self.href = href
                self.link_text = []
        elif tag == "code" and not self.pre:
            self._emit("`")

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID:
            return
        if tag == "title":
            self.in_title = False
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if tag in ("main", "article"):
            self.main = max(0, self.main - 1)
        if tag in _CHROME:
            self.chrome = max(0, self.chrome - 1)
        if tag == "pre":
            self.pre = max(0, self.pre - 1)
            self._emit("\n```\n")
        elif tag == "a" and self.href is not None:
            text = "".join(self.link_text).strip()
            if text and self.href not in text:
                self._emit(f" ({self.href})")
            self.href = None
        elif tag == "code" and not self.pre:
            self._emit("`")
        elif tag in _HEADINGS or tag in _BLOCK:
            self._emit("\n")

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title += data
        if self.skip:
            return
        if not self.pre:
            data = re.sub(r"\s+", " ", data)
        if self.href is not None:
            self.link_text.append(data)
        self._emit(data)

    def _emit(self, s: str) -> None:
        if self.skip:
            return
        if self.main_only and not self.main:
            return
        if not self.main_only and self.chrome:
            return
        self.parts.append(s)


def extract(html: str) -> str:
    lower = html.lower()
    main_only = "<main" in lower or "<article" in lower
    p = _Extractor(main_only)
    try:
        p.feed(html)
        p.close()
    except Exception:
        return html
    body = "".join(p.parts)
    if main_only and len(body.strip()) < 200:
        p = _Extractor(False)
        p.feed(html)
        p.close()
        body = "".join(p.parts)
    body = re.sub(r"(?<![ \t])[ \t]++\n", "\n", body)
    body = re.sub(r"\n[ \t]+", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    title = " ".join(p.title.split())
    return (f"# {title}\n\n" if title and title not in body[:300] else "") + body


class HTMLCompressor:
    def compress(self, text: str, ctx: Context | None = None) -> str:
        ctx = ctx or Context()
        body = extract(text)
        if not body or len(body) >= len(text):
            return text
        return (
            body
            + "\n"
            + ctx.mark(f"HTML markup, scripts and page chrome removed from {len(text):,} chars")
        )
