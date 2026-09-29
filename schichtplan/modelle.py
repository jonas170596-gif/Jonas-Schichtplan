"""Datenmodelle des Schichtplaners.

Zeiten werden durchgaengig als Halbstunden-Index ab 00:00 gerechnet
(06:00 -> 12, 13:30 -> 27). Das macht Ueberdeckungsrechnungen zu
simpler Integer-Arithmetik und vermeidet Rundungsfehler.
"""
from __future__ import annotations

from dataclasses import dataclass, field

TAGE = ["mo", "di", "mi", "do", "fr", "sa"]
TAG_LANG = {
    "mo": "Montag", "di": "Dienstag", "mi": "Mittwoch",
    "do": "Donnerstag", "fr": "Freitag", "sa": "Samstag",
}

# Zellarten, die keine Arbeitszeit sind. "nicht_im_plan" = Zeile wird mit
# "-" gedruckt (z. B. Inhaber, der in dieser Filiale nicht verplant wird).
ABWESEND = ("urlaub", "schule", "krank", "sonstige")
NICHT_ARBEIT = ABWESEND + ("frei", "feiertag", "nicht_im_plan")


def zu_index(hhmm: str) -> int:
    """'13:30' -> 27"""
    h, m = hhmm.split(":")
    if m not in ("00", "30"):
        raise ValueError(f"nur volle/halbe Stunden unterstuetzt: {hhmm}")
    return int(h) * 2 + (1 if m == "30" else 0)


def zu_zeit(index: int) -> str:
    """27 -> '13:30'"""
    return f"{index // 2:02d}:{'30' if index % 2 else '00'}"


def zu_text(index: int) -> str:
    """27 -> '13:30', 28 -> '14' (Kurzform wie auf dem Papierplan)."""
    return f"{index // 2}" if index % 2 == 0 else f"{index // 2}:30"


@dataclass(frozen=True)
class Schicht:
    id: str
    von: int
    bis: int
    kategorie: str = "mittel"          # frueh | mittel | spaet
    tage: tuple[str, ...] = tuple(TAGE)

    @property
    def dauer_h(self) -> float:
        return (self.bis - self.von) / 2

    @property
    def label(self) -> str:
        return f"{zu_text(self.von)}-{zu_text(self.bis)}"

    def deckt(self, slot: int) -> bool:
        return self.von <= slot < self.bis


def schicht_aus_text(text: str) -> Schicht:
    """'6-13:30' -> Schicht. Fuer handgeschriebene Wochen, in denen Zeiten
    vorkommen, die nicht im Katalog stehen (Heiligabend und dergleichen)."""
    import re
    m = re.fullmatch(r"\s*(\d{1,2})(?::(\d{2}))?\s*-\s*(\d{1,2})(?::(\d{2}))?\s*", text)
    if not m:
        raise ValueError(f"Zeitangabe nicht lesbar: {text!r} - erwartet z. B. '6-13:30'")
    von = zu_index(f"{int(m.group(1)):02d}:{m.group(2) or '00'}")
    bis = zu_index(f"{int(m.group(3)):02d}:{m.group(4) or '00'}")
    if bis <= von:
        raise ValueError(f"Schichtende liegt nicht nach dem Beginn: {text!r}")
    kategorie = ("frueh" if von <= zu_index("07:00")
                 else "spaet" if von >= zu_index("11:00") else "mittel")
    return Schicht(id=f"{zu_text(von)}-{zu_text(bis)}", von=von, bis=bis,
                   kategorie=kategorie)


@dataclass
class Mitarbeiter:
    id: str
    name: str
    vorname: str = ""
    aktiv: bool = True
    im_plan: bool = True               # False -> Zeile wird als "-" gedruckt
    soll_stunden: float = 0.0          # Brutto-Wochenstunden inkl. Pause
    soll_tage: int = 5
    max_tage: int = 6
    feste_freie_tage: list[str] = field(default_factory=list)
    bevorzugte_freie_tage: list[str] = field(default_factory=list)
    freie_tage_zusammenhaengend: bool = False
    faehigkeiten: frozenset[str] = frozenset()
    vermeiden: list[str] = field(default_factory=list)     # Kategorien oder Schicht-IDs
    schichtwunsch: dict[str, str] = field(default_factory=dict)   # tag -> kategorie
    frueh_spaet_ausgleich: bool = True
    max_spaet_pro_woche: int | None = None
    nur_obergrenze: bool = False        # Soll ist Obergrenze, weniger ist frei
    spaet_anteil: float | None = None   # Zielanteil Spaetschichten im Fenster
    bevorzugte_kategorie: str = ""      # bekommt am liebsten diese Schichtart
    einsatzprioritaet: float = 1.0      # >1: bekommt eher Tage als andere
    samstag_konto: bool = True          # nimmt am Ausgleich freier Samstage teil
    springer: bool = False
    praesenztage: int | None = None          # Arbeitstage + gezaehlte Abwesenheiten
    abwesenheit_stunden: dict[str, float] = field(default_factory=dict)
    moeglichst_wenig: bool = False
    zaehlt_stundenbudget: bool = True
    zaehlt_kopfzahl: bool = True        # False -> steht zusaetzlich im Laden (Azubi)
    stunden_toleranz_h: float | None = None
    erlaubte_schichten: list[str] = field(default_factory=list)
    stamm_schichten: dict[str, float] = field(default_factory=dict)  # id -> Gewicht 0..1
    max_tage_in_folge: int = 6
    notiz: str = ""

    def kann(self, faehigkeit: str) -> bool:
        return faehigkeit in self.faehigkeiten


@dataclass
class Zelle:
    """Eine Zelle im Plan: entweder eine Schicht oder ein Nicht-Arbeits-Zustand."""
    art: str                            # "schicht" | frei | urlaub | schule | ...
    schicht: Schicht | None = None
    zusatz: list[str] = field(default_factory=list)   # z. B. schulung, grossputz
    fixiert: bool = False               # vom Nutzer vorgegeben -> Solver fasst sie nicht an

    @property
    def arbeitet(self) -> bool:
        return self.art == "schicht" and self.schicht is not None

    @property
    def stunden(self) -> float:
        """Anwesenheit laut Plan, also brutto."""
        return self.schicht.dauer_h if self.arbeitet else 0.0

    def netto_stunden(self, pause_h: float) -> float:
        """Anwesenheit abzueglich Pause - das zaehlt als Verkaeuferstunde."""
        return max(0.0, self.stunden - pause_h) if self.arbeitet else 0.0

    def label(self) -> str:
        if self.arbeitet:
            s = self.schicht.label
            return s + (" + " + ", ".join(self.zusatz) if self.zusatz else "")
        return {
            "frei": "Frei", "urlaub": "Urlaub", "schule": "Schule",
            "krank": "Krank", "feiertag": "", "nicht_im_plan": "-",
            "sonstige": "-",
        }.get(self.art, self.art)


@dataclass
class Plan:
    woche: str
    datum_von: str
    datum_bis: str
    zellen: dict[str, dict[str, Zelle]]        # ma_id -> tag -> Zelle
    filiale: str = ""
    offene_tage: list[str] = field(default_factory=lambda: list(TAGE))

    def zelle(self, ma: str, tag: str) -> Zelle:
        return self.zellen[ma][tag]

    def stunden(self, ma: str) -> float:
        return sum(z.stunden for z in self.zellen[ma].values())

    def netto_stunden(self, ma: str, pause_h: float) -> float:
        return sum(z.netto_stunden(pause_h) for z in self.zellen[ma].values())

    def praesenztage(self, ma: str, arten: tuple[str, ...] = ()) -> int:
        """Arbeitstage plus mitgezaehlte Abwesenheiten (Berufsschule)."""
        return sum(1 for z in self.zellen[ma].values()
                   if z.arbeitet or z.art in arten)

    def arbeitstage(self, ma: str) -> int:
        return sum(1 for z in self.zellen[ma].values() if z.arbeitet)

    def besetzung(self, tag: str, slot: int) -> int:
        return sum(
            1 for reihe in self.zellen.values()
            if reihe[tag].arbeitet and reihe[tag].schicht.deckt(slot)
        )

    def koepfe(self, tag: str) -> int:
        return sum(1 for reihe in self.zellen.values() if reihe[tag].arbeitet)
