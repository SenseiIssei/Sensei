from __future__ import annotations

from sensei.security.redaction import Redactor, redact_payload

OPENAI_KEY = "sk-abcdefghij1234567890ABCDEFGH"
GH_TOKEN = "ghp_" + "a" * 36
JWT = "eyJhbGciOi.eyJzdWIxMjM.SflKxwRJSMeKKF2QT"


def test_redacts_high_confidence_secrets():
    r = Redactor(include_pii=False)
    out, counts = r.redact(f"key {OPENAI_KEY} and token {GH_TOKEN} and {JWT}")
    assert OPENAI_KEY not in out
    assert GH_TOKEN not in out
    assert "[REDACTED:openai_key]" in out
    assert counts.get("github_token") == 1
    assert counts.get("jwt") == 1


def test_private_key_block():
    r = Redactor()
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEdummybytes\n-----END RSA PRIVATE KEY-----"
    out, counts = r.redact("here: " + pem)
    assert "BEGIN RSA PRIVATE KEY" not in out
    assert counts.get("private_key") == 1


def test_pii_is_gated():
    text = "email me at john.doe@example.com"
    off, c_off = Redactor(include_pii=False).redact(text)
    assert "john.doe@example.com" in off  # untouched by default
    assert "email" not in c_off
    on, c_on = Redactor(include_pii=True).redact(text)
    assert "john.doe@example.com" not in on
    assert c_on.get("email") == 1


def test_redact_payload_walks_nested_and_leaves_other_strings():
    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": f"my key is {OPENAI_KEY}"}],
    }
    red, counts = redact_payload(payload, Redactor(include_pii=False))
    assert OPENAI_KEY not in red["messages"][0]["content"]
    assert counts.get("openai_key") == 1
    assert red["model"] == "gpt-4o"  # non-secret strings untouched
    assert red["messages"][0]["role"] == "user"


def test_current_openai_key_formats_are_redacted():
    """`sk-proj-…` and `sk-svcacct-…` are what OpenAI issues now; the old
    pattern stopped at the second dash and let them through."""
    from sensei.security.redaction import Redactor

    r = Redactor()
    for key in ("sk-proj-" + "Ab_-" * 12, "sk-svcacct-" + "x" * 40):
        out, counts = r.redact(f"export OPENAI_API_KEY={key}")
        assert key not in out and counts.get("openai_key") == 1
    # Prose and identifiers that merely start with sk- are left alone.
    assert Redactor().redact("sk-loading-spinner-container")[1] == {}
