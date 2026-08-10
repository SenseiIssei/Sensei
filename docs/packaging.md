# Getting Sensei into package managers

Every release already renders the manifests: `scripts/render_manifests.py` reads
the release's own `SHA256SUMS` and attaches
`package-manager-manifests.tar.gz`. What follows is the part that cannot be
automated from inside this repository, because each package manager wants the
manifest to live somewhere else.

Each of these is one-time setup. After it, a release publishes itself.

---

## The state of it

| Channel | One-time setup | Then |
|---|---|---|
| **PyPI** | Create the project, add GitHub as a trusted publisher, set `PYPI_ENABLED=true` | Automatic on tag |
| **GHCR** | None — uses `GITHUB_TOKEN` | Automatic on tag |
| **GitHub Releases** | None | Automatic on tag |
| **Homebrew** | Create `SenseiIssei/homebrew-tap`, add `TAP_TOKEN` | Automatic on tag |
| **Scoop** | Create `SenseiIssei/scoop-bucket`, add `BUCKET_TOKEN` | Automatic on tag |
| **winget** | Fork `microsoft/winget-pkgs`, open a PR per release | Manual, ~5 minutes |
| **VS Code Marketplace** | Create a publisher, add `VSCE_PAT` | Automatic on tag |
| **Open VSX** | Create a namespace, add `OVSX_PAT` | Automatic on tag |

---

## PyPI

The distribution is **`sensei-gateway`**, not `sensei`. The plain name was
registered in 2023 by an unrelated HTTP-client library and `sensei-ai` is taken
as well. The import package and the console script are both still `sensei`, so
this only changes the string you type once at install time.

1. Register `sensei-gateway` on PyPI.
2. **Publishing → Add a new pending publisher**: owner `SenseiIssei`, repository
   `Sensei`, workflow `release.yml`, environment `pypi`. Trusted Publishing
   means no API token is ever stored in this repo.
3. Repository → Settings → Variables → `PYPI_ENABLED` = `true`.

The `pypi` job is gated on that variable, so until it is set a release skips
PyPI rather than failing on it.

## Homebrew

A tap is a repository named `homebrew-<something>`; the `homebrew-` prefix is
what makes `brew install senseiissei/tap/sensei` resolve.

1. Create `SenseiIssei/homebrew-tap` with a `Formula/` directory.
2. Create a fine-grained PAT with **contents: write** on that repository only,
   and add it here as the `TAP_TOKEN` secret.

That is all. The `homebrew` job in `release.yml` is gated on `TAP_TOKEN`
existing: without it a release skips the job, and with it the formula is
committed to the tap automatically.

The formula ships the PyInstaller binary rather than declaring a Python
dependency. A formula that pip-installs would drag in a Homebrew Python it then
has to stay in sync with, which is a recurring support cost for a project whose
pitch is that it stays out of your way.

## Scoop

A bucket is any repository with a `bucket/` directory of JSON manifests.

1. Create `SenseiIssei/scoop-bucket` with a `bucket/` directory.
2. Add a `BUCKET_TOKEN` secret the same way as the tap.

The manifest carries `checkver` and `autoupdate`, so Scoop's own bots keep it
current between releases.

## winget

winget has no push API. Manifests live in `microsoft/winget-pkgs` and arrive by
pull request, which is reviewed and run through automated validation.

1. Fork `microsoft/winget-pkgs`.
2. Take `manifests/winget/` out of the release's
   `package-manager-manifests.tar.gz`.
3. Copy it over the fork's `manifests/` tree, commit, open a PR.

[`wingetcreate`](https://github.com/microsoft/winget-create) automates steps 2
and 3 and can be wired into CI later. It is left manual for now because the
first submission of a new package is reviewed by a human anyway, and there is no
point automating a step that will block on review regardless.

## VS Code Marketplace and Open VSX

Both are already wired in the `extension` job and gated on their tokens
existing, so a release without them skips publishing and still attaches the
`.vsix`.

- **Marketplace**: create a publisher at <https://marketplace.visualstudio.com/manage>,
  generate a PAT with **Marketplace → Manage**, add it as `VSCE_PAT`.
- **Open VSX**: create a namespace at <https://open-vsx.org>, generate an access
  token, add it as `OVSX_PAT`.

---

## A note on signing

None of these installers are code-signed. macOS shows a Gatekeeper prompt and
Windows shows SmartScreen, and every release note says so along with how to
verify the artifact instead.

That is the honest position, not a comfortable one. An Apple Developer account
is $99/year and a Windows OV certificate is a few hundred; until those exist,
SHA256SUMS and Sigstore signatures are what users have. They are better evidence
than a signature nobody checks — but they are also evidence almost nobody looks
at, so this is worth revisiting once the project has users who would.
