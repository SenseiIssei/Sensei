#!/bin/sh
# Sensei installer for macOS and Linux.
#
#   curl -fsSL https://raw.githubusercontent.com/SenseiIssei/Sensei/main/install.sh | sh
#
# Downloads the single-file binary for this machine from the latest GitHub
# release, checks it against the release's SHA256SUMS, and puts it in
# ~/.local/bin. No Python, no root, no package manager. Then it offers to start
# Sensei at login and to connect the AI tools it finds.
#
# Settings, as environment variables:
#   SENSEI_VERSION=0.2.0        a specific release instead of the latest
#   SENSEI_INSTALL_DIR=DIR      where the binary goes (default ~/.local/bin)
#   SENSEI_AUTOSTART=yes|no     skip the question (default: ask, yes)
#   SENSEI_SETUP_TOOLS=yes|no   skip the question (default: ask, yes)
#   SENSEI_FROM_SOURCE=1        clone the repository and run install.py instead
#
# Everything this does is undone by: sensei autostart off; sensei disconnect;
# rm ~/.local/bin/sensei.

set -eu

REPO="SenseiIssei/Sensei"
DIR="${SENSEI_INSTALL_DIR:-$HOME/.local/bin}"

say() { printf '  %s\n' "$*"; }
ok() { printf '  \033[32m✓\033[0m %s\n' "$*"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

# Questions go to the terminal even when this script arrives through a pipe.
ask() {
    preset="$1"; question="$2"
    case "$preset" in yes|y|1|true) return 0 ;; no|n|0|false) return 1 ;; esac
    if [ -r /dev/tty ]; then
        printf '  %s [Y/n] ' "$question"
        read -r answer </dev/tty || answer=""
        case "$answer" in [Nn]*) return 1 ;; *) return 0 ;; esac
    fi
    return 0
}

fetch() {
    if command -v curl >/dev/null 2>&1; then curl -fsSL --retry 2 -o "$2" "$1"
    elif command -v wget >/dev/null 2>&1; then wget -q -O "$2" "$1"
    else fail "curl or wget is required"; fi
}

sha256() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
    else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

if [ "${SENSEI_FROM_SOURCE:-}" = "1" ]; then
    say "Installing from source"
    [ -f install.py ] || { git clone --depth 1 "https://github.com/$REPO.git" && cd Sensei; }
    exec python3 install.py "$@"
fi

case "$(uname -s)" in
    Darwin) platform=macos ;;
    Linux) platform=linux ;;
    *) fail "unsupported system $(uname -s) — on Windows use install.ps1" ;;
esac
case "$(uname -m)" in
    x86_64|amd64) arch=x86_64 ;;
    arm64|aarch64) arch=arm64 ;;
    *) fail "unsupported CPU $(uname -m)" ;;
esac
if [ "$platform" = linux ] && [ "$arch" = arm64 ]; then
    fail "no prebuilt binary for Linux on ARM yet — run with SENSEI_FROM_SOURCE=1"
fi

asset="sensei-$platform-$arch.tar.gz"
if [ -n "${SENSEI_VERSION:-}" ]; then
    base="https://github.com/$REPO/releases/download/v${SENSEI_VERSION#v}"
else
    base="https://github.com/$REPO/releases/latest/download"
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

printf '\n  \033[1mSensei\033[0m — fewer tokens for the AI tools you already use\n\n'
say "Downloading $asset"
fetch "$base/$asset" "$tmp/$asset"
fetch "$base/SHA256SUMS" "$tmp/SHA256SUMS"

expected="$(grep " \*\{0,1\}$asset\$" "$tmp/SHA256SUMS" | cut -d' ' -f1 | head -n1)"
[ -n "$expected" ] || fail "SHA256SUMS does not list $asset — refusing to install"
actual="$(sha256 "$tmp/$asset")"
[ "$expected" = "$actual" ] || fail "checksum mismatch for $asset (expected $expected, got $actual)"
ok "Checksum verified"

tar -xzf "$tmp/$asset" -C "$tmp" sensei
mkdir -p "$DIR"
install -m 0755 "$tmp/sensei" "$DIR/sensei"
ok "Installed $("$DIR/sensei" --version) to $DIR/sensei"

case ":$PATH:" in
    *":$DIR:"*) ;;
    *) say "Add $DIR to your PATH:  export PATH=\"$DIR:\$PATH\"" ;;
esac

# Tools first, autostart second. `autostart on` starts the server right away
# (systemd --now, launchd RunAtLoad), and the server connects newly found tools
# in the background — so a "no" has to be written down before it starts, or it
# is overruled thirty seconds later.
if ask "${SENSEI_SETUP_TOOLS:-}" "Connect the AI tools on this machine (Claude Code, Cursor, Codex, …)?"; then
    "$DIR/sensei" setup-tools --from-installer | sed 's/^/  /'
else
    "$DIR/sensei" setup-tools --auto off --if-unset >/dev/null 2>&1 || true
    say "AI tools left alone. Connect them later with: sensei connect"
fi

if ask "${SENSEI_AUTOSTART:-}" "Start Sensei automatically when you log in?"; then
    # Redirected from a file rather than piped: anything the service manager
    # starts must not inherit the pipe, or `sed` waits for it to close forever.
    "$DIR/sensei" autostart on >"$tmp/autostart.log" 2>&1 </dev/null || true
    sed 's/^/  /' "$tmp/autostart.log"
fi

printf '\n'
ok "Done. Dashboard: http://localhost:7000/app/"
say "Start it now:   sensei tray      (or: sensei up)"
say "Check it:       sensei doctor"
say "Update later:   sensei update"
printf '\n'
