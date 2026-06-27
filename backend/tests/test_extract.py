from __future__ import annotations

from sensei.agents.extract import extract_main_text, extract_pdf_text


def test_extract_drops_chrome_keeps_content():
    html = """
    <html><head><style>.x{color:red}</style></head><body>
      <nav><a href="/">Home</a><a href="/about">About</a></nav>
      <header>Site Title</header>
      <article><h1>Real Title</h1><p>The main content paragraph one.</p>
      <p>And paragraph two here.</p></article>
      <footer>copyright 2026</footer>
      <script>track();</script>
    </body></html>
    """
    text = extract_main_text(html)
    assert "Real Title" in text
    assert "main content paragraph one" in text
    # Chrome / scripts are gone.
    assert "track()" not in text
    assert "copyright" not in text
    assert "About" not in text


def test_extract_block_boundaries_become_newlines():
    text = extract_main_text("<p>one</p><p>two</p><li>three</li>")
    assert text.split("\n")[0].strip() == "one"
    assert "two" in text and "three" in text


def test_pdf_extract_graceful_on_garbage():
    assert extract_pdf_text(b"not a real pdf") == ""
    assert extract_pdf_text(b"") == ""
