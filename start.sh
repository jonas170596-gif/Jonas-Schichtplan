#!/usr/bin/env bash
# Startet die Weboberflaeche. Beenden mit Strg+C.
set -e
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python)
"$PY" -c "import yaml" 2>/dev/null || {
  echo "PyYAML fehlt, wird nachinstalliert ..."
  "$PY" -m pip install pyyaml
}
exec "$PY" -m schichtplan web "$@"
