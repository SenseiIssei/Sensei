# Security Policy

## Supported versions

Sensei is pre-1.0. Security fixes land on `main` and in the next tagged
release. Only the latest release is supported.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately through GitHub's
[private vulnerability reporting](https://github.com/SenseiIssei/Sensei/security/advisories/new).

Please include:

- what the issue is and roughly how bad you think it is
- steps to reproduce, or a proof of concept
- the version or commit you tested
- your OS and how you're running Sensei (Docker, installer, from source)

You can expect an acknowledgement within **7 days** and an assessment within
**30 days**. Sensei is maintained by a very small team — if a fix will take
longer than that, you'll be told where it stands rather than left waiting.

Please give a fix a reasonable window before disclosing publicly. Reporters are
credited in the release notes unless they'd rather not be.

## What is and isn't in scope

Sensei is a **self-hosted** application. It assumes the machine it runs on is
trusted and that whoever can reach the port is authorised to use it.

In scope:

- remote code execution, path traversal, or SSRF via the gateway, agent tools,
  the crawler, or RAG ingestion
- authentication or authorisation bypass (JWT, OIDC, RBAC, session handling)
- leaking API keys or conversation contents to a model provider, to disk in
  plaintext, or across user boundaries
- prompt-injection paths that let untrusted fetched content drive tool calls
- flaws in encryption at rest or in the API-key vault

Out of scope:

- anything that requires an attacker to already have shell access on the host
- exposing Sensei to the public internet without a reverse proxy and auth.
  Sensei binds to `127.0.0.1` by default; overriding that is your decision
- denial of service via resource exhaustion on your own machine
- vulnerabilities in a model provider's API rather than in Sensei

## Hardening notes

If you run Sensei anywhere but your own laptop:

- keep `SENSEI_HOST=127.0.0.1` and put a TLS-terminating reverse proxy in front
  (templates in [`deploy/`](deploy/))
- set `SENSEI_AUTH_ENABLED=true` and a strong `SENSEI_AUTH_TOKEN`
- leave `SENSEI_CODE_EXEC_ENABLED=false` unless you need `run_python`, and
  understand that it runs in a subprocess, not a container
- set `SENSEI_JWT_SECRET` explicitly rather than relying on the generated one
- keep `SENSEI_DATA_ENCRYPTION_ENABLED=true`
