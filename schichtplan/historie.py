"""Einlesen der digitalisierten Altplaene."""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass

from .modelle import TAGE, Schicht, zu_index

HISTORIE_DIR = pathlib.Path("daten/historie")


@dataclass
class HistZelle:
    art: str
    von: int | None = None
    bis: int | None = None
    zusatz: tuple[str, ...] = ()
    unklar: bool = False

    @property
    def arbeitet(self) -> bool:
        return self.art == "schicht"

    @property
    def verwertbar(self) -> bool:
        """Zellen ohne Endzeit ('6-' auf dem Papier) taugen nicht fuer Statistik."""
        return self.arbeitet and self.bis is not None

    @property
    def label(self) -> str:
        if not self.arbeitet:
            return self.art
        from .modelle import zu_text
        bis = zu_text(self.bis) if self.bis is not None else "?"
        return f"{zu_text(self.von)}-{bis}"

    @property
    def stunden(self) -> float:
        return (self.bis - self.von) / 2 if self.verwertbar else 0.0


@dataclass
class HistWoche:
    woche: str
    datum_von: str
    status: str
    quelle_foto: str
    plan: dict[str, dict[str, HistZelle]]
    notiz: str = ""

    @property
    def final(self) -> bool:
        return self.status == "final"

    def offene_tage(self) -> list[str]:
        return [t for t in TAGE
                if not all(r[t].art == "feiertag" for r in self.plan.values())]


def kalenderabgleich(wochen: list[HistWoche]) -> list[str]:
    """Stimmen die als Feiertag markierten Spalten mit dem Kalender ueberein?

    Die Kopfzeilen der Papierplaene sind durchgaengig einen Tag zu frueh
    datiert; dadurch kann die Feiertagsspalte verrutscht sein."""
    import datetime as dt

    from .feiertage import Kalender
    kalender = Kalender()
    meldungen = []
    for w in wochen:
        montag = dt.date.fromisoformat(w.datum_von)
        laut_plan = sorted(t for t in TAGE
                           if all(r[t].art == "feiertag" for r in w.plan.values()))
        laut_kalender = sorted(t for i, t in enumerate(TAGE)
                               if kalender.ist_feiertag(montag + dt.timedelta(days=i)))
        if laut_plan != laut_kalender:
            meldungen.append(
                f"{w.woche}: Plan schliesst {laut_plan or ['nichts']}, "
                f"der Kalender nennt {laut_kalender or ['nichts']}")
    return meldungen


def lade_historie(ordner: pathlib.Path | str = HISTORIE_DIR,
                  nur_final: bool = True) -> list[HistWoche]:
    ordner = pathlib.Path(ordner)
    wochen = []
    for pfad in sorted(ordner.glob("*.json")):
        roh = json.loads(pfad.read_text(encoding="utf-8"))
        plan = {}
        for ma, tage in roh["plan"].items():
            plan[ma] = {
                t: HistZelle(
                    art=c["art"],
                    von=zu_index(c["von"]) if c.get("von") else None,
                    bis=zu_index(c["bis"]) if c.get("bis") else None,
                    zusatz=tuple(c.get("zusatz", [])),
                    unklar=bool(c.get("unklar")),
                )
                for t, c in tage.items()
            }
        w = HistWoche(
            woche=roh["woche"], datum_von=roh["datum_von"], status=roh["status"],
            quelle_foto=roh.get("quelle_foto", ""), plan=plan, notiz=roh.get("notiz", ""),
        )
        if nur_final and not w.final:
            continue
        wochen.append(w)
    wochen.sort(key=lambda w: w.datum_von)
    return wochen


def schicht_aus_hist(z: HistZelle) -> Schicht | None:
    if not z.verwertbar:
        return None
    kat = "frueh" if z.von <= zu_index("07:00") else ("spaet" if z.von >= zu_index("11:00") else "mittel")
    from .modelle import zu_text
    return Schicht(id=f"{zu_text(z.von)}-{zu_text(z.bis)}", von=z.von, bis=z.bis, kategorie=kat)
