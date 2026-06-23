from __future__ import annotations

import re
from typing import Literal


class CodeCompressor:
    """AST-aware code compression for multiple languages.

    Inspired by Headroom's CodeCompressor — strips comments, whitespace,
    and boilerplate while preserving semantics. Supports Python, JS/TS,
    Go, Rust, Java, C++.

    Uses regex-based heuristics rather than full AST parsing for speed
    and zero-dependency operation. Falls back gracefully for unknown languages.
    """

    # Language detection patterns
    LANG_PATTERNS = {
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

    def compress(self, code: str) -> str:
        """Compress code by removing comments, extra whitespace, and boilerplate."""
        # Extract code from markdown fences if present
        fenced = False
        if code.strip().startswith("```"):
            lines = code.strip().split("\n")
            lang_line = lines[0].strip("`").strip() if lines else ""
            code_body = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            fenced = True
            lang = self._detect_language(lang_line, code_body)
        else:
            lang = self._detect_language("", code)

        compressed = self._compress_code(code, lang)

        if fenced:
            return f"```{lang}\n{compressed}\n```"
        return compressed

    def _detect_language(self, hint: str, code: str) -> str:
        """Detect the programming language of a code block."""
        hint = hint.lower().strip()
        lang_map = {
            "py": "python", "python": "python",
            "js": "javascript", "javascript": "javascript",
            "ts": "typescript", "typescript": "typescript",
            "go": "go", "golang": "go",
            "rs": "rust", "rust": "rust",
            "java": "java",
            "cpp": "cpp", "c++": "cpp", "c": "cpp",
        }
        if hint in lang_map:
            return lang_map[hint]

        # Auto-detect from patterns
        for lang, patterns in self.LANG_PATTERNS.items():
            matches = sum(
                1 for line in code.split("\n")[:30]
                if any(re.search(p, line) for p in patterns)
            )
            if matches >= 2:
                return lang

        return "unknown"

    def _compress_code(self, code: str, lang: str) -> str:
        """Apply compression steps based on language."""
        lines = code.split("\n")

        # Step 1: Remove comments
        lines = self._strip_comments(lines, lang)

        # Step 2: Remove blank lines
        lines = [line for line in lines if line.strip()]

        # Step 3: Remove trailing whitespace
        lines = [line.rstrip() for line in lines]

        # Step 4: Collapse multi-line imports/declarations
        lines = self._collapse_imports(lines, lang)

        # Step 5: Remove docstrings (Python) / JSDoc
        lines = self._strip_docstrings(lines, lang)

        return "\n".join(lines)

    def _strip_comments(self, lines: list[str], lang: str) -> list[str]:
        """Remove single-line and multi-line comments."""
        comment_patterns = {
            "python": r"#.*$",
            "javascript": r"//.*$",
            "typescript": r"//.*$",
            "go": r"//.*$",
            "rust": r"//.*$",
            "java": r"//.*$",
            "cpp": r"//.*$",
        }

        pattern = comment_patterns.get(lang, r"(#|//).*$")
        result = []
        in_block_comment = False

        for line in lines:
            # Handle block comments /* ... */
            if "/*" in line and "*/" in line:
                line = re.sub(r"/\*.*?\*/", "", line)
            elif "/*" in line:
                in_block_comment = True
                line = line[: line.index("/*")]
            elif "*/" in line and in_block_comment:
                in_block_comment = False
                line = line[line.index("*/") + 2 :]
            elif in_block_comment:
                continue

            # Handle Python triple-quoted strings used as comments
            if lang == "python":
                stripped = line.strip()
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    if stripped.count('"""') == 2 or stripped.count("'''") == 2:
                        continue  # Single-line docstring
                    # Multi-line — skip until closing
                    continue

            # Remove single-line comments
            line = re.sub(pattern, "", line)
            if line.strip():
                result.append(line)

        return result

    def _collapse_imports(self, lines: list[str], lang: str) -> list[str]:
        """Collapse consecutive import statements."""
        import_prefixes = {
            "python": ("import ", "from "),
            "javascript": ("import ", "const ", "require("),
            "typescript": ("import ", "const ", "require("),
            "go": ("import ", "package "),
            "rust": ("use ", "mod "),
            "java": ("import "),
            "cpp": ("#include", "#define"),
        }

        prefixes = import_prefixes.get(lang, ())
        if not prefixes:
            return lines

        result = []
        import_block: list[str] = []

        for line in lines:
            stripped = line.strip()
            if any(stripped.startswith(p) for p in prefixes):
                import_block.append(stripped)
            else:
                if import_block:
                    # Collapse imports into a single line if there are many
                    if len(import_block) > 3:
                        result.append(f"# {len(import_block)} imports collapsed")
                        result.extend(import_block[:2])
                        result.append(f"# ... +{len(import_block) - 2} more")
                    else:
                        result.extend(import_block)
                    import_block = []
                result.append(line)

        if import_block:
            if len(import_block) > 3:
                result.append(f"# {len(import_block)} imports collapsed")
                result.extend(import_block[:2])
                result.append(f"# ... +{len(import_block) - 2} more")
            else:
                result.extend(import_block)

        return result

    def _strip_docstrings(self, lines: list[str], lang: str) -> list[str]:
        """Remove docstring markers (lightweight, since main stripping happens in comments)."""
        if lang not in ("python", "javascript", "typescript"):
            return lines

        result = []
        for line in lines:
            stripped = line.strip()
            # Skip lines that are just docstring markers
            if stripped in ('"""', "'''", "/**", "*/", "*"):
                continue
            # Strip JSDoc * prefix
            if stripped.startswith("* ") and lang in ("javascript", "typescript"):
                continue
            result.append(line)

        return result
