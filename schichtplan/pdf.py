"""HTML zu PDF, ueber einen headless Chromium.

Der Papierplan haengt im Laden aus, also muss er aus dem Werkzeug fallen und
nicht aus einem Druckdialog. Chromium kann das von der Kommandozeile und
bringt dieselbe Darstellung mit, die man im Browser sieht - fuer ein Layout
mit @page und print-Regeln ist das genau richtig.

Gibt es keinen Chromium, bleibt der Weg ueber den Browser: HTML oeffnen,
Strg+P, "Als PDF speichern". Das Layout ist dafuer vorbereitet.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

# Erst die ueblichen Namen im PATH - damit ist Linux meist erledigt.
_KANDIDATEN = ("chromium", "chromium-browser", "google-chrome",
               "google-chrome-stable", "chrome", "msedge")

# Danach die Stellen, an denen die Browser je System tatsaechlich liegen.
# Unter Windows und macOS steht Chrome nicht im PATH, dort findet ihn nur der
# feste Pfad.
_PFADE_LINUX = ("/opt/pw-browsers/chromium-*/chrome-linux/chrome",
                "/opt/pw-browsers/chromium/chrome-linux/chrome",
                "/usr/lib/chromium/chromium")
_PFADE_MAC = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)
_PFADE_WINDOWS = (
    r"{ProgramFiles}\Google\Chrome\Application\chrome.exe",
    r"{ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    r"{LocalAppData}\Google\Chrome\Application\chrome.exe",
    r"{ProgramFiles}\Microsoft\Edge\Application\msedge.exe",
    r"{ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    r"{ProgramFiles}\Chromium\Application\chrome.exe",
)


def browser() -> str | None:
    """Pfad zu einem Chromium oder Chrome, oder None.

    Eine eigene Umgebungsvariable SCHICHTPLAN_BROWSER sticht alles - damit
    laesst sich ein Browser an einer ungewoehnlichen Stelle nachreichen,
    ohne am Code zu drehen.
    """
    if eigener := os.environ.get("SCHICHTPLAN_BROWSER"):
        if pathlib.Path(eigener).exists():
            return eigener
    for name in _KANDIDATEN:
        if gefunden := shutil.which(name):
            return gefunden
    if sys.platform == "win32":
        for muster in _PFADE_WINDOWS:
            pfad = muster
            for schluessel in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData"):
                wert = os.environ.get(schluessel)
                if wert:
                    pfad = pfad.replace("{" + schluessel + "}", wert)
            if "{" not in pfad and pathlib.Path(pfad).exists():
                return pfad
        return None
    if sys.platform == "darwin":
        for pfad in _PFADE_MAC:
            if pathlib.Path(pfad).exists():
                return pfad
        return None
    for muster in _PFADE_LINUX:
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
