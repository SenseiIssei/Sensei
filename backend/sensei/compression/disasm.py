"""Disassembly listings — objdump, GDB, radare2, Ghidra, IDA.

Reverse-engineering agents (REA, GhidraMCP, ida-pro-mcp, r2mcp) feed models
listings that are mostly *layout*: an address column, a column of raw opcode
bytes the model never reads, box-drawing flow arrows, and alignment padding.
The instructions themselves are a fraction of the tokens.

What this removes:

- **Opcode bytes** (``55``, ``48 89 e5``). The address stays, so the bytes are
  recoverable from the binary — and the untouched listing is in the CCR store.
- **radare2 flow gutters** (``│ ╎ ┌─< └─>``). Jump targets remain in the
  operands, which is where the model reads control flow from anyway.
- **Column padding** inside each instruction line.
- **Runs of padding instructions** (``nop``, ``int3``, ``xchg ax,ax``) between
  functions, folded into one line with a count.

What it never touches: addresses, mnemonics, operands, labels, function headers,
cross-reference comments. A model can still name every instruction and follow
every jump.

Only for analysing software you are entitled to analyse — your own builds,
binaries you have permission to inspect, malware samples in a defensive
setting, CTF challenges.
"""

from __future__ import annotations

import re

_MNEMONIC = (
    r"(?:mov\w*|push\w*|pop\w*|call\w*|jmp\w*|j[a-z]{1,4}|ret\w*|lea\w?|add\w*|sub\w*"
    r"|cmp\w*|test\w?|xor\w*|and\w?|or\w?|not|neg|nop\w?|int3|leave|imul|i?div|mul"
    r"|sh[lr]\w?|sa[lr]|inc|dec|cdqe?|cqo|endbr64|syscall|hlt|ud2|cmov\w+|set\w+"
    r"|ldr\w*|str\w*|ldp|stp|bl|blr|br|b\.\w+|b|cbn?z|tbn?z|adrp?|movz|movk|cset|csel)"
)

_PREFIX = r"(?:(?:cs|ds|es|ss|lock|rep\w*|data16|notrack|bnd)\s+)*"

# One instruction line in any of the supported listing styles: an optional
# flow gutter, an address (`0x`-prefixed, `.text:`-prefixed or bare, possibly
# with a `<symbol+off>`), an optional byte column (`48 89 e5` or `4889e5`), and
# a recognisable mnemonic.
_INSN = re.compile(
    r"^(?P<gutter>[\s│╎┌└├┤┬┴┼─┐┘╰╭|<>:;=*]*?)"
    r"(?P<addr>(?:\.\w+:)?(?:0x)?[0-9a-fA-F]{4,16}(?:\s*<[^>]*>)?:?)\s+"
    r"(?P<bytes>[0-9a-fA-F]{2}(?: ?[0-9a-fA-F]{2}){0,15}\s+)?"
    rf"(?P<insn>{_PREFIX}{_MNEMONIC}\b.*)$",
    re.IGNORECASE,
)
# objdump wraps an instruction longer than seven bytes onto a second line that
# holds nothing but the address and the remaining bytes.
_BYTES_ONLY = re.compile(r"^\s*[0-9a-fA-F]{4,16}:\s+(?:[0-9a-fA-F]{2}\s?)+$")
_SPACES = re.compile(r"[ \t]{2,}")
_PADDING = re.compile(rf"^{_PREFIX}(?:nop\w?|int3|xchg\s+%?ax,\s*%?ax)\b", re.IGNORECASE)


def detect(text: str) -> bool:
    """At least 40% of the first 60 non-empty lines are instructions."""
    lines = [line for line in text.split("\n", 120)[:120] if line.strip()][:60]
    if len(lines) < 6:
        return False
    hits = sum(1 for line in lines if _INSN.match(line))
    return hits >= max(4, len(lines) * 0.4)


class DisasmCompressor:
    def compress(self, text: str) -> str:
        out: list[str] = []
        padding_run: list[str] = []

        def flush() -> None:
            if len(padding_run) >= 3:
                out.append(f"{padding_run[0]}  ; … {len(padding_run)} padding instructions")
            else:
                out.extend(padding_run)
            padding_run.clear()

        for raw in text.split("\n"):
            line = raw.rstrip()
            if not line.strip() or _BYTES_ONLY.match(line):
                continue
            m = _INSN.match(line)
            if m:
                insn = _SPACES.sub(" ", m.group("insn").strip())
                line = f"{_SPACES.sub(' ', m.group('addr'))} {insn}"
                if _PADDING.match(insn):
                    padding_run.append(line)
                    continue
            flush()
            out.append(line)
        flush()
        return "\n".join(out)
