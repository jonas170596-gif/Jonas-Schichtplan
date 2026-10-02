"""HTML zu PDF, ueber einen headless Chromium.

Der Papierplan haengt im Laden aus, also muss er aus dem Werkzeug fallen und
nicht aus einem Druckdialog. Chromium kann das von der Kommandozeile und
bringt dieselbe Darstellung mit, die man im Browser sieht - fuer ein Layout
mit @page und print-Regeln ist das genau richtig.

Gibt es keinen Chromium, bleibt der Weg ueber den Browser: HTML oeffnen,
Strg+P, "Als PDF speichern". Das Layout ist dafuer vorbereitet.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import tempfile

# Erst die ueblichen Namen im PATH, dann die Pfade, unter denen Playwright
# seine Browser ablegt.
_KANDIDATEN = ("chromium", "chromium-browser", "google-chrome", "chrome")
_PFADE = ("/opt/pw-browsers/chromium-*/chrome-linux/chrome",
          "/opt/pw-browsers/chromium/chrome-linux/chrome",
          "/usr/lib/chromium/chromium")


def browser() -> str | None:
    """Pfad zu einem Chromium, oder None."""
    for name in _KANDIDATEN:
        if gefunden := shutil.which(name):
            return gefunden
    for muster in _PFADE:
        treffer = sorted(pathlib.Path("/").glob(muster.lstrip("/")))
        if treffer:
            return str(treffer[-1])
    return None


class KeinBrowser(RuntimeError):
    """Kein Chromium gefunden - der Aufrufer soll den Druckdialog nennen."""


def aus_html(html: str, ziel: pathlib.Path, *, quer: bool = True) -> pathlib.Path:
    """HTML als PDF nach `ziel` schreiben."""
    exe = browser()
    if not exe:
        raise KeinBrowser(
            "Kein Chromium gefunden. Die HTML-Datei im Browser oeffnen und "
            "ueber Strg+P als PDF speichern - das Layout ist dafuer gebaut.")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        quelle = pathlib.Path(tmp) / "plan.html"
        quelle.write_text(html, encoding="utf-8")
        befehl = [exe, "--headless", "--disable-gpu", "--no-sandbox",
                  "--no-pdf-header-footer",
                  f"--print-to-pdf={ziel}", quelle.as_uri()]
        if quer:
            befehl.insert(-1, "--print-to-pdf-no-header")
        ergebnis = subprocess.run(befehl, capture_output=True, text=True,
                                  timeout=120)
    if not ziel.exists() or ziel.stat().st_size == 0:
        raise RuntimeError(f"Chromium hat kein PDF geschrieben:\n"
                           f"{ergebnis.stderr.strip()[-500:]}")
    return ziel
