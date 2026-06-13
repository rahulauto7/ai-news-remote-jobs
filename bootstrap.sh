#!/usr/bin/env bash
# Bootstrap the daily AI-news pipeline into an isolated .venv.
#
# WHY a venv: the cloud sandbox (and some Debian hosts) ship a patched system
# Python whose setuptools is broken — `pip install -r requirements.txt` against
# it aborts mid-build (feedparser's sgmllib3k: `install_layout`, or
# "Cannot uninstall wheel … RECORD file not found"), leaving feedparser /
# pytrends / slack_sdk missing and the pipeline half-installed. A fresh venv
# builds everything cleanly. `.venv/` is gitignored.
#
# Idempotent: safe to re-run. Run every pipeline step with `.venv/bin/python`,
# e.g.  ./bootstrap.sh && .venv/bin/python tools/run_daily_pipeline.py
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

VENV="$ROOT/.venv"
PY="$VENV/bin/python"

# Pick a real interpreter to build the venv with (never the venv's own).
BOOTSTRAP_PY="${PYTHON:-}"
if [ -z "$BOOTSTRAP_PY" ]; then
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then BOOTSTRAP_PY="$c"; break; fi
  done
fi
if [ -z "$BOOTSTRAP_PY" ]; then
  echo "bootstrap: no python3/python found on PATH" >&2
  exit 1
fi

if [ ! -x "$PY" ]; then
  echo "bootstrap: creating venv at $VENV (using $BOOTSTRAP_PY)"
  "$BOOTSTRAP_PY" -m venv "$VENV"
fi

echo "bootstrap: upgrading pip/setuptools/wheel"
"$PY" -m pip install --quiet --upgrade pip setuptools wheel

echo "bootstrap: installing requirements.txt"
"$PY" -m pip install --quiet -r "$ROOT/requirements.txt"

echo "bootstrap: done → run the pipeline with: .venv/bin/python tools/run_daily_pipeline.py"
