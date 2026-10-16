from __future__ import annotations

import re
from typing import ClassVar

# Line-comment markers per language. Unknown languages get none: `#` is a
# heading in Markdown, a colour in CSS and a preprocessor line in C, and `//`
# is half of every URL. Guessing wrong deletes real content.
_LINE_COMMENT: dict[str, str] = {
    "python": "#",
    "javascript": "//",
    "typescript": "//",
    "go": "//",
    "rust": "//",
    "java": "//",
    "cpp": "//",
}
_BLOCK_COMMENTS = {"javascript", "typescript", "go", "rust", "java", "cpp"}
# Quote characters that open a string literal, per language. Comment markers
# inside a literal are data: `"#16a34a"` and `"https://…"` must survive.
_QUOTES: dict[str, str] = {
    "python": "\"'",
    "javascript": "\"'`",
    "typescript": "\"'`",
    "go": '"`',
    "rust": '"',
    "java": '"',
    "cpp": '"',
}

_IMPORT_PREFIXES: dict[str, tuple[str, ...]] = {
    "python": ("import ", "from "),
    "javascript": ("import ",),
    "typescript": ("import ",),
    "go": ("import ",),
    "rust": ("use ",),
    "java": ("import ",),
    "cpp": ("#include",),
}

_TRIPLE = ('"""', "'''")

_DECISIVE: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("python", re.compile(r"^\s*(?:async\s+)?def \w+\(.*\)\s*(?:->.*)?:\s*$")),
    ("go", re.compile(r"^func (?:\(\w+ \*?\w+\) )?\w+\(")),
    ("rust", re.compile(r"^\s*(?:pub(?:\(\w+\))? )?(?:async )?fn \w+[<(]")),
    ("typescript", re.compile(r"^\s*(?:export )?(?:interface|type) \w+.*[={]\s*$")),
    ("javascript", re.compile(r"^\s*(?:export )?(?:async )?function\*?\s*\w*\s*\(")),
)


def _at_boundary(line: str, i: int) -> bool:
    """A `//` or `/*` only opens a comment at the start of a line or after
    whitespace. Elsewhere it is far more often code: a regex literal such as
    `url.replace(/^https?:\\/\\//, "")`, a glob, or a path."""
    return i == 0 or line[i - 1] in " \t"


def _scan(line: str, marker: str, quotes: str, block: bool, state: str) -> tuple[str, str]:
    """Remove comments from one line, carrying string/comment state across lines.

    ``state`` is ``""`` (code), ``"/*"`` (inside a block comment) or a quote
    character (inside a string that continues onto the next line — a JS
    template literal or a Go raw string). A single linear pass with a tiny
    state machine rather than a regex, because a regex cannot know whether
    ``#`` or ``//`` sits inside quotes, and linear is what untrusted input
    needs.
    """
    out: list[str] = []
    i = 0
    n = len(line)
    removed = False
    while i < n:
        if state == "/*":
            end = line.find("*/", i)
            removed = True
            if end < 0:
                return "".join(out), "/*"
            i = end + 2
            state = ""
            continue
        ch = line[i]
        if state:  # inside a string literal
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(line[i + 1])
                i += 2
                continue
            if ch == state:
                state = ""
            i += 1
            continue
        if ch in quotes:
            state = ch
            out.append(ch)
        elif block and line.startswith("/*", i) and _at_boundary(line, i):
            state = "/*"
            removed = True
            i += 2
            continue
        elif marker and line.startswith(marker, i) and (marker == "#" or _at_boundary(line, i)):
            removed = True
            break
        else:
            out.append(ch)
        i += 1
    # Only multi-line-capable quotes carry over; an unterminated `"` is a typo
    # or a language we misdetected, and must not swallow the rest of the file.
    if state and state != "`":
        state = ""
    text = "".join(out)
    return (text.rstrip() if removed else line), state


class CodeCompressor:
    """Semantics-preserving code compression for common languages.

    Removes what a compiler ignores — comments, docstrings, blank lines,
    trailing whitespace — and nothing it does not. String literals are never
    touched.

    Two modes:

    - ``safe`` (default): the above. The result means exactly what the input
      meant.
    - ``aggressive``: additionally folds long import blocks into a count. That
      deletes information, so it is opt-in.

    What this module cannot know is whether someone is about to *edit* the
    code by exact string match — Claude Code's Edit tool and Codex's
    apply_patch both do. That decision belongs to the gateway, which knows the
    text arrived as a tool result; see ``ContentRouter.compress(edit_target=)``.
    """

    LANG_PATTERNS: ClassVar[dict[str, list[str]]] = {
        "python": [
            r"^\s*(def |class |import |from .+ import)",
            r"^\s*(if __name__|@|print\()",
        ],
        "javascript": [
            r"^\s*(function |const |let |var |export |import )",
            r"=>\s*[{(]",
        ],
        "typescript": [
            r"^\s*(interface |type |enum |export |import )",
            r":\s*(string|number|boolean|void|any)\b",
        ],
        "go": [
            r"^\s*(package |func |import |type |struct )",
            r":=\s",
        ],
        "rust": [
            r"^\s*(fn |let mut|impl |pub |use |mod |struct |enum |trait )",
            r"->\s*\w+",
        ],
        "java": [
            r"^\s*(public |private |protected |class |interface |import )",
            r"void\s+\w+\s*\(",
        ],
        "cpp": [
            r"^\s*(#include|template|namespace|std::)",
            r"\b(int|void|float|double|char)\s+\w+\s*\(",
        ],
    }
    _COMPILED: ClassVar[dict[str, list[re.Pattern[str]]]] = {
        lang: [re.compile(p) for p in pats] for lang, pats in LANG_PATTERNS.items()
    }

    def __init__(self, mode: str = "safe") -> None:
        self.mode = mode

    def compress(self, code: str) -> str:
        """Compress code by removing comments, docstrings and blank lines."""
        if code.strip().startswith("```"):
            lines = code.strip().split("\n")
            lang_line = lines[0].strip("`").strip() if lines else ""
            has_close = len(lines) > 1 and lines[-1].strip() == "```"
            code_body = "\n".join(lines[1:-1] if has_close else lines[1:])
            lang = self._detect_language(lang_line, code_body)
            compressed = self._compress_code(code_body, lang)
            fence = lang_line or (lang if lang != "unknown" else "")
            return f"```{fence}\n{compressed}\n```"

        return self._compress_code(code, self._detect_language("", code))

    def _detect_language(self, hint: str, code: str) -> str:
        hint = hint.lower().strip()
        lang_map = {
            "py": "python",
            "python": "python",
            "js": "javascript",
            "jsx": "javascript",
            "javascript": "javascript",
            "ts": "typescript",
            "tsx": "typescript",
            "typescript": "typescript",
            "go": "go",
            "golang": "go",
            "rs": "rust",
            "rust": "rust",
            "java": "java",
            "kotlin": "java",
            "cpp": "cpp",
            "c++": "cpp",
            "c": "cpp",
            "cs": "java",
            "csharp": "java",
        }
        if hint in lang_map:
            return lang_map[hint]

        sample = code.split("\n")[:30]
        # One unambiguous line is enough — a short snippet holding a single
        # function is still clearly that language.
        for lang, pattern in _DECISIVE:
            if any(pattern.match(line) for line in sample):
                return lang
        for lang, patterns in self._COMPILED.items():
            matches = sum(1 for line in sample if any(p.search(line) for p in patterns))
            if matches >= 2:
                return lang
        return "unknown"

    def _compress_code(self, code: str, lang: str) -> str:
        lines = self._strip_comments(code.split("\n"), lang)
        lines = [line.rstrip() for line in lines if line.strip()]
        if self.mode == "aggressive":
            lines = self._collapse_imports(lines, lang)
        return "\n".join(lines)

    def _strip_comments(self, lines: list[str], lang: str) -> list[str]:
        marker = _LINE_COMMENT.get(lang, "")
        quotes = _QUOTES.get(lang, "\"'")
        block = lang in _BLOCK_COMMENTS
        result: list[str] = []
        state = ""
        # Python triple-quoted strings: a docstring (a statement on its own
        # line) is dropped; any other triple-quoted string is data and kept
        # verbatim, `#` and all.
        docstring = ""
        verbatim = ""

        for line in lines:
            if lang == "python":
                if docstring:
                    if docstring in line:
                        docstring = ""
                    continue
                if verbatim:
                    result.append(line)
                    if line.count(verbatim) % 2 == 1:
                        verbatim = ""
                    continue
                stripped = line.strip()
                opener = next((q for q in _TRIPLE if stripped.startswith(q)), "")
                # A docstring is the first statement of a module, class or
                # function. Anywhere else a line starting with """ is a string
                # argument or value — `textwrap.dedent(\n    """…` — and data.
                at_docstring_position = not result or result[-1].rstrip().endswith(":")
                if opener and at_docstring_position:
                    if stripped.count(opener) == 1:
                        docstring = opener
                    continue  # one-line or opening docstring
                triple = next((q for q in _TRIPLE if line.count(q) % 2 == 1), "")
                if triple:
                    head = line[: line.index(triple)]
                    result.append(_scan(head, marker, quotes, False, "")[0] + line[len(head) :])
                    verbatim = triple
                    continue

            if not marker and not block:
                # Language unknown: a line that *starts* with `//` is a comment
                # in every C-family language and is never a URL on its own.
                if line.lstrip().startswith("//"):
                    continue
                result.append(line)
                continue

            text, state = _scan(line, marker, quotes, block, state)
            if text.strip():
                result.append(text)

        return result

    def _collapse_imports(self, lines: list[str], lang: str) -> list[str]:
        """Fold long import blocks into a count. Lossy — aggressive mode only."""
        prefixes = _IMPORT_PREFIXES.get(lang, ())
        if not prefixes:
            return lines
        marker = _LINE_COMMENT.get(lang, "#")

        result: list[str] = []
        block: list[str] = []

        def flush() -> None:
            if len(block) > 3:
                result.extend(block[:2])
                result.append(f"{marker} … +{len(block) - 2} more imports")
            else:
                result.extend(block)
            block.clear()

        for line in lines:
            if any(line.strip().startswith(p) for p in prefixes):
                block.append(line.strip())
            else:
                flush()
                result.append(line)
        flush()
        return result
