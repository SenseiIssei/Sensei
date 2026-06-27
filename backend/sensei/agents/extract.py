"""Content extraction — clean "reader-mode" text from HTML, and text from PDFs.

``extract_main_text`` drops chrome (nav/header/footer/aside/scripts/forms) and
turns block boundaries into newlines so the remaining prose is clean for RAG.
``extract_pdf_text`` pulls text from a PDF (via pypdf), failing gracefully.
"""
from __future__ import annotations

import html as _html
import io
import re

_DROP_BLOCK = re.compile(
    r"<(script|style|noscript|nav|header|footer|aside|form|svg|button|iframe|template)\b[^>]*>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_BLOCK_END = re.compile(
    r"</(p|div|li|h[1-6]|section|article|tr|ul|ol|blockquote|pre)>", re.IGNORECASE
)
_TAG = re.compile(r"<[^>]+>")


def extract_main_text(body: str) -> str:
    body = _DROP_BLOCK.sub(" ", body)
    body = _COMMENT.sub(" ", body)
    body = _BR.sub("\n", body)
    body = _BLOCK_END.sub("\n", body)
    text = _TAG.sub(" ", body)
    text = _html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        parts = [(page.extract_text() or "").strip() for page in reader.pages]
        return "\n\n".join(p for p in parts if p)
    except Exception:
        return ""
