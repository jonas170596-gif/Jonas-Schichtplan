"""Gesetzliche Feiertage in Baden-Wuerttemberg.

Gerechnet statt gepflegt - eine Tabelle waere jedes Jahr wieder Handarbeit.
Basis ist der Ostersonntag nach der Gaussschen Osterformel (Meeus/Jones/Butcher),
alle beweglichen Feiertage haengen daran.
"""
from __future__ import annotations

import datetime as dt

# Sonntage sind ohnehin zu und tauchen hier nicht auf (Ostersonntag,
# Pfingstsonntag). Weihnachten und Silvester stehen unten gesondert.
BEWEGLICH = {
    -2: "Karfreitag",
    1: "Ostermontag",
    39: "Christi Himmelfahrt",
    50: "Pfingstmontag",
    60: "Fronleichnam",
}
FEST = {
    (1, 1): "Neujahr",
    (1, 6): "Heilige Drei Koenige",
    (5, 1): "Tag der Arbeit",
    (10, 3): "Tag der Deutschen Einheit",
    (11, 1): "Allerheiligen",
    (12, 25): "1. Weihnachtsfeiertag",
    (12, 26): "2. Weihnachtsfeiertag",
}
# Keine gesetzlichen Feiertage, aber im Einzelhandel Sonderfaelle.
SONDERTAGE = {
    (12, 24): "Heiligabend",
    (12, 31): "Silvester",
}


def ostersonntag(jahr: int) -> dt.date:
    a = jahr % 19
    b, c = divmod(jahr, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    monat, tag = divmod(h + ll - 7 * m + 114, 31)
    return dt.date(jahr, monat, tag + 1)


def feiertage_bw(jahr: int) -> dict[dt.date, str]:
    """Alle gesetzlichen Feiertage in BW fuer ein Jahr."""
    ostern = ostersonntag(jahr)
    tage = {ostern + dt.timedelta(days=v): name for v, name in BEWEGLICH.items()}
    tage.update({dt.date(jahr, m, t): name for (m, t), name in FEST.items()})
    return dict(sorted(tage.items()))


def sondertage(jahr: int) -> dict[dt.date, str]:
    return {dt.date(jahr, m, t): name for (m, t), name in SONDERTAGE.items()}


class Kalender:
    """Feiertagsauskunft ueber Jahresgrenzen hinweg."""

    def __init__(self, bundesland: str = "BW"):
        if bundesland.upper() != "BW":
            raise ValueError(f"nur Baden-Wuerttemberg umgesetzt, nicht {bundesland!r}")
        self._jahre: dict[int, dict[dt.date, str]] = {}

    def _jahr(self, jahr: int) -> dict[dt.date, str]:
        if jahr not in self._jahre:
            self._jahre[jahr] = feiertage_bw(jahr)
        return self._jahre[jahr]

    def name(self, tag: dt.date) -> str | None:
        return self._jahr(tag.year).get(tag)

    def ist_feiertag(self, tag: dt.date) -> bool:
        return self.name(tag) is not None

    def geschlossen(self, tag: dt.date) -> bool:
        """Sonntage und Feiertage - da wird nicht geplant."""
        return tag.weekday() == 6 or self.ist_feiertag(tag)

    def vor_feiertag(self, tag: dt.date) -> str | None:
        """Ist der naechste Werktag (Sonntag uebersprungen) ein Feiertag?

        Damit gilt auch der Samstag vor einem Feiertagsmontag als Vortag."""
        naechster = tag + dt.timedelta(days=1)
        while naechster.weekday() == 6:
            naechster += dt.timedelta(days=1)
        return self.name(naechster)

    def nach_feiertag(self, tag: dt.date) -> str | None:
        vorher = tag - dt.timedelta(days=1)
        while vorher.weekday() == 6:
            vorher -= dt.timedelta(days=1)
        return self.name(vorher)

    def weihnachtswoche(self, montag: dt.date) -> str | None:
        """Woche, die 24.-26.12. oder 31.12./01.01. enthaelt - die wird von Hand
        geplant, dafuer gelten die normalen Regeln nicht."""
        besonders = {}
        for jahr in {montag.year, (montag + dt.timedelta(days=6)).year}:
            besonders.update(sondertage(jahr))
            besonders[dt.date(jahr, 12, 25)] = "1. Weihnachtsfeiertag"
            besonders[dt.date(jahr, 12, 26)] = "2. Weihnachtsfeiertag"
            besonders[dt.date(jahr, 1, 1)] = "Neujahr"
        treffer = [name for i in range(7)
                   if (name := besonders.get(montag + dt.timedelta(days=i)))]
        return ", ".join(treffer) if treffer else None
