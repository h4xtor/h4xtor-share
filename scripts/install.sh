#!/usr/bin/env bash
#
# Installs h4xtor-share on Linux and macOS through Python (pip).
#
# The latest release wheel is downloaded from the GitHub release; if that
# fails, the app is installed directly from the repository. Everything lives
# in an isolated virtual environment and a launcher is written to
# ~/.local/bin/h4xtor-share.
#
# Python 3.11 or later is required. Debian/Ubuntu also need the Tk runtime:
#     sudo apt install python3-tk
#
# Run:
#     bash <(curl -fsSL https://raw.githubusercontent.com/h4xtor/h4xtor-share/main/scripts/install.sh)
#

set -euo pipefail

REPO="h4xtor/h4xtor-share"
APP_NAME="h4xtor-share"

BASE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/$APP_NAME"
VENV_DIR="$BASE_DIR/venv"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
LAUNCHER="$BIN_DIR/$APP_NAME"

log() { printf '==> %s\n' "$*"; }
err() { printf '%s\n' "$*" >&2; }

find_python() {
    local candidate version major minor
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            version="$("$candidate" -c 'import sys; print(".".join(map(str, sys.version_info[:2])))' 2>/dev/null || true)"
            if [ -n "$version" ]; then
                major="${version%%.*}"
                minor="${version#*.}"
                minor="${minor%%.*}"
                if [ "$major" -gt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -ge 11 ]; }; then
                    command -v "$candidate"
                    return 0
                fi
            fi
        fi
    done
    return 1
}

PYTHON="$(find_python || true)"
if [ -z "$PYTHON" ]; then
    err "h4xtor-share requires Python 3.11 or later."
    err "Install a recent Python and make sure 'python3' is on your PATH."
    exit 1
fi

log "Using Python: $PYTHON"
mkdir -p "$BASE_DIR" "$BIN_DIR"

if [ ! -x "$VENV_DIR/bin/python" ]; then
    log "Creating virtual environment at $VENV_DIR"
    "$PYTHON" -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install --upgrade pip >/dev/null

installed=0
if command -v curl >/dev/null 2>&1; then
    log "Fetching the latest release from GitHub"
    release="$(curl -fsSL -H "User-Agent: h4xtor-share-installer" "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null || true)"
    url="$(printf '%s' "$release" | "$VENV_DIR/bin/python" -c '
import json, sys
try:
    data = json.load(sys.stdin)
    wheels = [a for a in data.get("assets", []) if a.get("name", "").endswith(".whl")]
    print(wheels[0]["browser_download_url"] if wheels else "")
except Exception:
    print("")
' 2>/dev/null || true)"
    if [ -n "$url" ]; then
        log "Downloading wheel"
        if curl -fsSL -o "$BASE_DIR/package.whl" "$url" && "$VENV_DIR/bin/python" -m pip install "$BASE_DIR/package.whl" >/dev/null 2>&1; then
            installed=1
        fi
    fi
fi

if [ "$installed" -ne 1 ]; then
    log "Release download failed, installing from the repository instead"
    "$VENV_DIR/bin/python" -m pip install "h4xtor-share @ git+https://github.com/$REPO.git" >/dev/null
fi

log "Writing launcher to $LAUNCHER"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
exec "$VENV_DIR/bin/python" -m h4xtor_share "\$@"
EOF
chmod +x "$LAUNCHER"

if ! "$VENV_DIR/bin/python" -c "import tkinter" >/dev/null 2>&1; then
    err ""
    err "Note: your Python is missing the Tk user interface runtime."
    err "On Debian/Ubuntu run: sudo apt install python3-tk"
fi

log "Verifying the installation"
"$VENV_DIR/bin/python" -c "import h4xtor_share; print('h4xtor-share', h4xtor_share.__version__)"

printf '\nh4xtor-share installed.\n'
printf 'Run it with:  %s\n' "$LAUNCHER"
if [ "$BIN_DIR" != "$HOME/.local/bin" ] || [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    printf 'Add %s to your PATH to run it as: %s\n' "$BIN_DIR" "$APP_NAME"
fi
