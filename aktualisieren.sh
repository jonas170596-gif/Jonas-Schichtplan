#!/usr/bin/env bash
# Holt den neuesten Stand und startet danach die Weboberflaeche.
cd "$(dirname "$0")"
if [ -d .git ] && command -v git >/dev/null; then
  echo "Hole den neuesten Stand ..."
  git pull --ff-only || {
    echo
    echo "Das Holen hat nicht geklappt - vermutlich gibt es hier eigene"
    echo "Aenderungen. Der alte Stand laeuft weiter."
  }
else
  echo "Kein Git-Arbeitsverzeichnis - neuen Stand von Hand laden."
fi
exec ./start.sh "$@"
