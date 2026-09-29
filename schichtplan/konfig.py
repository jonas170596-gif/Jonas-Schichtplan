"""Laden der Stammdaten (Mitarbeiter, Schichten, Bedarf, Regeln) und der
Wochenvorgabe."""
from __future__ import annotations

import datetime as _dt
import pathlib
from dataclasses import dataclass, field

import yaml

from .modelle import TAGE, Mitarbeiter, Schicht, zu_index

KONFIG_DIR = pathlib.Path("konfig")


@dataclass
class Feiertagsregeln:
    """Was sich an den Tagen rund um einen Feiertag aendert."""
    bundesland: str = "BW"
    vor_feiertag: dict[str, int] = field(default_factory=dict)
    nach_feiertag: dict[str, int] = field(default_factory=dict)


@dataclass
class Bedarf:
    offene_tage: list[str]
    oeffnung: dict[str, tuple[int, int]]          # tag -> (von, bis) als Slotindex
    kopfzahl: dict[str, int]
    frueh_min: dict[str, int]                     # Schichten mit Start <= frueh_bis
    frueh_bis: int
    schluss_min: dict[str, int]                   # Schichten, die bis Ladenschluss laufen
    besetzung_min: dict[str, list[tuple[int, int, int]]]   # tag -> [(von, bis, min)]
    kopfzahl_toleranz_unter: int = 0      # wie viele Koepfe unter Ziel straffrei
    kopfzahl_toleranz_ueber: int = 0      # wie viele Koepfe ueber Ziel straffrei
    wochenstunden_gesamt: float = 0.0     # 0 = kein Gesamtbudget
    wochenstunden_gesamt_toleranz: float = 5.0
    feiertagsregeln: Feiertagsregeln = field(default_factory=Feiertagsregeln)

    def min_am_slot(self, tag: str, slot: int) -> int:
        return max((m for v, b, m in self.besetzung_min.get(tag, []) if v <= slot < b),
                   default=0)


@dataclass
class Verteilungsregel:
    """Ueber mehrere Tage hinweg soll je Kategorie hoechstens/mindestens eine
    Schicht liegen - z. B. Rohwer freitags und samstags im Wechsel frueh/spaet."""
    tage: list[str]
    kategorien: list[str]


@dataclass
class Abdeckungsregel:
    """Eine Faehigkeit muss besetzt sein - entweder durchgehend waehrend der
    Oeffnungszeit oder in einem bestimmten Schichttyp."""
    faehigkeit: str
    min: int = 1
    kategorie: str | None = None
    startet_bis: int | None = None
    tage: list[str] | None = None
    grund: str = ""

    @property
    def zeitabdeckung(self) -> bool:
        return self.kategorie is None and self.startet_bis is None

    def gilt_am(self, tag: str) -> bool:
        return self.tage is None or tag in self.tage

    def passt(self, schicht) -> bool:
        if self.kategorie and schicht.kategorie != self.kategorie:
            return False
        if self.startet_bis is not None and schicht.von > self.startet_bis:
            return False
        return True


@dataclass
class Gruppenregel:
    """Mindest- oder Hoechstbesetzung aus einer Personengruppe.

    `min` und `max_gleichzeitig` schliessen sich nicht aus - eine Regel kann
    beides haben. Der Filter (kategorie/startet_bis/endet_ab) grenzt ein,
    welche Schichten mitzaehlen."""
    name: str
    gruppe: list[str]
    min: int = 0
    max_gleichzeitig: int | None = None
    kategorie: str | None = None
    startet_bis: int | None = None
    endet_ab: int | None = None
    tage: list[str] | None = None
    grund: str = ""

    def passt(self, tag: str, schicht) -> bool:
        if self.tage is not None and tag not in self.tage:
            return False
        if self.kategorie and schicht.kategorie != self.kategorie:
            return False
        if self.startet_bis is not None and schicht.von > self.startet_bis:
            return False
        if self.endet_ab is not None and schicht.bis < self.endet_ab:
            return False
        return True

    def gilt_am(self, tag: str) -> bool:
        return self.tage is None or tag in self.tage


@dataclass
class Regeln:
    gewichte: dict[str, float]
    ruhezeit_h: float = 11.0
    ruhezeit_min_h: float = 10.0
    stunden_toleranz_h: float = 0.0
    max_tage_in_folge: int = 6
    samstage_frei_pro_x: int = 0        # 0 = aus; sonst: 1 freier Samstag je X Wochen
    wechsel_max_pro_woche: int = 1      # kurze Wechsel (Spaet -> Frueh) je MA und Woche
    ausgleich_fenster_wochen: int = 4   # Fenster fuer den Frueh/Spaet-Ausgleich
    ausgleich_toleranz: int = 2         # erlaubtes Ungleichgewicht im Fenster


def effektiver_bedarf(grund: Bedarf, vorgabe) -> Bedarf:
    """Bedarf der Woche: Stammdaten, ueberschrieben von der Wochenvorgabe.

    Gebraucht fuer Tage, die aus dem Rahmen fallen - Heiligabend schliesst
    frueher, vor langen Wochenenden steht mehr Personal im Laden."""
    import dataclasses
    roh = vorgabe.bedarf
    if not roh:
        return grund
    neu = dataclasses.replace(
        grund,
        oeffnung=dict(grund.oeffnung),
        kopfzahl=dict(grund.kopfzahl),
        frueh_min=dict(grund.frueh_min),
        schluss_min=dict(grund.schluss_min),
        besetzung_min={k: list(v) for k, v in grund.besetzung_min.items()},
    )
    for tag, fenster in (roh.get("oeffnung") or {}).items():
        neu.oeffnung[tag] = (zu_index(fenster["von"]), zu_index(fenster["bis"]))
    for feld in ("kopfzahl", "frueh_min", "schluss_min"):
        for tag, wert in (roh.get(feld) or {}).items():
            getattr(neu, feld)[tag] = int(wert)
    for tag, fenster in (roh.get("besetzung_min") or {}).items():
        neu.besetzung_min[tag] = [
            (zu_index(f["von"]), zu_index(f["bis"]), int(f["min"])) for f in fenster]
    if roh.get("wochenstunden_gesamt") is not None:
        neu.wochenstunden_gesamt = float(roh["wochenstunden_gesamt"])
    return neu


@dataclass
class Stammdaten:
    mitarbeiter: dict[str, Mitarbeiter]
    schichten: dict[str, Schicht]
    bedarf: Bedarf
    regeln: Regeln
    gruppenbesetzung: list[Gruppenregel] = field(default_factory=list)
    unvertraeglich: list[Gruppenregel] = field(default_factory=list)
    abdeckung: list[Abdeckungsregel] = field(default_factory=list)
    faehigkeit_namen: dict[str, str] = field(default_factory=dict)
    verteilung: dict[str, list[Verteilungsregel]] = field(default_factory=dict)

    _kat_tabelle: dict[tuple[int, int], str] = field(default_factory=dict, repr=False)

    def kategorie_von(self, von: int, bis: int) -> str:
        """Kategorie einer Zeitspanne - aus dem Katalog, sonst nach Startzeit."""
        if not self._kat_tabelle:
            self._kat_tabelle.update({(s.von, s.bis): s.kategorie
                                      for s in self.schichten.values()})
        kat = self._kat_tabelle.get((von, bis))
        if kat is None:
            kat = ("frueh" if von <= self.bedarf.frueh_bis
                   else "spaet" if von >= zu_index("11:00") else "mittel")
            self._kat_tabelle[(von, bis)] = kat
        return kat


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
            bevorzugte_freie_tage=list(m.get("bevorzugte_freie_tage", [])),
            freie_tage_zusammenhaengend=bool(m.get("freie_tage_zusammenhaengend", False)),
            faehigkeiten=frozenset(m.get("faehigkeiten", [])),
            vermeiden=list(m.get("vermeiden", [])),
            schichtwunsch=dict(m.get("schichtwunsch") or {}),
            frueh_spaet_ausgleich=bool(m.get("frueh_spaet_ausgleich", True)),
            max_spaet_pro_woche=(int(m["max_spaet_pro_woche"])
                                 if m.get("max_spaet_pro_woche") is not None else None),
            springer=bool(m.get("springer", False)),
            praesenztage=(int(m["praesenztage"])
                          if m.get("praesenztage") is not None else None),
            abwesenheit_stunden={k: float(v) for k, v
                                 in (m.get("abwesenheit_stunden") or {}).items()},
            moeglichst_wenig=bool(m.get("moeglichst_wenig", False)),
            zaehlt_stundenbudget=bool(m.get("zaehlt_stundenbudget", True)),
            stunden_toleranz_h=(float(m["stunden_toleranz_h"])
                                if m.get("stunden_toleranz_h") is not None else None),
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
        kopfzahl_toleranz_unter=int(roh_b.get("kopfzahl_toleranz_unter", 0)),
        kopfzahl_toleranz_ueber=int(roh_b.get("kopfzahl_toleranz_ueber", 1)),
        wochenstunden_gesamt=float(roh_b.get("wochenstunden_gesamt", 0)),
        wochenstunden_gesamt_toleranz=float(roh_b.get("wochenstunden_gesamt_toleranz", 5)),
        feiertagsregeln=Feiertagsregeln(
            bundesland=(roh_b.get("feiertagsregeln") or {}).get("bundesland", "BW"),
            vor_feiertag={k: int(v) for k, v in
                          ((roh_b.get("feiertagsregeln") or {}).get("vor_feiertag") or {}).items()},
            nach_feiertag={k: int(v) for k, v in
                           ((roh_b.get("feiertagsregeln") or {}).get("nach_feiertag") or {}).items()},
        ),
    )

    roh_r = _lies(ordner / "regeln.yaml")
    regeln = Regeln(
        gewichte={k: float(v) for k, v in roh_r["gewichte"].items()},
        ruhezeit_h=float(roh_r.get("ruhezeit_h", 11)),
        ruhezeit_min_h=float(roh_r.get("ruhezeit_min_h", 10)),
        stunden_toleranz_h=float(roh_r.get("stunden_toleranz_h", 0)),
        max_tage_in_folge=int(roh_r.get("max_tage_in_folge", 6)),
        samstage_frei_pro_x=int(roh_r.get("samstage_frei_pro_x", 0)),
        wechsel_max_pro_woche=int(roh_r.get("wechsel_max_pro_woche", 1)),
        ausgleich_fenster_wochen=int(roh_r.get("ausgleich_fenster_wochen", 4)),
        ausgleich_toleranz=int(roh_r.get("ausgleich_toleranz", 2)),
    )
    roh_t = _lies(ordner / "team.yaml") if (ordner / "team.yaml").exists() else {}

    def _gruppenregel(r: dict, feld_min: str) -> Gruppenregel:
        unbekannt = [g for g in r["gruppe"] if g not in mitarbeiter]
        if unbekannt:
            raise ValueError(f"team.yaml/{r.get('name', '?')}: unbekannte Mitarbeiter {unbekannt}")
        return Gruppenregel(
            name=r.get("name", "unbenannt"),
            gruppe=list(r["gruppe"]),
            min=int(r.get("min", 0)),
            max_gleichzeitig=(int(r["max_gleichzeitig"])
                              if r.get("max_gleichzeitig") is not None else None),
            kategorie=r.get("kategorie"),
            startet_bis=zu_index(r["startet_bis"]) if r.get("startet_bis") else None,
            endet_ab=zu_index(r["endet_ab"]) if r.get("endet_ab") else None,
            tage=list(r["tage"]) if r.get("tage") else None,
            grund=r.get("grund", ""),
        )

    abdeckung = []
    for r in (roh_t.get("abdeckung") or []):
        abdeckung.append(Abdeckungsregel(
            faehigkeit=r["faehigkeit"],
            min=int(r.get("min", 1)),
            kategorie=r.get("kategorie"),
            startet_bis=zu_index(r["startet_bis"]) if r.get("startet_bis") else None,
            tage=list(r["tage"]) if r.get("tage") else None,
            grund=r.get("grund", ""),
        ))
    bekannt = {f for m in mitarbeiter.values() for f in m.faehigkeiten}
    for r in abdeckung:
        if r.faehigkeit not in bekannt:
            raise ValueError(f"team.yaml/abdeckung: Faehigkeit {r.faehigkeit!r} "
                             f"hat niemand - bekannt sind {sorted(bekannt)}")

    verteilung = {}
    for mid, m in roh_m["mitarbeiter"].items():
        regeln_v = [Verteilungsregel(tage=list(r["tage"]), kategorien=list(r["kategorien"]))
                    for r in (m.get("schicht_verteilung") or [])]
        if regeln_v:
            verteilung[mid] = regeln_v

    return Stammdaten(
        mitarbeiter, schichten, bedarf, regeln,
        gruppenbesetzung=[_gruppenregel(r, "min")
                          for r in (roh_t.get("gruppenbesetzung") or [])],
        unvertraeglich=[_gruppenregel(r, "max_gleichzeitig")
                        for r in (roh_t.get("unvertraeglich") or [])],
        abdeckung=abdeckung,
        faehigkeit_namen={k: (v or {}).get("name", k)
                          for k, v in (roh_t.get("faehigkeiten") or {}).items()},
        verteilung=verteilung,
    )


@dataclass
class Termin:
    """Fixer Termin, fuer den jemand die Schicht frueher beenden muss -
    z. B. die Teamleitersitzung am Dienstag ab 13:30."""
    name: str
    tag: str
    ab: int                       # Slotindex; die Schicht muss genau dann enden
    kandidaten: list[str]
    anzahl: int = 1
    abwechselnd: bool = False     # nicht dieselbe Person wie beim letzten Mal


@dataclass
class Schulplan:
    """Berufsschultage eines Azubis ueber das Schuljahr."""
    klasse: str = ""
    gruppe: str = ""
    quelle: str = ""
    gilt_bis: str = ""
    tage: dict[str, list[str]] = field(default_factory=dict)
    schulfrei: dict[str, str] = field(default_factory=dict)

    def fuer(self, woche: str) -> list[str] | None:
        """Schultage der Woche, [] wenn schulfrei, None wenn unbekannt."""
        if woche in self.tage:
            return list(self.tage[woche])
        if woche in self.schulfrei:
            return []
        return None if self.ausserhalb(woche) else []

    def ausserhalb(self, woche: str) -> bool:
        return bool(self.gilt_bis) and woche > self.gilt_bis


def lade_schulplaene(ordner: pathlib.Path | str = KONFIG_DIR) -> dict[str, Schulplan]:
    pfad = pathlib.Path(ordner) / "schulplan.yaml"
    if not pfad.exists():
        return {}
    roh = _lies(pfad)
    plaene = {}
    for mid, s in (roh.get("schulplaene") or {}).items():
        tage = {}
        for woche, wt in (s.get("tage") or {}).items():
            unbekannt = [d for d in wt if d not in TAGE]
            if unbekannt:
                raise ValueError(f"schulplan.yaml/{mid}/{woche}: unbekannte Tage {unbekannt}")
            tage[str(woche)] = list(wt)
        plaene[mid] = Schulplan(
            klasse=s.get("klasse", ""), gruppe=str(s.get("gruppe", "")),
            quelle=s.get("quelle", ""), gilt_bis=str(s.get("gilt_bis", "")),
            tage=tage,
            schulfrei={str(k): v for k, v in (s.get("schulfrei") or {}).items()},
        )
    return plaene


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
    termine: list[Termin] = field(default_factory=list)
    modus: str = "auto"                                 # auto | manuell
    bedarf: dict = field(default_factory=dict)          # Uebersteuerung je Woche
    regeln_aus: list[str] = field(default_factory=list)  # Regeln, die nicht gelten
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

    termine = [
        Termin(name=r.get("name", "Termin"), tag=r["tag"], ab=zu_index(r["ab"]),
               kandidaten=list(r["kandidaten"]), anzahl=int(r.get("anzahl", 1)),
               abwechselnd=bool(r.get("abwechselnd", False)))
        for r in (roh.get("termine") or [])
    ]
    for tm in termine:
        if tm.tag not in TAGE:
            raise ValueError(f"Termin {tm.name}: unbekannter Tag {tm.tag!r}")

    woche = roh["woche"]
    datum_von = str(roh["datum_von"])
    try:
        jahr, _, kw = woche.partition("-KW")
        montag = _dt.date.fromisocalendar(int(jahr), int(kw.split("-")[0]), 1)
    except (ValueError, TypeError):
        montag = None
    if montag and datum_von != montag.isoformat():
        raise ValueError(
            f"{pfad}: datum_von ist {datum_von}, der Montag von {woche} ist aber "
            f"{montag}. Ein falsches Datum verschiebt alle Feiertagsregeln - bitte "
            f"korrigieren (oder die Woche umbenennen).")

    modus = roh.get("modus", "auto")
    if modus not in ("auto", "manuell"):
        raise ValueError(f"modus muss 'auto' oder 'manuell' sein, nicht {modus!r}")

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
        termine=termine,
        modus=modus,
        bedarf=dict(roh.get("bedarf") or {}),
        regeln_aus=list(roh.get("regeln_aus") or []),
        notiz=roh.get("notiz", ""),
    )
