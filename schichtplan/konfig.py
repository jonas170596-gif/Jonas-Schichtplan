"""Laden der Stammdaten (Mitarbeiter, Schichten, Bedarf, Regeln) und der
Wochenvorgabe."""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

import yaml

from .modelle import TAGE, Mitarbeiter, Schicht, zu_index

KONFIG_DIR = pathlib.Path("konfig")


@dataclass
class Bedarf:
    offene_tage: list[str]
    oeffnung: dict[str, tuple[int, int]]          # tag -> (von, bis) als Slotindex
    kopfzahl: dict[str, int]
    frueh_min: dict[str, int]                     # Schichten mit Start <= frueh_bis
    frueh_bis: int
    schluss_min: dict[str, int]                   # Schichten, die bis Ladenschluss laufen
    besetzung_min: dict[str, list[tuple[int, int, int]]]   # tag -> [(von, bis, min)]
    kopfzahl_toleranz: int = 0

    def min_am_slot(self, tag: str, slot: int) -> int:
        return max((m for v, b, m in self.besetzung_min.get(tag, []) if v <= slot < b),
                   default=0)


@dataclass
class Regeln:
    gewichte: dict[str, float]
    ruhezeit_h: float = 11.0
    ruhezeit_min_h: float = 10.0
    stunden_toleranz_h: float = 0.0
    max_tage_in_folge: int = 6
    samstage_frei_pro_x: int = 0        # 0 = aus; sonst: 1 freier Samstag je X Wochen


@dataclass
class Stammdaten:
    mitarbeiter: dict[str, Mitarbeiter]
    schichten: dict[str, Schicht]
    bedarf: Bedarf
    regeln: Regeln


def _lies(pfad: pathlib.Path) -> dict:
    if not pfad.exists():
        raise FileNotFoundError(f"Konfigurationsdatei fehlt: {pfad}")
    return yaml.safe_load(pfad.read_text(encoding="utf-8")) or {}


def lade_stammdaten(ordner: pathlib.Path | str = KONFIG_DIR) -> Stammdaten:
    ordner = pathlib.Path(ordner)

    roh_s = _lies(ordner / "schichten.yaml")
    schichten = {}
    for sid, s in roh_s["schichten"].items():
        schichten[sid] = Schicht(
            id=sid,
            von=zu_index(s["von"]),
            bis=zu_index(s["bis"]),
            kategorie=s.get("kategorie", "mittel"),
            tage=tuple(s.get("tage", TAGE)),
        )

    roh_m = _lies(ordner / "mitarbeiter.yaml")
    mitarbeiter = {}
    for mid, m in roh_m["mitarbeiter"].items():
        erlaubt = list(m.get("erlaubte_schichten", []))
        unbekannt = [s for s in erlaubt if s not in schichten]
        if unbekannt:
            raise ValueError(f"{mid}: unbekannte Schichten {unbekannt}")
        mitarbeiter[mid] = Mitarbeiter(
            id=mid,
            name=m["name"],
            aktiv=m.get("aktiv", True),
            im_plan=m.get("im_plan", True),
            soll_stunden=float(m.get("soll_stunden", 0)),
            soll_tage=int(m.get("soll_tage", 5)),
            max_tage=int(m.get("max_tage", 6)),
            feste_freie_tage=list(m.get("feste_freie_tage", [])),
            erlaubte_schichten=erlaubt,
            stamm_schichten={k: float(v) for k, v in (m.get("stamm_schichten") or {}).items()},
            max_tage_in_folge=int(m.get("max_tage_in_folge", 6)),
            notiz=m.get("notiz", ""),
        )

    roh_b = _lies(ordner / "bedarf.yaml")
    offene = list(roh_b.get("offene_tage", TAGE))
    bedarf = Bedarf(
        offene_tage=offene,
        oeffnung={t: (zu_index(v["von"]), zu_index(v["bis"]))
                  for t, v in roh_b["oeffnung"].items()},
        kopfzahl={t: int(v) for t, v in roh_b["kopfzahl"].items()},
        frueh_min={t: int(v) for t, v in roh_b["frueh_min"].items()},
        frueh_bis=zu_index(roh_b.get("frueh_bis", "07:00")),
        schluss_min={t: int(v) for t, v in roh_b["schluss_min"].items()},
        besetzung_min={
            t: [(zu_index(f["von"]), zu_index(f["bis"]), int(f["min"])) for f in fenster]
            for t, fenster in roh_b.get("besetzung_min", {}).items()
        },
        kopfzahl_toleranz=int(roh_b.get("kopfzahl_toleranz", 0)),
    )

    roh_r = _lies(ordner / "regeln.yaml")
    regeln = Regeln(
        gewichte={k: float(v) for k, v in roh_r["gewichte"].items()},
        ruhezeit_h=float(roh_r.get("ruhezeit_h", 11)),
        ruhezeit_min_h=float(roh_r.get("ruhezeit_min_h", 10)),
        stunden_toleranz_h=float(roh_r.get("stunden_toleranz_h", 0)),
        max_tage_in_folge=int(roh_r.get("max_tage_in_folge", 6)),
        samstage_frei_pro_x=int(roh_r.get("samstage_frei_pro_x", 0)),
    )
    return Stammdaten(mitarbeiter, schichten, bedarf, regeln)


@dataclass
class Wochenvorgabe:
    """Die Variablen, die vor jeder Woche eingegeben werden."""
    woche: str
    datum_von: str
    datum_bis: str = ""
    filiale: str = ""
    geschlossen: list[str] = field(default_factory=list)      # Feiertage
    abwesend: dict[str, dict[str, str]] = field(default_factory=dict)  # ma -> tag -> art
    fest: dict[str, dict[str, str]] = field(default_factory=dict)      # ma -> tag -> schicht|frei
    wunsch_frei: dict[str, list[str]] = field(default_factory=dict)
    wunsch_schicht: dict[str, dict[str, str]] = field(default_factory=dict)
    zusatz: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    soll_stunden: dict[str, float] = field(default_factory=dict)       # Override
    notiz: str = ""


def _tageliste(wert) -> list[str]:
    if wert in (None, "", "alle", "woche"):
        return list(TAGE)
    if isinstance(wert, str):
        wert = [wert]
    unbekannt = [t for t in wert if t not in TAGE]
    if unbekannt:
        raise ValueError(f"unbekannte Wochentage: {unbekannt}")
    return list(wert)


def lade_wochenvorgabe(pfad: pathlib.Path | str) -> Wochenvorgabe:
    roh = _lies(pathlib.Path(pfad))

    abwesend: dict[str, dict[str, str]] = {}
    for art in ("urlaub", "schule", "krank", "sonstige"):
        for ma, tage in (roh.get(art) or {}).items():
            for t in _tageliste(tage):
                abwesend.setdefault(ma, {})[t] = art

    fest = {ma: dict(v) for ma, v in (roh.get("fest") or {}).items()}
    wunsch_frei = {ma: _tageliste(v) for ma, v in (roh.get("wunsch_frei") or {}).items()}
    wunsch_schicht = {ma: dict(v) for ma, v in (roh.get("wunsch_schicht") or {}).items()}
    zusatz = {ma: {t: (v if isinstance(v, list) else [v]) for t, v in tage.items()}
              for ma, tage in (roh.get("zusatz") or {}).items()}

    return Wochenvorgabe(
        woche=roh["woche"],
        datum_von=str(roh["datum_von"]),
        datum_bis=str(roh.get("datum_bis", "")),
        filiale=roh.get("filiale", ""),
        geschlossen=_tageliste(roh["geschlossen"]) if roh.get("geschlossen") else [],
        abwesend=abwesend,
        fest=fest,
        wunsch_frei=wunsch_frei,
        wunsch_schicht=wunsch_schicht,
        zusatz=zusatz,
        soll_stunden={k: float(v) for k, v in (roh.get("soll_stunden") or {}).items()},
        notiz=roh.get("notiz", ""),
    )
