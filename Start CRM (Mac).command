#!/usr/bin/env bash
# Double-click to start Simple CRM (Mac), or run:  bash "Start CRM (Mac).command"
set -e
cd "$(dirname "$0")"

is_new_enough() {  # true if "$1" is a Python 3.10+ interpreter
  [ -n "$1" ] && [ -x "$1" ] && "$1" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1
}

find_python() {
  # Prefer a specific new Python (python.org, Homebrew) over a generic "python3",
  # which may be an older Anaconda or Apple copy that comes first on PATH.
  local v p
  for v in 3.16 3.15 3.14 3.13 3.12 3.11 3.10; do
    for p in "$(command -v "python$v" 2>/dev/null || true)" \
             "/Library/Frameworks/Python.framework/Versions/$v/bin/python3" \
             "/opt/homebrew/bin/python$v" "/usr/local/bin/python$v"; do
      if is_new_enough "$p"; then echo "$p"; return 0; fi
    done
  done
  for p in "$(command -v python3 2>/dev/null || true)" "$(command -v python 2>/dev/null || true)"; do
    if is_new_enough "$p"; then echo "$p"; return 0; fi
  done
  return 1
}

# Rebuild the app's private environment if it's missing or was made with an old Python.
if ! is_new_enough ".venv/bin/python"; then
  PY="$(find_python || true)"
  if [ -z "$PY" ]; then
    echo "Python 3.10 or newer is required, but none was found."
    echo "The 'python3' on this Mac is: $(command -v python3 || echo none) ($(python3 --version 2>&1 || true))"
    echo "Install Python from https://www.python.org/downloads/ and run this again."
    read -r -p "Press Enter to close." _; exit 1
  fi
  echo "First run: setting up the app with $("$PY" --version) (about a minute)..."
  rm -rf .venv
  "$PY" -m venv .venv
fi

.venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt
echo "Starting Simple CRM... (close this window to stop it)"
.venv/bin/python -m streamlit run app.py
