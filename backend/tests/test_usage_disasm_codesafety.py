from __future__ import annotations

import json
import time

import pytest

from sensei.compression.codecomp import CodeCompressor
from sensei.compression.disasm import DisasmCompressor, detect
from sensei.compression.router import ContentRouter, ContentType
from sensei.security.redaction import redact_payload
from sensei.usage import Usage, UsageSniffer, from_response, from_usage_block

# ─── usage normalisation ─────────────────────────────────────────────────────


class TestUsage:
    def test_anthropic_counts_cache_separately(self):
        u = from_usage_block(
            {
                "input_tokens": 50,
                "cache_read_input_tokens": 900,
                "cache_creation_input_tokens": 50,
                "output_tokens": 12,
            }
        )
        assert u == Usage(prompt=1000, output=12, cache_read=900, cache_write=50)

    def test_openai_chat_includes_cached_in_prompt(self):
        u = from_usage_block(
            {
                "prompt_tokens": 1000,
                "completion_tokens": 20,
                "prompt_tokens_details": {"cached_tokens": 640},
            }
        )
        assert u == Usage(prompt=1000, output=20, cache_read=640)

    def test_openai_responses(self):
        u = from_response(
            {"usage": {"input_tokens": 300, "output_tokens": 9, "input_tokens_details": {}}}
        )
        assert u == Usage(prompt=300, output=9)

    def test_garbage_is_zero_not_an_exception(self):
        assert from_usage_block("nope") == Usage()
        assert from_usage_block({"input_tokens": -4, "output_tokens": "x"}) == Usage()

    def test_sniffer_survives_chunk_boundaries(self):
        events = [
            {
                "type": "message_start",
                "message": {"usage": {"input_tokens": 5, "cache_read_input_tokens": 95}},
            },
            {"type": "message_delta", "usage": {"output_tokens": 3}},
        ]
        data = "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()
        sniffer = UsageSniffer()
        for i in range(0, len(data), 7):  # deliberately awkward chunking
            sniffer.feed(data[i : i + 7])
        assert sniffer.close() == Usage(prompt=100, output=3, cache_read=95)

    def test_sniffer_reads_responses_completed(self):
        event = {
            "type": "response.completed",
            "response": {
                "usage": {
                    "input_tokens": 40,
                    "output_tokens": 2,
                    "input_tokens_details": {"cached_tokens": 32},
                }
            },
        }
        sniffer = UsageSniffer()
        sniffer.feed(f"event: response.completed\ndata: {json.dumps(event)}\n".encode())
        assert sniffer.close() == Usage(prompt=40, output=2, cache_read=32)

    def test_sniffer_does_not_buffer_a_huge_line(self):
        sniffer = UsageSniffer()
        sniffer.feed(b"data: " + b"x" * 200_000)
        assert len(sniffer._pending) == 0


# ─── code compression must not change what code means ───────────────────────


class TestCodeSafety:
    @pytest.mark.parametrize(
        "line",
        [
            'colour = "#16a34a"',
            "url = 'https://example.com/#top'",
            'fmt = "%d items # not a comment"',
        ],
    )
    def test_python_strings_survive(self, line):
        src = f"import os\nimport sys\n\ndef f():\n    {line}\n    return 1\n"
        assert line in CodeCompressor().compress(src)

    @pytest.mark.parametrize(
        "line",
        [
            'const url = "https://example.com/a";',
            "const glob = 'src/**/*.ts';",
            "const re = `// still a string`;",
        ],
    )
    def test_js_strings_survive(self, line):
        src = f"import x from 'x';\n{line}\nfunction f() {{ return 1; }}\n"
        assert line in CodeCompressor().compress(src)

    def test_consecutive_consts_are_not_imports(self):
        """`const` lines used to be folded away as an 'import block'."""
        src = "import a from 'a';\nconst w = 1;\nconst x = 2;\nconst y = 3;\nconst z = 4;\n"
        out = CodeCompressor().compress(src)
        for name in "wxyz":
            assert f"const {name} =" in out

    def test_multiline_docstring_is_removed_whole(self):
        src = 'def f():\n    """Summary.\n\n    Details.\n    """\n    return 1\n'
        out = CodeCompressor().compress(src)
        assert "Details" not in out and "Summary" not in out
        assert "return 1" in out

    def test_triple_quoted_data_is_kept_verbatim(self):
        src = 'def f():\n    q = """\n    # not a comment\n    SELECT 1\n    """\n    return q\n'
        out = CodeCompressor().compress(src)
        assert "# not a comment" in out

    def test_unknown_language_keeps_hash_lines(self):
        md = "# Title\n\nSome prose.\n\n## Section\n"
        assert "# Title" in CodeCompressor().compress(md)

    def test_scanner_is_linear(self):
        src = "x = '" + "\\'" * 50_000 + "'\n"
        start = time.perf_counter()
        CodeCompressor()._strip_comments(src.split("\n"), "python")
        assert time.perf_counter() - start < 1.0


# ─── disassembly ─────────────────────────────────────────────────────────────

OBJDUMP = """0000000000401126 <main>:
  401126:	55                   	push   %rbp
  401127:	48 89 e5             	mov    %rsp,%rbp
  40112a:	48 83 ec 10          	sub    $0x10,%rsp
  40112e:	89 7d fc             	mov    %edi,-0x4(%rbp)
  401136:	e8 f5 fe ff ff       	call   401030 <puts@plt>
  40113b:	b8 00 00 00 00       	mov    $0x0,%eax
  401140:	c9                   	leave
  401141:	c3                   	ret
  401142:	66 2e 0f 1f 84 00 00 	cs nopw 0x0(%rax,%rax,1)
  401149:	00 00 00
  40114c:	0f 1f 40 00          	nopl   0x0(%rax)
  401150:	90                   	nop
"""

RADARE = """┌ 35: int main (int argc, char **argv);
│           0x00401126      55             push rbp
│           0x00401127      4889e5         mov rbp, rsp
│       ┌─< 0x0040112e      7405           je 0x401135
│       │   0x00401130      e8fbfeffff     call sym.imp.puts
│       └─> 0x00401135      b800000000     mov eax, 0
│           0x0040113a      c9             leave
└           0x0040113b      c3             ret
"""

GHIDRA = """                     main
        00401126 55              PUSH       RBP
        00401127 48 89 e5        MOV        RBP,RSP
        0040112a 48 83 ec 10     SUB        RSP,0x10
        0040112e 74 05           JZ         LAB_00401135
        00401130 e8 fb fe ff ff  CALL       puts
        00401135 b8 00 00 00 00  MOV        EAX,0x0
        0040113a c9              LEAVE
        0040113b c3              RET
"""


class TestDisasm:
    @pytest.mark.parametrize("listing", [OBJDUMP, RADARE, GHIDRA])
    def test_detected(self, listing):
        assert detect(listing)
        assert ContentRouter(enable_caching=False).detect_type(listing) is ContentType.disasm

    @pytest.mark.parametrize("listing", [OBJDUMP, RADARE, GHIDRA])
    def test_keeps_every_instruction(self, listing):
        out = DisasmCompressor().compress(listing).lower()
        for needle in ("push", "mov", "call", "leave", "ret"):
            assert needle in out
        assert len(out) < len(listing)

    def test_drops_bytes_but_keeps_addresses_and_targets(self):
        out = DisasmCompressor().compress(RADARE)
        assert "4889e5" not in out
        assert "0x00401127 mov rbp, rsp" in out
        assert "je 0x401135" in out

    def test_padding_is_folded(self):
        out = DisasmCompressor().compress(OBJDUMP)
        assert "padding instructions" in out
        assert "00 00 00" not in out

    def test_logs_and_hexdumps_are_not_disassembly(self):
        logs = "\n".join(f"2026-10-16 12:00:{i:02d} INFO worker {i} done" for i in range(20))
        hexdump = "\n".join(
            f"{i * 16:08x}: 7f45 4c46 0201 0100 0000 0000 0000 0000" for i in range(20)
        )
        assert not detect(logs)
        assert not detect(hexdump)


# ─── redaction leaves signed blobs alone ─────────────────────────────────────


def test_redaction_skips_signatures_and_encrypted_reasoning():
    secret = "sk-ant-api03-" + "A" * 40
    payload = {
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "t", "signature": secret},
                    {"type": "text", "text": f"key is {secret}"},
                ],
            }
        ],
        "input": [{"type": "reasoning", "encrypted_content": secret}],
    }
    out, counts = redact_payload(payload)
    blocks = out["messages"][0]["content"]
    assert blocks[0]["signature"] == secret
    assert out["input"][0]["encrypted_content"] == secret
    assert secret not in blocks[1]["text"]
    assert sum(counts.values()) >= 1
