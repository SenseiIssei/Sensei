"""Characters you pay for and nobody can see.

A zero-width space is one token. So is a byte-order mark, a word joiner, a
soft hyphen. They arrive by the hundred when code is pasted out of a web
interface, a wiki or a chat window, and they survive every compressor here
because none of them looks at individual characters — a measured 40% token
overhead on source that carries one per line.

Removing them is exactly what this project is for: they cost money and carry no
information. Two of them additionally carry risk.

## Not every invisible character is noise

The tempting version of this strips everything non-printing and corrupts real
text. Three distinctions are load-bearing:

**Zero-width joiner and non-joiner** are structural in Devanagari, Persian and
Arabic, and they are what holds a multi-person emoji together — remove them and
a family emoji becomes three separate people. They are meaningless in source
code and nowhere else, so they are stripped only from content the router
classified as code.

**Bidi overrides and isolates** are the Trojan Source vector (CVE-2021-42574):
they let source render in one order and compile in another, so a reviewer reads
`if (isAdmin)` where the compiler reads the opposite. Those come out
everywhere. Left- and right-to-left *marks* are ordinary punctuation in Hebrew
and Arabic prose and stay.

**Non-breaking space and homoglyphs** are reported, never rewritten. A Cyrillic
`a` in an identifier is almost always an attack or a paste accident, but
"almost always" is not a licence to edit somebody's text — and an NBSP is
deliberate in typeset prose. Counting them puts the decision in front of a
human instead of making it silently.

The original is in the CCR store either way, byte-identical, retrievable by id.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Specified by code point, so this file contains no non-ASCII at all.
#
# Not a style preference. A module whose job is to remove Trojan Source vectors
# must not itself contain any, and ruff's `bidirectional-unicode` rule refuses
# them outright. Escapes would satisfy the linter, but several tools in this
# pipeline normalise an escape back into the character on write -- which is how
# the first version of this file ended up carrying the very bytes it exists to
# delete. A code point cannot be silently rewritten into something invisible.

# No semantic role in any script. Pure cost.
ALWAYS_STRIP = "".join(
    map(
        chr,
        (
            0x200B,  # ZERO WIDTH SPACE
            0xFEFF,  # ZERO WIDTH NO-BREAK SPACE / BOM, when not the first byte
            0x2060,  # WORD JOINER
            0x00AD,  # SOFT HYPHEN
            0x2061,  # FUNCTION APPLICATION
            0x2062,  # INVISIBLE TIMES
            0x2063,  # INVISIBLE SEPARATOR
            0x2064,  # INVISIBLE PLUS
            0x180E,  # MONGOLIAN VOWEL SEPARATOR
        ),
    )
)

# The Unicode tag block, and the deprecated language tag that heads it.
#
# These render as absolutely nothing — not a thin space, nothing — and each one
# maps to an ASCII character, so a whole readable instruction can be written in
# them and pasted into a document that looks innocent. That is the technique
# usually called ASCII smuggling, and it is a prompt-injection channel rather
# than a curiosity: a gateway whose job is forwarding text to a model is exactly
# the place it would arrive, and the human reviewing the text cannot see it.
#
# Deprecated since Unicode 5.1 for everything except emoji subdivision flags,
# and those cannot be told apart by code point: England is U+1F3F4 followed by
# the tag letters g, b, e, n, g and a cancel tag — the same lowercase letters a
# hidden sentence is written in. The first attempt here excluded the lowercase
# range to protect flags, which left the whole readable alphabet unfiltered and
# made the feature useless for the case it exists for.
#
# So the split is by context, not by code point: a tag run that follows the flag
# base and ends in a cancel tag is a flag and stays; every other tag character
# goes. See `_SMUGGLED_RE`.
TAG_CHARACTERS = "".join(map(chr, [0xE0001, *range(0xE0020, 0xE0080)]))

# Variation selectors, minus the two that do visible work.
#
# The rest carry no meaning of their own and are the other well-known place to
# hide a payload — a byte per selector, invisible, surviving copy and paste.
#
# U+FE0E and U+FE0F are excluded on purpose: they choose between the text and
# emoji presentation of the preceding character, so removing U+FE0F turns a
# rendered emoji back into a dingbat. That is the same class of mistake as
# stripping a zero-width joiner out of a family emoji.
VARIATION_SELECTORS = "".join(map(chr, [*range(0xFE00, 0xFE0E), *range(0xE0100, 0xE01F0)]))

# Meaningful in Indic, Persian and Arabic text, and in emoji sequences. Stripped
# from source code, where they cannot mean anything, and left alone elsewhere.
CODE_ONLY_STRIP = "".join(
    map(
        chr,
        (
            0x200C,  # ZERO WIDTH NON-JOINER
            0x200D,  # ZERO WIDTH JOINER
        ),
    )
)

# Trojan Source. Overrides and isolates change rendering order without changing
# the bytes a compiler sees; there is no legitimate use for them in a payload
# being sent to a language model.
#
# U+200E and U+200F (LEFT-TO-RIGHT MARK, RIGHT-TO-LEFT MARK) are deliberately
# absent: they are ordinary punctuation in bidirectional prose.
BIDI_CONTROLS = "".join(
    map(
        chr,
        (
            0x202A,  # LEFT-TO-RIGHT EMBEDDING
            0x202B,  # RIGHT-TO-LEFT EMBEDDING
            0x202C,  # POP DIRECTIONAL FORMATTING
            0x202D,  # LEFT-TO-RIGHT OVERRIDE
            0x202E,  # RIGHT-TO-LEFT OVERRIDE
            0x2066,  # LEFT-TO-RIGHT ISOLATE
            0x2067,  # RIGHT-TO-LEFT ISOLATE
            0x2068,  # FIRST STRONG ISOLATE
            0x2069,  # POP DIRECTIONAL ISOLATE
        ),
    )
)

# Reported, not rewritten.
NBSP = "".join(
    map(
        chr,
        (
            0x00A0,  # NO-BREAK SPACE
            0x202F,  # NARROW NO-BREAK SPACE
            0x2007,  # FIGURE SPACE
        ),
    )
)

_ALWAYS_RE = re.compile(f"[{ALWAYS_STRIP}]")
_CODE_RE = re.compile(f"[{ALWAYS_STRIP}{CODE_ONLY_STRIP}]")
_BIDI_RE = re.compile(f"[{BIDI_CONTROLS}]")
# Alternation, not a plain character class: the first branch matches a whole
# emoji subdivision flag and is put back untouched, the second matches a single
# smuggled character and is dropped. Ordering matters — the flag has to be
# recognised before its tag letters are seen individually.
_SMUGGLED_RE = re.compile(
    "(\U0001f3f4[\U000e0020-\U000e007e]{1,6}\U000e007f)"
    f"|([{TAG_CHARACTERS}{VARIATION_SELECTORS}])"
)
_NBSP_RE = re.compile(f"[{NBSP}]")

# An identifier-ish run containing both Latin and non-Latin letters. A word
# spelled with a Cyrillic "a" reads as its Latin twin and is a different name.
_WORDLIKE_RE = re.compile(r"[^\W\d_]{2,}", re.UNICODE)


@dataclass
class Findings:
    """What was removed, and what was only noticed."""

    invisible: int = 0
    bidi: int = 0
    # Tag characters and variation selectors. Counted apart from `invisible`
    # because finding one is a different kind of news: the others are usually a
    # paste artefact, while a tag character is somebody encoding readable text
    # in a form the reader cannot see.
    smuggled: int = 0
    nbsp: int = 0
    mixed_script_words: list[str] = field(default_factory=list)

    @property
    def removed(self) -> int:
        return self.invisible + self.bidi + self.smuggled

    @property
    def anything(self) -> bool:
        return bool(self.removed or self.nbsp or self.mixed_script_words)

    def as_dict(self) -> dict[str, object]:
        return {
            "invisible_removed": self.invisible,
            "bidi_removed": self.bidi,
            "smuggled_removed": self.smuggled,
            "nbsp_seen": self.nbsp,
            # Capped: a payload full of transliterated text would otherwise put
            # thousands of words into a response nobody reads.
            "mixed_script_words": self.mixed_script_words[:10],
        }


def _script(char: str) -> str:
    """Coarse script bucket, from the character's Unicode name."""
    try:
        name = unicodedata.name(char)
    except ValueError:
        return "?"
    return name.split(" ")[0]


def _mixed_script_words(text: str, limit: int = 50) -> list[str]:
    """Words mixing Latin with another alphabet — the homoglyph signature.

    Deliberately not a confusables table. The point is to surface "this
    identifier is not what it looks like" cheaply, and a word written in two
    alphabets at once is that, whichever characters were used.
    """
    found: list[str] = []
    for match in _WORDLIKE_RE.finditer(text):
        word = match.group()
        if word.isascii():
            continue
        scripts = {_script(c) for c in word if c.isalpha()}
        if "LATIN" in scripts and len(scripts) > 1:
            found.append(word)
            if len(found) >= limit:
                break
    return found


def scan(text: str) -> Findings:
    """Report without changing anything."""
    return Findings(
        invisible=len(_CODE_RE.findall(text)),
        bidi=len(_BIDI_RE.findall(text)),
        nbsp=len(_NBSP_RE.findall(text)),
        mixed_script_words=_mixed_script_words(text),
    )


def clean(text: str, *, is_code: bool = False, strip_nbsp: bool = False) -> tuple[str, Findings]:
    """Remove the characters that cost tokens and mean nothing.

    Returns the cleaned text and what was found. `is_code` widens the set to
    the joiners, which are structural in several writing systems but cannot
    mean anything in source.
    """
    if not text:
        return text, Findings()

    # Every character this function looks for lives above U+007F: the zero-width
    # set, the bidi controls, the no-break spaces, and homoglyphs by definition —
    # a Cyrillic `a` that passes for a Latin one is not ASCII. So pure-ASCII text
    # cannot contain a single one, and all the work below is guaranteed to find
    # nothing.
    #
    # Worth an early exit because that is the normal case — logs, source, English
    # prose — and because the work is not cheap: four regex passes plus a
    # per-word script check over the whole input. Measured on 880KB of log
    # output, this function was 43.65ms of a 47ms compression, and `isascii()`
    # is a C-level scan that does not register at 0.001ms resolution.
    if text.isascii():
        return text, Findings()

    pattern = _CODE_RE if is_code else _ALWAYS_RE
    findings = Findings(
        invisible=len(pattern.findall(text)),
        bidi=len(_BIDI_RE.findall(text)),
        smuggled=sum(1 for m in _SMUGGLED_RE.finditer(text) if m.group(2)),
        nbsp=len(_NBSP_RE.findall(text)),
        mixed_script_words=_mixed_script_words(text),
    )

    if findings.invisible:
        text = pattern.sub("", text)
    if findings.bidi:
        text = _BIDI_RE.sub("", text)
    if findings.smuggled:
        # Keep group 1 (a flag), drop group 2 (everything else).
        text = _SMUGGLED_RE.sub(lambda m: m.group(1) or "", text)
    if strip_nbsp and findings.nbsp:
        # A plain space, not nothing: an NBSP is a space that was asked not to
        # break, and deleting it would join two words.
        text = _NBSP_RE.sub(" ", text)

    return text, findings
