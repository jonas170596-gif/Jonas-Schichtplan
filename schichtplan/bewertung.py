"""Bewertung eines Plans: alle Regeln als gewichtete Strafpunkte.

Der Generator minimiert `Bewertung.punkte`. Fuer den Menschen gibt es
`pruefen()`, das dieselben Regeln als Klartextliste ausgibt.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .konfig import Stammdaten, Wochenvorgabe, effektiver_bedarf
from .modelle import ABWESEND, TAGE, TAG_LANG, Plan


@dataclass
class Befund:
    regel: str
    punkte: float
    text: str
    schwere: str = "hinweis"        # fehler | warnung | hinweis


@dataclass
class Bewertung:
    punkte: float = 0.0
    befunde: list[Befund] = field(default_factory=list)

    def fehler(self) -> list[Befund]:
        return [b for b in self.befunde if b.schwere == "fehler"]

    def warnungen(self) -> list[Befund]:
        return [b for b in self.befunde if b.schwere == "warnung"]


class Bewerter:
    """Haelt die vorberechneten Teile, damit der Solver schnell bleibt."""

    def __init__(self, stamm: Stammdaten, vorgabe: Wochenvorgabe,
                 vorwochen: list | None = None):
        self.stamm = stamm
        self.vorgabe = vorgabe
        self.vorwochen = vorwochen or []
        self.g = stamm.regeln.gewichte
        # Wochenvorgabe darf den Bedarf uebersteuern (Heiligabend & Co.)
        self.bedarf = b = effektiver_bedarf(stamm.bedarf, vorgabe)
        self.tage = [t for t in b.offene_tage if t not in vorgabe.geschlossen]
        self.slots = {t: list(range(*b.oeffnung[t])) for t in self.tage}
        self.min_kurve = {t: [b.min_am_slot(t, s) for s in self.slots[t]] for t in self.tage}
        # Oeffnungsfenster als Bitmaske je Tag; jede Schicht bekommt dieselbe
        # Darstellung, dann ist "Faehigkeit durchgehend besetzt" ein AND/OR.
        self.tagesmaske = {t: ((1 << len(self.slots[t])) - 1) << self.slots[t][0]
                           for t in self.tage if self.slots[t]}
        self.schichtmaske = {s.id: ((1 << (s.bis - s.von)) - 1) << s.von
                             for s in stamm.schichten.values()}
        self.soll_stunden = {
            mid: vorgabe.soll_stunden.get(mid, m.soll_stunden)
            for mid, m in stamm.mitarbeiter.items()
        }
        # Urlaub kuerzt nicht die Stunden pro Tag, sondern die Anzahl moeglicher
        # Tage. Wer 40 h auf 5 Tage hat und einen Tag Urlaub nimmt, arbeitet die
        # restlichen Tage normal weiter - genau so steht es in den Altplaenen.
        self.verfuegbare_tage = {
            mid: sum(1 for t in self.tage if t not in vorgabe.abwesend.get(mid, {}))
            for mid in stamm.mitarbeiter
        }
        self._hist_bilanz = self._historische_bilanz()
        self._samstagskonto = self._historisches_samstagskonto()
        self._fehltage = self._historische_fehltage()
        self.feiertagsumfeld = self._feiertagsumfeld()

    # ---- Konten aus der Historie (einmal vorberechnet) ------------------ #
    def _teilnehmer_samstag(self) -> list[str]:
        """Wer am Samstagsausgleich teilnimmt - wer den Tag ohnehin fest oder
        bevorzugt frei hat, verzerrt sonst den Durchschnitt."""
        return [mid for mid, m in self.stamm.mitarbeiter.items()
                if m.im_plan and m.aktiv and m.samstag_konto
                and "sa" not in m.feste_freie_tage
                and "sa" not in m.bevorzugte_freie_tage]

    def samstag_zwingend(self, mid: str) -> bool:
        """Lassen feste freie Tage und Solltage ueberhaupt einen freien
        Samstag zu? Wer fuenf Tage arbeiten soll und schon einen festen
        freien Tag hat, muss samstags ran - dann waere ein Rueckstand im
        Konto eine Forderung, die der Planer nie erfuellen kann."""
        m = self.stamm.mitarbeiter[mid]
        verfuegbar = len(set(self.stamm.bedarf.offene_tage) - set(m.feste_freie_tage))
        return verfuegbar - m.soll_tage <= 0

    def _historisches_samstagskonto(self) -> dict[str, tuple[int, int]]:
        """(moegliche Samstage, davon frei) je Mitarbeiter im Fenster."""
        fenster = self.stamm.regeln.samstag_fenster_wochen
        vor = self.vorwochen[-fenster:] if fenster else self.vorwochen
        konto = {}
        for mid in self.stamm.mitarbeiter:
            moeglich = frei = 0
            for w in vor:
                if "sa" not in w.offene_tage():
                    continue
                z = w.plan.get(mid, {}).get("sa")
                if z is None or z.art in ABWESEND:
                    continue
                moeglich += 1
                frei += not z.verwertbar
            konto[mid] = (moeglich, frei)
        return konto

    def _historische_fehltage(self) -> dict[str, float]:
        """Aufgelaufene Fehltage (unter Soll) im Ausgleichsfenster."""
        fenster = self.stamm.regeln.ausgleich_fenster_wochen
        vor = self.vorwochen[-(fenster - 1):] if fenster > 1 else []
        konto = {}
        for mid, m in self.stamm.mitarbeiter.items():
            summe = 0.0
            for w in vor:
                offen = w.offene_tage()
                reihe = w.plan.get(mid, {})
                if not reihe:
                    continue
                abwesend = sum(1 for t in offen if reihe[t].art in ABWESEND)
                moeglich = len(offen) - abwesend
                if moeglich <= 0:
                    continue
                tage = sum(1 for t in offen if reihe[t].verwertbar)
                if m.praesenztage is not None:
                    # Beim Azubi zaehlen Schultage als Praesenz mit, sonst
                    # erschiene jede Schulwoche als Fehltag.
                    gezaehlt = sum(1 for t in offen
                                   if reihe[t].art in m.abwesenheit_stunden)
                    soll = max(0, min(m.praesenztage - gezaehlt, moeglich))
                else:
                    soll = min(m.soll_tage, moeglich)
                summe += max(0, soll - tage)
            konto[mid] = summe
        return konto

    def _feiertagsumfeld(self) -> dict[str, dict[str, object]]:
        """Je Tag: welche Mindestwerte der Feiertag drumherum anhebt.

        Vor einem Feiertag wird abends mehr verkauft, danach muss morgens
        mehr aufgebaut werden. Der Samstag vor einem Feiertagsmontag zaehlt
        mit, weil sonntags ohnehin zu ist."""
        import datetime as dt
        from .feiertage import Kalender
        regeln = self.bedarf.feiertagsregeln
        if not (regeln.vor_feiertag or regeln.nach_feiertag):
            return {}
        try:
            montag = dt.date.fromisoformat(self.vorgabe.datum_von)
        except ValueError:
            return {}
        kalender = Kalender(regeln.bundesland)
        umfeld = {}
        for tag in self.tage:
            datum = montag + dt.timedelta(days=TAGE.index(tag))
            eintrag: dict[str, object] = {}
            if (name := kalender.vor_feiertag(datum)) and regeln.vor_feiertag:
                eintrag.update(regeln.vor_feiertag)
                eintrag["anlass"] = f"vor {name}"
            if (name := kalender.nach_feiertag(datum)) and regeln.nach_feiertag:
                eintrag.update(regeln.nach_feiertag)
                anlass = eintrag.get("anlass")
                eintrag["anlass"] = f"{anlass} / nach {name}" if anlass else f"nach {name}"
            if eintrag:
                umfeld[tag] = eintrag
        return umfeld

    def mindestwert(self, tag: str, feld: str, grundwert: int) -> tuple[int, str]:
        eintrag = self.feiertagsumfeld.get(tag)
        if not eintrag or feld not in eintrag:
            return grundwert, ""
        return max(grundwert, int(eintrag[feld])), str(eintrag.get("anlass", ""))

    def _maske(self, schicht) -> int:
        m = self.schichtmaske.get(schicht.id)
        if m is None:      # Schicht aus einem Altplan, nicht im Katalog
            m = ((1 << (schicht.bis - schicht.von)) - 1) << schicht.von
            self.schichtmaske[schicht.id] = m
        return m

    def _historische_bilanz(self) -> dict[str, tuple[int, int, int, int]]:
        """(frueh, spaet, Schichten gesamt, Wochen) der Vorwochen.

        Aendert sich waehrend der Suche nicht und wird deshalb einmal
        vorberechnet."""
        fenster = self.stamm.regeln.ausgleich_fenster_wochen
        vor = self.vorwochen[-(fenster - 1):] if fenster > 1 else []
        bilanz = {}
        for mid in self.stamm.mitarbeiter:
            frueh = spaet = gesamt = 0
            for w in vor:
                for z in w.plan.get(mid, {}).values():
                    if z.verwertbar:
                        kat = self.stamm.kategorie_von(z.von, z.bis)
                        frueh += kat == "frueh"
                        spaet += kat == "spaet"
                        gesamt += 1
            bilanz[mid] = (frueh, spaet, gesamt, len(vor))
        return bilanz

    def _ziel(self, mid: str) -> tuple[float, int]:
        """(Zielstunden, Zieltage) fuer diese Woche.

        Mit `praesenztage` zaehlen bestimmte Abwesenheiten als Tag mit - beim
        Azubi die Berufsschule: vier Schichten plus ein Schultag sind seine
        fuenf Tage, und der Schultag deckt einen Teil des Wochensolls ab."""
        m = self.stamm.mitarbeiter[mid]
        moeglich = self.verfuegbare_tage[mid]
        if m.praesenztage is not None:
            abwesend = self.vorgabe.abwesend.get(mid, {})
            gezaehlt = [art for t, art in abwesend.items()
                        if t in self.tage and art in m.abwesenheit_stunden]
            tage = max(0, min(m.praesenztage - len(gezaehlt), moeglich))
            stunden = self.soll_stunden[mid] - sum(m.abwesenheit_stunden[a]
                                                   for a in gezaehlt)
            return max(0.0, stunden), tage
        tage = min(m.soll_tage, moeglich)
        pro_tag = self.soll_stunden[mid] / m.soll_tage if m.soll_tage else 0.0
        return pro_tag * tage, tage

    # ------------------------------------------------------------------ #
    def bewerte(self, plan: Plan, detail: bool = False) -> Bewertung:
        erg = Bewertung()
        add = self._sammler(erg, detail)
        self._besetzung(plan, add)
        self._team(plan, add)
        self._faehigkeiten(plan, add)
        self._ausgleich(plan, add)
        self._konten(plan, add)
        self._termine(plan, add)
        self._arbeitszeit(plan, add)
        self._stundenbudget(plan, add)
        self._wuensche(plan, add)
        self._qualitaet(plan, add)
        return erg

    def _sammler(self, erg: Bewertung, detail: bool):
        aus = set(self.vorgabe.regeln_aus)

        def add(regel: str, faktor: float, text: str = "", schwere: str = "hinweis"):
            if faktor <= 0 or regel in aus:
                return
            p = self.g.get(regel, 0.0) * faktor
            erg.punkte += p
            if detail and text:
                erg.befunde.append(Befund(regel, p, text, schwere))
        return add

    # ---- Besetzung ---------------------------------------------------- #
    def _besetzung(self, plan: Plan, add):
        b = self.bedarf
        for t in self.tage:
            zellen = [r[t] for r in plan.zellen.values() if r[t].arbeitet]
            koepfe = len(zellen)
            ziel, _ = self.mindestwert(t, "kopfzahl", b.kopfzahl.get(t, koepfe))
            if koepfe < ziel:
                weg = max(0, ziel - koepfe - b.kopfzahl_toleranz_unter)
                wort = "nur"
            else:
                weg = max(0, koepfe - ziel - b.kopfzahl_toleranz_ueber)
                wort = "schon"
            if weg:
                add("kopfzahl", weg,
                    f"{TAG_LANG[t]}: {wort} {koepfe} Mitarbeiter statt {ziel}",
                    "fehler" if weg > 1 else "warnung")

            frueh = sum(1 for z in zellen if z.schicht.von <= b.frueh_bis)
            noetig, anlass = self.mindestwert(t, "frueh_min", b.frueh_min.get(t, 0))
            if frueh < noetig:
                add("frueh_besetzung", noetig - frueh,
                    f"{TAG_LANG[t]}: nur {frueh} Fruehschichten, {noetig} noetig"
                    + (f" ({anlass})" if anlass else ""), "fehler")
            elif frueh > noetig:
                # Wer um 6 Uhr nicht gebraucht wird, fehlt mittags. Ein
                # spaeterer Start (8-16 statt 6-14) deckt die Spitze besser ab.
                add("frueh_ueber", frueh - noetig,
                    f"{TAG_LANG[t]}: {frueh} Fruehschichten, noetig sind {noetig} - "
                    f"ein spaeterer Start waere moeglich"
                    if frueh - noetig > 1 else "")

            schluss_zeit = b.oeffnung[t][1]
            schluss = sum(1 for z in zellen if z.schicht.bis >= schluss_zeit)
            noetig, anlass = self.mindestwert(t, "schluss_min", b.schluss_min.get(t, 0))
            if schluss < noetig:
                add("schluss_besetzung", noetig - schluss,
                    f"{TAG_LANG[t]}: nur {schluss} bis Ladenschluss, {noetig} noetig"
                    + (f" ({anlass})" if anlass else ""), "fehler")

            belegt = [0] * len(self.slots[t])
            start = self.slots[t][0]
            for z in zellen:
                s = z.schicht
                for i in range(max(s.von, start) - start,
                               min(s.bis, start + len(belegt)) - start):
                    belegt[i] += 1
            unter = ueber = 0
            luecken = []
            for i, (ist, soll) in enumerate(zip(belegt, self.min_kurve[t])):
                if ist < soll:
                    unter += soll - ist
                    luecken.append(start + i)
                elif soll and ist > soll + 1:
                    ueber += ist - soll - 1
            if unter:
                from .modelle import zu_zeit
                add("besetzung_unter", unter,
                    f"{TAG_LANG[t]}: Unterbesetzung ab {zu_zeit(luecken[0])} "
                    f"({unter} Personenhalbstunden)", "fehler")
            add("besetzung_ueber", ueber)

    # ---- Team: wer muss da sein, wer nicht zusammen --------------------- #
    def _team(self, plan: Plan, add):
        for regel in self.stamm.gruppenbesetzung:
            for tag in self.tage:
                if not regel.gilt_am(tag):
                    continue
                # Wer an dem Tag im Urlaub, krank oder in der Schule ist, kann
                # die Regel nicht erfuellen. Der Anspruch sinkt entsprechend,
                # sonst stuende bei jedem Urlaub eine unerfuellbare Forderung
                # im Plan und der Solver wuerde sie gegen alles andere abwaegen.
                verfuegbar = sum(
                    1 for mid in regel.gruppe
                    if tag not in self.vorgabe.abwesend.get(mid, {})
                    and self.stamm.mitarbeiter[mid].im_plan)
                noetig = min(regel.min, verfuegbar)
                da = sum(1 for mid in regel.gruppe
                         if (z := plan.zellen.get(mid, {}).get(tag)) is not None
                         and z.arbeitet and regel.passt(tag, z.schicht))
                if da < noetig:
                    add("gruppenbesetzung", noetig - da,
                        f"{TAG_LANG[tag]}: {regel.name} - {da} von {noetig} besetzt"
                        + (f" ({regel.grund})" if regel.grund else ""), "fehler")

        for regel in self.stamm.unvertraeglich:
            grenze = regel.max_gleichzeitig
            if grenze is None:
                continue
            for tag in self.tage:
                if not regel.gilt_am(tag):
                    continue
                namen = [self.stamm.mitarbeiter[mid].name for mid in regel.gruppe
                         if (z := plan.zellen.get(mid, {}).get(tag)) is not None
                         and z.arbeitet and regel.passt(tag, z.schicht)]
                if len(namen) > grenze:
                    add("unvertraeglich", len(namen) - grenze,
                        f"{TAG_LANG[tag]}: {regel.name} - {' und '.join(namen)} "
                        f"gleichzeitig eingeteilt", "fehler")

    def _faehigkeiten(self, plan: Plan, add):
        from .modelle import zu_zeit
        for regel in self.stamm.abdeckung:
            name = self.stamm.faehigkeit_namen.get(regel.faehigkeit, regel.faehigkeit)
            for tag in self.tage:
                if not regel.gilt_am(tag):
                    continue
                koennen = [
                    z.schicht for mid, reihe in plan.zellen.items()
                    if (z := reihe[tag]).arbeitet
                    and self.stamm.mitarbeiter[mid].kann(regel.faehigkeit)
                ]
                if not regel.zeitabdeckung:
                    da = sum(1 for s in koennen if regel.passt(s))
                    if da < regel.min:
                        add("faehigkeit", regel.min - da,
                            f"{TAG_LANG[tag]}: {name} nicht besetzt "
                            f"({da} von {regel.min})"
                            + (f" - {regel.grund}" if regel.grund else ""), "fehler")
                    continue
                if regel.min == 1:
                    gedeckt = 0
                    for s in koennen:
                        gedeckt |= self._maske(s)
                    offen = self.tagesmaske[tag] & ~gedeckt
                    if not offen:
                        continue
                    luecke = bin(offen).count("1")
                    erste = (offen & -offen).bit_length() - 1
                else:
                    luecke, erste = 0, None
                    for slot in self.slots[tag]:
                        da = sum(1 for s in koennen if s.deckt(slot))
                        if da < regel.min:
                            luecke += regel.min - da
                            if erste is None:
                                erste = slot
                if luecke:
                    add("faehigkeit", luecke,
                        f"{TAG_LANG[tag]}: {name} ab {zu_zeit(erste)} nicht besetzt "
                        f"({luecke} Personenhalbstunden)", "fehler")

    # ---- Frueh/Spaet-Ausgleich ueber mehrere Wochen --------------------- #
    def _kategorie(self, von: int, bis: int) -> str:
        return self.stamm.kategorie_von(von, bis)

    def schichtbilanz(self, plan: Plan, mid: str) -> tuple[int, int, int, int]:
        """(frueh, spaet, Schichten gesamt, Wochen) inklusive der Planwoche."""
        frueh, spaet, gesamt, wochen = self._hist_bilanz.get(mid, (0, 0, 0, 0))
        for z in plan.zellen.get(mid, {}).values():
            if z.arbeitet:
                frueh += z.schicht.kategorie == "frueh"
                spaet += z.schicht.kategorie == "spaet"
                gesamt += 1
        return frueh, spaet, gesamt, wochen + 1

    def frueh_spaet_bilanz(self, plan: Plan, mid: str) -> tuple[int, int, int]:
        """(frueh, spaet, Wochen im Fenster) inklusive der geplanten Woche."""
        frueh, spaet, _, wochen = self.schichtbilanz(plan, mid)
        return frueh, spaet, wochen

    def _ausgleich(self, plan: Plan, add):
        if self.stamm.regeln.ausgleich_fenster_wochen <= 1:
            return
        toleranz = self.stamm.regeln.ausgleich_toleranz
        for mid, m in self.stamm.mitarbeiter.items():
            if not (m.im_plan and m.aktiv):
                continue
            frueh, spaet, gesamt, wochen = self.schichtbilanz(plan, mid)

            if m.spaet_anteil is not None:
                # Fester Zielanteil statt 50/50 - beim Azubi soll rund ein
                # Viertel der Schichten spaet sein, gemessen ueber das Fenster.
                if gesamt:
                    ziel = m.spaet_anteil * gesamt
                    add("spaet_anteil", max(0.0, abs(spaet - ziel) - toleranz),
                        f"{m.name}: {spaet} von {gesamt} Schichten spaet in "
                        f"{wochen} Wochen, Ziel {ziel:.1f} "
                        f"({m.spaet_anteil:.0%})"
                        if abs(spaet - ziel) > toleranz else "", "warnung")
                continue

            if not m.frueh_spaet_ausgleich or frueh + spaet == 0:
                continue
            weg = max(0, abs(frueh - spaet) - toleranz)
            add("frueh_spaet_ausgleich", weg,
                f"{m.name}: {frueh} Frueh gegen {spaet} Spaet in {wochen} Wochen "
                f"(Toleranz {toleranz})" if weg else "", "warnung")

    # ---- Konten: freie Samstage und Fehltage --------------------------- #
    def samstagskonto(self, plan: Plan | None = None
                      ) -> dict[str, tuple[int, int, float]]:
        """(moeglich, frei, Soll nach Gruppenschnitt) je Teilnehmer.

        Der Gruppenschnitt ist die Quote freier Samstage ueber alle
        Teilnehmer zusammen. Wer darunter liegt, hat Rueckstand."""
        teilnehmer = self._teilnehmer_samstag()
        roh = {}
        for mid in teilnehmer:
            moeglich, frei = self._samstagskonto.get(mid, (0, 0))
            if plan is not None and "sa" in self.tage:
                z = plan.zellen.get(mid, {}).get("sa")
                if z is not None and z.art not in ABWESEND:
                    moeglich += 1
                    frei += not z.arbeitet
            roh[mid] = (moeglich, frei)
        gesamt_m = sum(m for m, _ in roh.values())
        gesamt_f = sum(f for _, f in roh.values())
        quote = gesamt_f / gesamt_m if gesamt_m else 0.0
        return {mid: (m, f, quote * m) for mid, (m, f) in roh.items()}

    def _konten(self, plan: Plan, add):
        for mid, (moeglich, frei, soll) in self.samstagskonto(plan).items():
            if moeglich < 3:          # zu duenne Datenlage fuer eine Aussage
                continue
            if self.samstag_zwingend(mid):
                continue              # unerfuellbar, siehe samstag_zwingend
            m = self.stamm.mitarbeiter[mid]
            rueckstand = soll - frei
            add("samstag_konto",
                max(0.0, rueckstand - self.stamm.regeln.samstag_toleranz),
                f"{m.name}: {frei} von {moeglich} Samstagen frei, "
                f"im Schnitt waeren es {soll:.1f}"
                if rueckstand > self.stamm.regeln.samstag_toleranz else "",
                "warnung")

        for mid, m in self.stamm.mitarbeiter.items():
            if not (m.im_plan and m.aktiv) or m.nur_obergrenze:
                continue
            _, soll_t = self._ziel(mid)
            tage = sum(1 for z in plan.zellen[mid].values() if z.arbeitet)
            konto = self._fehltage.get(mid, 0.0) + max(0, soll_t - tage)
            # Wer eine hohe Einsatzprioritaet hat, soll seine Tage eher
            # bekommen - bei ihm wiegt derselbe Rueckstand schwerer.
            weg = max(0.0, konto - self.stamm.regeln.fehltage_toleranz)
            add("fehltage_konto", weg * m.einsatzprioritaet,
                f"{m.name}: {konto:.0f} Fehltage unter Soll in "
                f"{self.stamm.regeln.ausgleich_fenster_wochen} Wochen"
                if weg else "", "warnung")

    def _termine(self, plan: Plan, add):
        for tm in self.vorgabe.termine:
            if tm.tag not in self.tage:
                continue
            passend = [mid for mid in tm.kandidaten
                       if (z := plan.zellen.get(mid, {}).get(tm.tag)) is not None
                       and z.arbeitet and z.schicht.bis == tm.ab]
            if len(passend) < tm.anzahl:
                from .modelle import zu_zeit
                add("termin", tm.anzahl - len(passend),
                    f"{TAG_LANG[tm.tag]}: {tm.name} ab {zu_zeit(tm.ab)} - "
                    f"{len(passend)} von {tm.anzahl} Kandidaten enden passend", "fehler")
            if tm.abwechselnd:
                letzter = self._letzter_terminhalter(tm)
                if letzter is not None and letzter in passend:
                    add("termin_wechsel", 1,
                        f"{tm.name}: {self.stamm.mitarbeiter[letzter].name} war schon "
                        f"beim letzten Mal dran", "warnung")

    def _letzter_terminhalter(self, tm) -> str | None:
        """Wer den Termin zuletzt wahrgenommen hat - erkannt am Schichtende."""
        for w in reversed(self.vorwochen):
            treffer = [mid for mid in tm.kandidaten
                       if (z := w.plan.get(mid, {}).get(tm.tag)) is not None
                       and z.verwertbar and z.bis == tm.ab]
            if len(treffer) == 1:
                return treffer[0]
            if treffer:
                return None
        return None

    # ---- Gesamtstundenbudget -------------------------------------------- #
    def gesamtbudget(self) -> float:
        """Wochenbudget, um ausgefallene Sollstunden (Urlaub) gekuerzt."""
        b = self.bedarf
        if not b.wochenstunden_gesamt:
            return 0.0
        ausfall = 0.0
        for mid, m in self.stamm.mitarbeiter.items():
            if not (m.im_plan and m.aktiv and m.zaehlt_stundenbudget) or m.moeglichst_wenig:
                continue
            ziel, _ = self._ziel(mid)
            ausfall += max(0.0, self.soll_stunden[mid] - ziel)
        return max(0.0, b.wochenstunden_gesamt - ausfall)

    def gesamtstunden(self, plan: Plan) -> float:
        return sum(z.stunden
                   for mid, reihe in plan.zellen.items()
                   if self.stamm.mitarbeiter[mid].zaehlt_stundenbudget
                   for z in reihe.values())

    def _stundenbudget(self, plan: Plan, add):
        ziel = self.gesamtbudget()
        if not ziel:
            return
        ist = self.gesamtstunden(plan)
        weg = max(0.0, abs(ist - ziel) - self.stamm.bedarf.wochenstunden_gesamt_toleranz)
        add("gesamtstunden", weg,
            f"Gesamt {ist:.1f} h statt {ziel:.1f} h "
            f"(+/-{self.bedarf.wochenstunden_gesamt_toleranz:.0f} h, ohne Azubi)"
            if weg else "", "warnung")

    # ---- Arbeitszeit --------------------------------------------------- #
    def _arbeitszeit(self, plan: Plan, add):
        for mid, m in self.stamm.mitarbeiter.items():
            if not m.im_plan or not m.aktiv:
                continue
            reihe = plan.zellen[mid]
            stunden = sum(z.stunden for z in reihe.values())
            tage = sum(1 for z in reihe.values() if z.arbeitet)
            if self.verfuegbare_tage[mid] == 0:
                continue
            if m.moeglichst_wenig:
                # Leichter Gegendruck: die Reserve wird nur eingesetzt, wenn
                # die Besetzung es rechtfertigt. Das Soll unten begrenzt sie
                # nach oben, nach unten ist es frei.
                add("sparsam_einsetzen", stunden,
                    f"{m.name}: {stunden:.1f} h (Reserve)" if stunden else "")

            soll_h, soll_t = self._ziel(mid)
            toleranz = (m.stunden_toleranz_h if m.stunden_toleranz_h is not None
                        else self.stamm.regeln.stunden_toleranz_h)
            if m.nur_obergrenze:
                # Soll ist eine Obergrenze, kein Ziel: weniger ist in Ordnung.
                weg_h = max(0.0, stunden - soll_h - toleranz)
                weg_t = max(0, tage - soll_t)
            else:
                weg_h = max(0.0, abs(stunden - soll_h) - toleranz)
                weg_t = abs(tage - soll_t)
            add("wochenstunden", weg_h,
                f"{m.name}: {stunden:.1f} h statt {soll_h:.1f} h" if weg_h >= 2 else "",
                "warnung")
            add("arbeitstage", weg_t,
                f"{m.name}: {tage} Arbeitstage statt {soll_t}" if weg_t >= 2 else "")
            if tage > m.max_tage:
                add("max_tage", tage - m.max_tage,
                    f"{m.name}: {tage} Arbeitstage, erlaubt sind {m.max_tage}", "fehler")

            if m.praesenztage is not None:
                # Schichten plus gezaehlte Abwesenheiten (Berufsschule) ergeben
                # die Praesenztage - beim Azubi sind das immer genau fuenf.
                abwesend = self.vorgabe.abwesend.get(mid, {})
                gezaehlt = sum(1 for t_, art in abwesend.items()
                               if t_ in self.tage and art in m.abwesenheit_stunden)
                ist = tage + gezaehlt
                add("praesenztage", abs(ist - m.praesenztage),
                    f"{m.name}: {ist} Praesenztage ({tage} Schichten + {gezaehlt} "
                    f"Schule) statt {m.praesenztage}"
                    if ist != m.praesenztage else "",
                    "fehler" if ist > m.praesenztage else "warnung")

            folge = max_folge = 0
            for t in TAGE:      # ueber alle Wochentage, nicht nur die offenen -
                zelle = reihe.get(t)   # ein Feiertag unterbricht die Serie
                folge = folge + 1 if (zelle is not None and zelle.arbeitet) else 0
                max_folge = max(max_folge, folge)
            if max_folge > m.max_tage_in_folge:
                add("tage_in_folge", max_folge - m.max_tage_in_folge,
                    f"{m.name}: {max_folge} Arbeitstage am Stueck", "warnung")

    # ---- Wuensche ------------------------------------------------------ #
    def _wuensche(self, plan: Plan, add):
        for mid, tage in self.vorgabe.wunsch_frei.items():
            if mid not in plan.zellen:
                continue
            for t in tage:
                if t in self.tage and plan.zellen[mid][t].arbeitet:
                    add("wunsch_frei", 1,
                        f"{self.stamm.mitarbeiter[mid].name}: Wunschfrei {TAG_LANG[t]} "
                        f"nicht erfuellt", "warnung")
        for mid, tage in self.vorgabe.wunsch_schicht.items():
            if mid not in plan.zellen:
                continue
            for t, sid in tage.items():
                z = plan.zellen[mid].get(t)
                if t in self.tage and not (z and z.arbeitet and z.schicht.id == sid):
                    add("wunsch_schicht", 1,
                        f"{self.stamm.mitarbeiter[mid].name}: Wunschschicht {sid} am "
                        f"{TAG_LANG[t]} nicht erfuellt", "warnung")

        for mid, tage in self.vorgabe.wunsch_kategorie.items():
            if mid not in plan.zellen:
                continue
            for t, kat in tage.items():
                z = plan.zellen[mid].get(t)
                if t in self.tage and not (z and z.arbeitet
                                           and z.schicht.kategorie == kat):
                    add("wunsch_schicht", 1,
                        f"{self.stamm.mitarbeiter[mid].name}: {TAG_LANG[t]} als "
                        f"{kat} gewuenscht", "warnung")

        for mid, tage in self.vorgabe.arbeitet.items():
            if mid not in plan.zellen:
                continue
            for t in tage:
                z = plan.zellen[mid].get(t)
                if t in self.tage and not (z and z.arbeitet):
                    add("soll_arbeiten", 1,
                        f"{self.stamm.mitarbeiter[mid].name}: soll {TAG_LANG[t]} "
                        f"arbeiten, ist aber nicht eingeteilt", "fehler")

    # ---- Qualitaet ------------------------------------------------------ #
    def _qualitaet(self, plan: Plan, add):
        ruhe_slots = int(self.stamm.regeln.ruhezeit_h * 2)
        ruhe_hart = int(self.stamm.regeln.ruhezeit_min_h * 2)
        for mid, m in self.stamm.mitarbeiter.items():
            if not m.im_plan:
                continue
            reihe = plan.zellen[mid]
            wechsel = []
            for a, b_ in zip(self.tage, self.tage[1:]):
                za, zb = reihe[a], reihe[b_]
                if za.arbeitet and zb.arbeitet:
                    # self.tage enthaelt keine geschlossenen Tage, zwei Eintraege
                    # koennen also mehr als einen Kalendertag auseinanderliegen.
                    abstand = TAGE.index(b_) - TAGE.index(a)
                    pause = (48 * abstand - za.schicht.bis) + zb.schicht.von
                    if pause < ruhe_hart:
                        add("ruhezeit_verletzung", (ruhe_hart - pause) / 2,
                            f"{m.name}: nur {pause / 2:.1f} h Ruhe zwischen "
                            f"{TAG_LANG[a]} und {TAG_LANG[b_]} "
                            f"(Untergrenze {self.stamm.regeln.ruhezeit_min_h} h)", "fehler")
                    if pause < ruhe_slots:
                        wechsel.append((a, b_, pause))
            # Spaet -> Frueh: einmal pro Woche geduldet, jeder weitere teuer
            grenze = self.stamm.regeln.wechsel_max_pro_woche
            for i, (a, b_, pause) in enumerate(wechsel):
                if i < grenze:
                    add("wechsel", 1,
                        f"{m.name}: kurzer Wechsel {TAG_LANG[a]} -> {TAG_LANG[b_]} "
                        f"({pause / 2:.1f} h Ruhe)")
                else:
                    add("wechsel_ueber_limit", 1,
                        f"{m.name}: {i + 1}. kurzer Wechsel in der Woche "
                        f"({TAG_LANG[a]} -> {TAG_LANG[b_]}, {pause / 2:.1f} h Ruhe) - "
                        f"erlaubt ist {grenze}", "warnung")

            for tag in m.bevorzugte_freie_tage:
                if tag in self.tage and reihe[tag].arbeitet:
                    add("bevorzugter_freier_tag", 1,
                        f"{m.name}: {TAG_LANG[tag]} ist eigentlich frei")

            for tag, z in reihe.items():
                if not z.arbeitet:
                    continue
                if z.schicht.kategorie in m.vermeiden or z.schicht.id in m.vermeiden:
                    add("vermiedene_schicht", 1,
                        f"{m.name}: {z.schicht.label} am {TAG_LANG[tag]} "
                        f"(soll vermieden werden)", "warnung")
                wunsch = m.schichtwunsch.get(tag)
                if wunsch and z.schicht.kategorie != wunsch:
                    add("schichtwunsch", 1,
                        f"{m.name}: {TAG_LANG[tag]} {z.schicht.kategorie} "
                        f"statt {wunsch}")

            for regel in self.stamm.verteilung.get(mid, []):
                kats = [reihe[tag].schicht.kategorie for tag in regel.tage
                        if tag in self.tage and reihe[tag].arbeitet]
                if len(kats) < len(regel.kategorien):
                    continue
                fehl = sum(max(0, 1 - kats.count(k)) for k in regel.kategorien)
                fehl += sum(1 for k in kats if k not in regel.kategorien)
                add("schicht_verteilung", fehl,
                    f"{m.name}: {'/'.join(TAG_LANG[t][:2] for t in regel.tage)} sollen "
                    f"{' und '.join(regel.kategorien)} sein, sind {'/'.join(kats)}"
                    if fehl else "", "warnung")

            if m.freie_tage_zusammenhaengend:
                frei = [TAGE.index(t_) for t_ in self.tage
                        if reihe[t_].art == "frei"]
                if len(frei) >= 2:
                    # Ein geschlossener Tag zwischen zwei freien Tagen trennt sie
                    # nicht - der Mitarbeiter hat trotzdem am Stueck frei.
                    geschlossen = {TAGE.index(t_) for t_ in TAGE
                                   if t_ not in self.tage}
                    bloecke = 1
                    for x, y in zip(frei, frei[1:]):
                        if any(i not in geschlossen for i in range(x + 1, y)):
                            bloecke += 1
                    add("freie_tage_zusammenhaengend", bloecke - 1,
                        f"{m.name}: freie Tage liegen in {bloecke} Bloecken "
                        f"({', '.join(TAG_LANG[TAGE[i]] for i in frei)})"
                        if bloecke > 1 else "")
            if m.stamm_schichten:
                fremd = sum(1 - m.stamm_schichten.get(z.schicht.id, 0.0)
                            for z in reihe.values() if z.arbeitet)
                add("stammschicht", fremd)
            if m.max_spaet_pro_woche is not None:
                spaet = sum(1 for z in reihe.values()
                            if z.arbeitet and z.schicht.kategorie == "spaet")
                add("zu_viel_spaet", max(0, spaet - m.max_spaet_pro_woche),
                    f"{m.name}: {spaet} Spaetschichten, hoechstens "
                    f"{m.max_spaet_pro_woche} vorgesehen"
                    if spaet > m.max_spaet_pro_woche else "", "warnung")

            if not m.springer:
                verschieden = {z.schicht.id for z in reihe.values() if z.arbeitet}
                add("zersplitterung", max(0, len(verschieden) - 2))



def pruefen(plan: Plan, stamm: Stammdaten, vorgabe: Wochenvorgabe,
            vorwochen: list | None = None) -> Bewertung:
    return Bewerter(stamm, vorgabe, vorwochen).bewerte(plan, detail=True)
