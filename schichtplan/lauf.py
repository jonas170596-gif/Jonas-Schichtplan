"""Eine Woche rechnen und die Ausgabedateien schreiben.

Den Weg von der Wochenvorgabe zum fertigen Satz Dateien gehen die
Kommandozeile und die Weboberflaeche gleichermassen - er steht deshalb hier
und nicht in einer der beiden.
"""
from __future__ import annotations

import pathlib

from . import export
from .bewertung import Bewerter
from .generator import erzeuge
from .konfig import Stammdaten, Wochenvorgabe
from .modelle import Plan


def plane(stamm: Stammdaten, vorgabe: Wochenvorgabe, vorwochen: list, *,
          iterationen: int = 40000, neustarts: int = 4, seed: int | None = None):
    """Den Plan rechnen. Handplaene ('modus: manuell') werden nur geprueft."""
    return erzeuge(stamm, vorgabe, vorwochen, iterationen=iterationen,
                   neustarts=neustarts, seed=seed)


def schreibe(plan: Plan, stamm: Stammdaten, bewertung, bewerter: Bewerter,
             vorwochen: list, ziel: pathlib.Path | str, *,
             pdf: bool = False, arbeitsbereich: str = "", pause: int = 30,
             ) -> tuple[list[str], list[str]]:
    """Schreibt Papierplan, Teamleiteruebersicht und die Exporte.

    Gibt (geschriebene Dateien, Meldungen) zurueck. Eine Meldung gibt es nur,
    wenn das PDF nicht erzeugt werden konnte - der Rest ist dann trotzdem da.
    """
    ziel = pathlib.Path(ziel)
    ziel.mkdir(parents=True, exist_ok=True)
    basis = ziel / plan.woche
    dateien = {
        f"{basis}.html": export.als_html(plan, stamm, bewertung, bewerter=bewerter),
        f"{basis}.json": export.als_json(plan, stamm),
        f"{basis}.csv": export.als_csv(plan, stamm),
        f"{basis}-e2n-schichten.csv": export.als_e2n_csv(
            plan, stamm, arbeitsbereich=arbeitsbereich, pause_min=pause),
        f"{basis}-e2n-abwesenheiten.csv": export.als_abwesenheits_csv(plan, stamm),
    }
    # Teamleiteruebersicht: Befunde, Stunden und Konten auf einer Seite. Die
    # Konten brauchen die Historie - ohne sie bleibt der Block weg.
    from . import uebersicht as _uebersicht
    kontozeilen = None
    if vorwochen:
        from . import konten as _konten
        kontozeilen = _konten.sammle(stamm, vorwochen)
    dateien[f"{basis}-teamleiter.html"] = _uebersicht.als_html(
        plan, stamm, bewertung, bewerter, kontozeilen)
    for pfad, inhalt in dateien.items():
        pathlib.Path(pfad).write_text(inhalt, encoding="utf-8")

    geschrieben, meldungen = list(dateien), []
    if pdf:
        from . import pdf as _pdf
        for name, quer in ((f"{basis}.html", True),
                           (f"{basis}-teamleiter.html", False)):
            try:
                erzeugt = _pdf.aus_html(
                    pathlib.Path(name).read_text(encoding="utf-8"),
                    pathlib.Path(name[:-5] + ".pdf"), quer=quer)
                geschrieben.append(str(erzeugt))
            except _pdf.KeinBrowser as fehler:
                meldungen.append(f"PDF nicht erzeugt: {fehler}")
                break
    return geschrieben, meldungen
