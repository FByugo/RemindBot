#!/usr/bin/env bash
set -u
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { python3 -m venv .venv && .venv/bin/pip install -q -e ".[test]"; } || exit 2
.venv/bin/python -m pytest -q tests || exit 1
echo "check: all green"
