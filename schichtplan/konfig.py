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
    pause_minuten: int = 30            # je Schicht, wird von der Summe abgezogen
    kategorieprofil: dict[str, dict[str, int]] = field(default_factory=dict)
    feiertagsregeln: Feiertagsregeln = field(default_factory=Feiertagsregeln)

    @property
    def pause_h(self) -> float:
        return self.pause_minuten / 60

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
    samstag_fenster_wochen: int = 0     # Fenster fuers Samstagskonto, 0 = ganze Historie
    samstag_toleranz: float = 1.0       # so viele Samstage Rueckstand bleiben straffrei
    fehltage_toleranz: float = 1.0      # so viele Fehltage im Fenster bleiben straffrei
    max_wochenstunden: float = 48.0     # Obergrenze je MA und Woche (ArbZG)
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
            vorname=m.get("vorname", ""),
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
            nur_obergrenze=bool(m.get("nur_obergrenze", False)),
            spaet_anteil=(float(m["spaet_anteil"])
                          if m.get("spaet_anteil") is not None else None),
            bevorzugte_kategorie=m.get("bevorzugte_kategorie", ""),
            einsatzprioritaet=float(m.get("einsatzprioritaet", 1.0)),
            samstag_konto=bool(m.get("samstag_konto", True)),
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
        pause_minuten=int(roh_b.get("pause_minuten", 30)),
        kategorieprofil={t_: {k: int(v) for k, v in p_.items()}
                         for t_, p_ in (roh_b.get("kategorieprofil") or {}).items()},
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
        samstag_fenster_wochen=int(roh_r.get("samstag_fenster_wochen", 0)),
        samstag_toleranz=float(roh_r.get("samstag_toleranz", 1)),
        fehltage_toleranz=float(roh_r.get("fehltage_toleranz", 1)),
        max_wochenstunden=float(roh_r.get("max_wochenstunden", 48)),
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
class Kalendereintrag:
    ma: str
    von: _dt.date
    bis: _dt.date
    art: str            # siehe ARTEN_KALENDER

    def tage_in(self, montag: _dt.date) -> list[str]:
        """Wochentagskuerzel, die in die Woche ab `montag` fallen."""
        return [TAGE[i] for i in range(6)
                if self.von <= montag + _dt.timedelta(days=i) <= self.bis]


@dataclass
class Kalender:
    """Urlaubs- und Wunschkalender, wie er an der Wand haengt."""
    quelle: str = ""
    eintraege: list[Kalendereintrag] = field(default_factory=list)
    zu_klaeren: list[dict] = field(default_factory=list)

    def fuer_woche(self, montag: _dt.date) -> list[tuple[Kalendereintrag, list[str]]]:
        treffer = []
        for e in self.eintraege:
            tage = e.tage_in(montag)
            if tage:
                treffer.append((e, tage))
        return treffer

    def offene_fragen(self, montag: _dt.date) -> list[dict]:
        ende = montag + _dt.timedelta(days=5)
        return [f for f in self.zu_klaeren
                if montag <= _dt.date.fromisoformat(str(f["tag"])) <= ende]


ARTEN_KALENDER = ("urlaub", "frei", "wunsch_frei", "wunsch_frueh",
                  "frei_oder_frueh", "arbeitet")


def lade_kalender(pfad: pathlib.Path | str = "daten/kalender.yaml",
                  mitarbeiter: dict[str, Mitarbeiter] | None = None) -> Kalender:
    pfad = pathlib.Path(pfad)
    if not pfad.exists():
        return Kalender()
    roh = _lies(pfad)
    nach_vorname = {}
    for mid, m in (mitarbeiter or {}).items():
        if m.vorname:
            schluessel = m.vorname.casefold()
            if schluessel in nach_vorname:
                raise ValueError(
                    f"Vorname {m.vorname!r} gehoert zu {nach_vorname[schluessel]} "
                    f"und zu {mid} - im Kalender waere er nicht aufloesbar")
            nach_vorname[schluessel] = mid

    def _wer(e: dict) -> str:
        """Eintrag einem Mitarbeiter zuordnen - ueber Vorname oder Kuerzel."""
        if "vorname" in e:
            mid = nach_vorname.get(str(e["vorname"]).casefold())
            if mid is None:
                raise ValueError(
                    f"{pfad}: Vorname {e['vorname']!r} steht in keinen Stammdaten. "
                    f"Bekannt sind: {', '.join(sorted(nach_vorname))}")
            return mid
        mid = e["ma"]
        if mitarbeiter and mid not in mitarbeiter:
            raise ValueError(f"{pfad}: unbekanntes Kuerzel {mid!r}")
        return mid

    def _lies_eintrag(e: dict) -> Kalendereintrag:
        art = e["art"]
        if art not in ARTEN_KALENDER:
            raise ValueError(f"{pfad}: unbekannte Art {art!r} - erlaubt sind "
                             f"{', '.join(ARTEN_KALENDER)}")
        von = _dt.date.fromisoformat(str(e.get("tag") or e["von"]))
        bis = _dt.date.fromisoformat(str(e.get("tag") or e["bis"]))
        if bis < von:
            raise ValueError(f"{pfad}: {von} bis {bis} laeuft rueckwaerts")
        return Kalendereintrag(ma=_wer(e), von=von, bis=bis, art=art)

    eintraege = [_lies_eintrag(e) for e in (roh.get("eintraege") or [])]
    zu_klaeren = []
    for f in (roh.get("zu_klaeren") or []):
        eintrag = dict(f)
        vermutet = eintrag.get("vermutet")
        if vermutet:
            eintrag["vermutet"] = {**vermutet, "ma": _wer(vermutet)}
        zu_klaeren.append(eintrag)
    return Kalender(quelle=roh.get("quelle", ""), eintraege=eintraege,
                    zu_klaeren=zu_klaeren)


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
    wunsch_kategorie: dict[str, dict[str, str]] = field(default_factory=dict)
    arbeitet: dict[str, list[str]] = field(default_factory=dict)   # hebt feste freie Tage auf
    nur_schichten: dict[str, dict[str, list[str]]] = field(default_factory=dict)
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
    wunsch_kategorie = {ma: dict(v)
                        for ma, v in (roh.get("wunsch_kategorie") or {}).items()}
    arbeitet = {ma: _tageliste(v) for ma, v in (roh.get("arbeitet") or {}).items()}
    nur_schichten = {ma: {tag: list(s) for tag, s in tage.items()}
                     for ma, tage in (roh.get("nur_schichten") or {}).items()}
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
        wunsch_kategorie=wunsch_kategorie,
        arbeitet=arbeitet,
        nur_schichten=nur_schichten,
        zusatz=zusatz,
        soll_stunden={k: float(v) for k, v in (roh.get("soll_stunden") or {}).items()},
        termine=termine,
        modus=modus,
        bedarf=dict(roh.get("bedarf") or {}),
        regeln_aus=list(roh.get("regeln_aus") or []),
        notiz=roh.get("notiz", ""),
    )
