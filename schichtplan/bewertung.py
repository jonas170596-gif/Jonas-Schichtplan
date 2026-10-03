"""Bewertung eines Plans: alle Regeln als gewichtete Strafpunkte.

Der Generator minimiert `Bewertung.punkte`. Fuer den Menschen gibt es
`pruefen()`, das dieselben Regeln als Klartextliste ausgibt.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .konfig import Stammdaten, Wochenvorgabe, effektiver_bedarf
from .modelle import ABWESEND, TAGE, TAG_LANG, Plan, zu_zeit


@dataclass
class Befund:
    regel: str
    punkte: float
    text: str
    schwere: str = "hinweis"        # fehler | warnung | hinweis


# Schweregrade in der Reihenfolge, in der sie ausgegeben werden: Kuerzel,
# Ueberschrift, und was der Grad fuer den Aushang bedeutet.
SCHWEREGRADE = (
    ("fehler",  "FEHLER",  "so nicht aushaengen"),
    ("warnung", "WARNUNG", "geht, ist aber ein Zugestaendnis"),
    ("hinweis", "HINWEIS", "nur zur Kenntnis"),
)


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
        # Laengste Schicht, die der/die MA ueberhaupt arbeiten darf. C. Kurz hat
        # 20 h auf 3 Tage im Vertrag, ihre laengste erlaubte Schicht sind aber
        # 6 h - sie kann ihr Soll gar nicht erreichen. Ohne diese Deckelung
        # wuerde ihr Stundenkonto Woche fuer Woche weiter ins Minus laufen und
        # sie stuende dauerhaft ganz oben auf der Liste, obwohl das nichts mit
        # der Planung zu tun hat.
        self.laengste_schicht = {
            mid: max((stamm.schichten[sid].dauer_h for sid in m.erlaubte_schichten
                      if sid in stamm.schichten), default=0.0)
            for mid, m in stamm.mitarbeiter.items()
        }
        # Urlaub kuerzt nicht die Stunden pro Tag, sondern die Anzahl moeglicher
        # Tage. Wer 40 h auf 5 Tage hat und einen Tag Urlaub nimmt, arbeitet die
        # restlichen Tage normal weiter - genau so steht es in den Altplaenen.
        self.verfuegbare_tage = {
            mid: sum(1 for t in self.tage if self._einsetzbar(mid, t))
            for mid in stamm.mitarbeiter
        }
        self._hist_bilanz = self._historische_bilanz()
        self._samstagskonto = self._historisches_samstagskonto()
        self._fehltage = self._historische_fehltage()
        self._minusstunden = self._historische_minusstunden()
        self._letzte_seite = self._letzte_wochenseite()
        self.feiertagsumfeld = self._feiertagsumfeld()

    def _einsetzbar(self, mid: str, tag: str) -> bool:
        """Kann der/die MA an dem Tag ueberhaupt eingeteilt werden?

        Nicht nur Urlaub sperrt einen Tag, auch ein fester freier Tag und ein
        im Kalender zugesagtes 'frei'. Wuerde man die mitzaehlen, stuende die
        Person dauerhaft mit einem Fehltag da, obwohl der Tag abgesprochen ist.
        `arbeitet` (Pflicht) und `kann_arbeiten` (nur Angebot) heben einen
        festen freien Tag fuer diese Woche wieder auf."""
        m = self.stamm.mitarbeiter[mid]
        if tag in self.vorgabe.abwesend.get(mid, {}):
            return False
        if self.vorgabe.fest.get(mid, {}).get(tag) in ("frei", "Frei", False):
            return False
        if tag in m.feste_freie_tage \
                and tag not in self.vorgabe.arbeitet.get(mid, []) \
                and tag not in self.vorgabe.kann_arbeiten.get(mid, []):
            return False
        return True

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
        if m.samstag_moeglich:
            # Ausdruecklich zugelassen: dann darf sie dafuer unter ihre
            # Solltage fallen. Rohwer hat Mittwoch fest frei und fuenf
            # Solltage - ohne diese Ausnahme kaeme sie nie an einen freien
            # Samstag, und das Konto waere eine Dauerforderung ins Leere.
            return False
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

    def _letzte_wochenseite(self) -> dict[tuple[str, int], str]:
        """Welche Seite der Wechselblock zuletzt hatte - fuer den Takt.

        Gesucht wird die juengste Woche, in der die Person an den Tagen des
        Blocks ueberhaupt gearbeitet hat und einheitlich auf einer Seite war.
        Urlaubs- und Mischwochen unterbrechen den Takt nicht."""
        letzte = {}
        for mid, regeln in self.stamm.wochenwechsel.items():
            for i, regel in enumerate(regeln):
                for w in reversed(self.vorwochen):
                    offen = w.offene_tage()
                    seiten = set()
                    for tag in regel.tage:
                        z = w.plan.get(mid, {}).get(tag)
                        if tag in offen and z is not None and z.verwertbar:
                            kat = self.stamm.kategorie_von(z.von, z.bis)
                            seiten.add("frueh" if kat == "frueh" else "spaet")
                    if len(seiten) == 1:
                        letzte[(mid, i)] = seiten.pop()
                        break
        return letzte

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

    def _kontogruppe(self) -> list[str]:
        """Wer beim Fairnessvergleich mitzaehlt.

        Die Reserve (U. Kurz) hat ihr Soll als Obergrenze und baut deshalb
        per Definition Minusstunden auf; der Azubi haengt an `praesenztage`
        und der Berufsschule. Beide wuerden den Schnitt verzerren."""
        return [mid for mid, m in self.stamm.mitarbeiter.items()
                if m.im_plan and m.aktiv and not m.nur_obergrenze
                and not m.moeglichst_wenig and m.praesenztage is None
                and m.soll_stunden > 0]

    def _historische_minusstunden(self) -> dict[str, float]:
        """Aufgelaufenes Stundenkonto (Soll minus Ist) im Ausgleichsfenster.

        Vorzeichenbehaftet: eine Woche mit Ueberstunden zahlt eine Woche mit
        Minusstunden zurueck, wie auf einem echten Arbeitszeitkonto. Gerechnet
        wird brutto, also in Anwesenheitsstunden - so wie `soll_stunden`."""
        fenster = self.stamm.regeln.ausgleich_fenster_wochen
        vor = self.vorwochen[-(fenster - 1):] if fenster > 1 else []
        konto = {}
        for mid in self._kontogruppe():
            m = self.stamm.mitarbeiter[mid]
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
                # Urlaub kuerzt das Wochensoll anteilig - genau wie in _ziel.
                tage = min(m.soll_tage, moeglich)
                pro_tag = m.soll_stunden / m.soll_tage if m.soll_tage else 0.0
                pro_tag = min(pro_tag, self.laengste_schicht.get(mid) or pro_tag)
                soll = pro_tag * tage
                summe += soll - sum(z.stunden for z in reihe.values())
            konto[mid] = summe
        return konto

    def stundenkonto(self, plan: Plan | None = None) -> dict[str, float]:
        """Minusstunden je Mitarbeiter, Historie plus laufende Woche."""
        konto = dict(self._minusstunden)
        if plan is None:
            return konto
        for mid in konto:
            soll_h, _ = self._ziel(mid)
            ist = sum(z.stunden for z in plan.zellen.get(mid, {}).values())
            konto[mid] += soll_h - ist
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
                        # Die Mittelschicht zaehlt auf der Fruehseite mit: wer
                        # um 8 anfaengt, hat den Abend frei, und genau darum
                        # geht es beim Ausgleich.
                        frueh += kat in ("frueh", "mittel")
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
        pro_tag = min(pro_tag, self.laengste_schicht.get(mid) or pro_tag)
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
        if detail:
            self._ueberhang(plan, add)
            self._stammdaten_pruefung(add)
        return erg

    def _sammler(self, erg: Bewertung, detail: bool):
        aus = set(self.vorgabe.regeln_aus)

        def add(regel: str, faktor: float, text: str = "", schwere: str = "hinweis",
                nur_melden: bool = False):
            """Strafpunkte vergeben - oder mit nur_melden nur berichten.

            Letzteres fuer Befunde, an denen der Planer nichts aendern kann:
            Punkte dafuer wuerden ihn nur dazu bringen, an anderer Stelle
            Unsinn zu bauen, um sie loszuwerden."""
            if regel in aus or (faktor <= 0 and not nur_melden):
                return
            p = 0.0 if nur_melden else self.g.get(regel, 0.0) * faktor
            erg.punkte += p
            if detail and text:
                erg.befunde.append(Befund(regel, p, text, schwere))
        return add

    # ---- Besetzung ---------------------------------------------------- #
    def _besetzung(self, plan: Plan, add):
        b = self.bedarf
        # Der Azubi zaehlt Mo-Do wahlweise mit: normalerweise steht er als zweite
        # Mittelschicht zusaetzlich im Laden, bei einem Engpass macht er die
        # Mittelschicht auch allein. Beides ist recht, deshalb ist die Kopfzahl
        # an diesen Tagen eine Spanne. Fr und Sa zaehlt er fest mit - so sind
        # die Zielkopfzahlen aus den Altplaenen gemittelt.
        mitarbeiter = self.stamm.mitarbeiter
        for t in self.tage:
            zellen = [r[t] for r in plan.zellen.values() if r[t].arbeitet]
            extra = {mid for mid, m in mitarbeiter.items() if not m.zaehlt_am(t)}
            koepfe = sum(1 for mid, r in plan.zellen.items()
                         if r[t].arbeitet and mid not in extra)
            koepfe_max = sum(1 for r in plan.zellen.values() if r[t].arbeitet)
            ziel, _ = self.mindestwert(t, "kopfzahl", b.kopfzahl.get(t, koepfe))
            if koepfe < ziel:
                # Wer wahlweise mitzaehlt, darf die Luecke schliessen - aber
                # lieber kommt jemand mit Vertrag. Montags ist die zweite
                # Mittelschicht fuer C. Kurz gedacht, der Azubi obendrauf.
                springt_ein = min(ziel, koepfe_max) - koepfe
                add("azubi_fuellt_luecke", springt_ein,
                    f"{TAG_LANG[t]}: {springt_ein} Platz vom Azubi gefuellt - "
                    f"mit Vertrag waere jemand anderes dran" if springt_ein else "")
                weg = max(0, ziel - min(ziel, koepfe_max) - b.kopfzahl_toleranz_unter)
                # Manche Tage duerfen notfalls mit einem Kopf weniger laufen -
                # dafuer muessen dann aber ein paar Leute frueher anfangen.
                # Samstags heisst das: statt sieben auch sechs, aber zwei davon
                # spaetestens um 9 statt erst um 10 oder 11.
                notfall = b.kopfzahl_notfalls.get(t)
                if notfall and weg:
                    weniger, anzahl, start_bis = notfall
                    erlassen = min(weg, weniger)
                    weg -= erlassen
                    frueh_start = sum(1 for z in zellen
                                      if b.frueh_bis < z.schicht.von <= start_bis)
                    fehlt = max(0, anzahl - frueh_start)
                    add("notfall_frueher_start", fehlt,
                        f"{TAG_LANG[t]}: laeuft mit {koepfe} statt {ziel} "
                        f"Mitarbeitern - dann muessen {anzahl} spaetestens um "
                        f"{zu_zeit(start_bis)} anfangen, es sind {frueh_start}"
                        if fehlt else "", "fehler")
                regel, wort = "kopfzahl", "nur"
            else:
                weg = max(0, koepfe - ziel - b.kopfzahl_toleranz_ueber)
                regel, wort = "kopfzahl_ueber", "schon"
            if weg:
                add(regel, weg,
                    f"{TAG_LANG[t]}: {wort} {koepfe} Mitarbeiter statt {ziel}",
                    "fehler" if weg > 1 else "warnung")

            frueh = sum(1 for z in zellen if z.schicht.von <= b.frueh_bis)
            noetig, anlass = self.mindestwert(t, "frueh_min", b.frueh_min.get(t, 0))
            if frueh < noetig:
                add("frueh_besetzung", noetig - frueh,
                    f"{TAG_LANG[t]}: nur {frueh} Fruehschichten, {noetig} noetig"
                    + (f" ({anlass})" if anlass else ""), "fehler")
            elif frueh > noetig and not b.kategorieprofil.get(t):
                # Wer um 6 Uhr nicht gebraucht wird, fehlt mittags. Ein
                # spaeterer Start (8-16 statt 6-14) deckt die Spitze besser ab.
                # Wo ein Kategorieprofil steht, regelt das die Verteilung.
                add("frueh_ueber", frueh - noetig,
                    f"{TAG_LANG[t]}: {frueh} Fruehschichten, noetig sind {noetig} - "
                    f"ein spaeterer Start waere moeglich"
                    if frueh - noetig > 1 else "")

            profil = b.kategorieprofil.get(t)
            if profil and t not in self.feiertagsumfeld:
                # Mo-Do steht das Tagesgeruest fest: zwei frueh, eine mittel,
                # zwei spaet. Wer zusaetzlich kommt (der Azubi), faellt nicht
                # darunter - deshalb wird nur ein Fehlbestand bestraft, kein
                # Ueberhang.
                ist = {"frueh": 0, "mittel": 0, "spaet": 0}
                voll = {"frueh": 0, "mittel": 0, "spaet": 0}
                for mid, r in plan.zellen.items():
                    if not r[t].arbeitet:
                        continue
                    voll[r[t].schicht.kategorie] += 1
                    if mid not in extra:
                        ist[r[t].schicht.kategorie] += 1
                for kat, soll in profil.items():
                    if voll[kat] < soll:
                        # Der Azubi darf die Mittelschicht auch allein machen -
                        # gemessen wird die Luecke deshalb an allen Anwesenden.
                        add("kategorieprofil", soll - voll[kat],
                            f"{TAG_LANG[t]}: {voll[kat]} statt {soll} "
                            f"{kat}-Schichten", "warnung")
                    elif ist[kat] > soll and kat != "mittel":
                        add("kategorieprofil", ist[kat] - soll,
                            f"{TAG_LANG[t]}: {ist[kat]} statt {soll} "
                            f"{kat}-Schichten", "warnung")

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
                    # Eine Person ueber der Kurve ist frei: nachmittags verlangt
                    # sie nur zwei, die Zielkopfzahl aber fuenf Koepfe am Tag -
                    # die muessen irgendwo stehen. Ab der zweiten ueberzaehligen
                    # Person ist es eine Verkaeuferstunde, die keiner braucht.
                    ueber += ist - soll - 1
            if unter:
                add("besetzung_unter", unter,
                    f"{TAG_LANG[t]}: Unterbesetzung ab {zu_zeit(luecken[0])} "
                    f"({unter} Personenhalbstunden)", "fehler")
            add("besetzung_ueber", ueber)

            # Niemand steht allein im Laden. Die Besetzungskurve verlangt
            # ueberall mindestens zwei, aber sie ist weich und laesst sich
            # gegen andere Regeln eintauschen. Allein im Laden ist dagegen
            # nie verhandelbar - weder fuer die Kasse noch fuer die Pause.
            allein = [start + i for i, ist in enumerate(belegt) if ist == 1]
            if allein:
                add("allein", len(allein),
                    f"{TAG_LANG[t]}: ab {zu_zeit(allein[0])} nur eine Person "
                    f"im Laden ({len(allein)} Halbstunden)", "fehler")

    # ---- Team: wer muss da sein, wer nicht zusammen --------------------- #
    def _team(self, plan: Plan, add):
        for regel in self.stamm.gruppenbesetzung:
            for tag in self.tage:
                if not regel.gilt_am(tag):
                    continue
                # Wer an dem Tag nicht einsetzbar ist, kann die Regel nicht
                # erfuellen - Urlaub, Schule, ein fester freier Tag oder ein im
                # Kalender zugesagtes "frei". Der Anspruch sinkt entsprechend,
                # sonst stuende eine unerfuellbare Forderung im Plan und der
                # Solver wuerde sie gegen alles andere abwaegen. In KW45 hat
                # Kurka den Montag frei - dann kann der Montagsanker an dem Tag
                # nicht gelten.
                verfuegbar = sum(1 for mid in regel.gruppe
                                 if self.stamm.mitarbeiter[mid].im_plan
                                 and self._einsetzbar(mid, tag))
                noetig = min(regel.min, verfuegbar)
                if noetig < regel.min:
                    fehlen = [self.stamm.mitarbeiter[mid].name for mid in regel.gruppe
                              if not self._einsetzbar(mid, tag)]
                    add("gruppenbesetzung", 0,
                        f"{TAG_LANG[tag]}: {regel.name} entfaellt - "
                        f"{', '.join(fehlen)} nicht einsetzbar",
                        "hinweis", nur_melden=True)
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
        """(frueh, spaet, Schichten gesamt, Wochen) inklusive der Planwoche.

        Die Mittelschicht zaehlt auf der Fruehseite mit."""
        frueh, spaet, gesamt, wochen = self._hist_bilanz.get(mid, (0, 0, 0, 0))
        for z in plan.zellen.get(mid, {}).values():
            if z.arbeitet:
                frueh += z.schicht.kategorie in ("frueh", "mittel")
                spaet += z.schicht.kategorie == "spaet"
                gesamt += 1
        return frueh, spaet, gesamt, wochen + 1

    def frueh_spaet_bilanz(self, plan: Plan, mid: str) -> tuple[int, int, int]:
        """(frueh, spaet, Wochen im Fenster) inklusive der geplanten Woche."""
        frueh, spaet, _, wochen = self.schichtbilanz(plan, mid)
        return frueh, spaet, wochen

    def _beide_seiten(self, mid: str) -> bool:
        """Hat der/die MA ueberhaupt Schichten auf beiden Seiten?"""
        m = self.stamm.mitarbeiter[mid]
        ids = set(m.erlaubte_schichten)
        for liste in m.zusatzschichten.values():
            ids.update(liste)
        kats = {self.stamm.schichten[s].kategorie
                for s in ids if s in self.stamm.schichten}
        return bool(kats & {"frueh", "mittel"}) and "spaet" in kats

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
            if not self._beide_seiten(mid):
                # Wer gar keine Spaetschicht im Katalog hat, kann nichts
                # ausgleichen. Seit die Mittelschicht auf der Fruehseite
                # mitzaehlt, betrifft das C. Kurz: 8-14, 8-13, 8-16 - alles
                # frueh, nie spaet. Das waere eine Dauerwarnung ohne Ausweg.
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
            # Quadratisch, nicht linear. Linear ist das Verschieben eines
            # Samstags ein Nullsummenspiel: wer ihn abgibt, verliert genau so
            # viel, wie der andere gewinnt - und weil der Schnitt dabei steigt,
            # kostet die gerechtere Verteilung sogar mehr. Quadratisch zaehlt
            # der groesste Rueckstand am schwersten, und jede Angleichung senkt
            # die Summe.
            offen = max(0.0, rueckstand - self.stamm.regeln.samstag_toleranz)
            add("samstag_konto", offen * offen * m.samstagprioritaet,
                f"{m.name}: {frei} von {moeglich} Samstagen frei, "
                f"im Schnitt waeren es {soll:.1f}"
                if rueckstand > self.stamm.regeln.samstag_toleranz else "",
                "warnung")

        # Fehltage und Minusstunden werden gegen den Teamschnitt gemessen,
        # nicht gegen das eigene Soll. In einer Woche ohne Urlaub gibt die
        # Mannschaft mehr Tage her, als der Laden braucht - dann muss jemand
        # zurueckstecken, und die Frage ist nur, wen es trifft. Absolute
        # Strafpunkte wuerden den Planer stattdessen dazu bringen, einen
        # ueberzaehligen Kopf in den Laden zu stellen.
        gruppe = self._kontogruppe()
        fenster = self.stamm.regeln.ausgleich_fenster_wochen

        gruppe = [mid for mid in gruppe
                  if any(self._einsetzbar(mid, t) for t in self.tage)]
        fehltage = {}
        for mid in gruppe:
            _, soll_t = self._ziel(mid)
            tage = sum(1 for z in plan.zellen[mid].values() if z.arbeitet)
            fehltage[mid] = self._fehltage.get(mid, 0.0) + max(0, soll_t - tage)
        schnitt_t = sum(fehltage.values()) / len(fehltage) if fehltage else 0.0
        for mid, konto in fehltage.items():
            m = self.stamm.mitarbeiter[mid]
            # Wer eine hohe Einsatzprioritaet hat, soll seine Tage eher
            # bekommen - bei ihm wiegt derselbe Rueckstand schwerer.
            weg = max(0.0, konto - schnitt_t - self.stamm.regeln.fehltage_toleranz)
            add("fehltage_konto", weg * m.einsatzprioritaet,
                f"{m.name}: {konto:.1f} Fehltage in {fenster} Wochen, "
                f"im Schnitt sind es {schnitt_t:.1f}" if weg else "", "warnung")

        # Wer die ganze Woche abwesend ist, kann an seinem Konto nichts aendern
        # und verzerrt nur den Schnitt. In KW44 waeren das Kurka, Kohl und
        # Menzler mit drei Wochen Urlaub, waehrend der Rest Ueberstunden macht.
        # Die Reserven zusammen: nur was ueber die Luecke hinausgeht, kostet
        # jemandem mit Vertrag einen Tag. Einzeln geprueft wuerde es doppelt
        # zaehlen, sobald eine Aushilfe neben U. Kurz steht.
        reserve = [mid for mid, m in self.stamm.mitarbeiter.items()
                   if m.im_plan and m.aktiv and m.moeglichst_wenig]
        if reserve:
            gesamt = sum(1 for mid in reserve
                         for z in plan.zellen.get(mid, {}).values() if z.arbeitet)
            bedarf = self.reservebedarf()
            namen = ", ".join(self.stamm.mitarbeiter[mid].name for mid in reserve
                              if any(z.arbeitet
                                     for z in plan.zellen.get(mid, {}).values()))
            add("reserve_ueber_bedarf", max(0, gesamt - bedarf),
                f"Reserve {gesamt} Tage, aufzufuellen waren {bedarf} ({namen}) - "
                f"dafuer faellt jemand mit Vertrag unter sein Soll"
                if gesamt > bedarf else "", "warnung")

        stunden = {mid: k for mid, k in self.stundenkonto(plan).items()
                   if any(self._einsetzbar(mid, t) for t in self.tage)}
        schnitt_h = sum(stunden.values()) / len(stunden) if stunden else 0.0
        for mid, konto in stunden.items():
            m = self.stamm.mitarbeiter[mid]
            weg = max(0.0, konto - schnitt_h
                      - self.stamm.regeln.minusstunden_toleranz_h)
            add("minusstunden_konto", weg * m.stundenprioritaet,
                f"{m.name}: {konto:+.1f} h Stundenkonto in {fenster} Wochen, "
                f"im Schnitt sind es {schnitt_h:+.1f} h" if weg else "", "warnung")

    def _kurzgrenze(self, mid: str) -> float:
        """Kuerzeste Schicht, die fuer diese Person noch sinnvoll ist.

        Im Plan steht die volle Schicht - ob jemand frueher geht, entscheidet
        sich im Betrieb, nicht auf dem Papier. Der Faktor ist an zwei
        Beispielen geeicht: 6-12 ist fuer eine 40-Stunden-Kraft zu kurz,
        11-18 am Samstag in Ordnung. Nach oben begrenzt die kuerzeste Schicht,
        die der/die MA ohnehin gewohnt ist - C. Kurz arbeitet mittwochs 8-13,
        das soll kein Befund sein."""
        m = self.stamm.mitarbeiter[mid]
        tagwert = (self.soll_stunden[mid] / m.soll_tage) if m.soll_tage else 0.0
        grenze = 0.85 * tagwert
        gewohnt = [self.stamm.schichten[sid].dauer_h for sid in m.stamm_schichten
                   if sid in self.stamm.schichten]
        if gewohnt:
            grenze = min(grenze, min(gewohnt))
        return max(self.stamm.regeln.min_schicht_h, grenze)

    def _stammdaten_pruefung(self, add):
        """Vertragsstunden, die die gewohnten Schichten gar nicht hergeben.

        C. Kurz hat 20 h auf 3 Tage im Vertrag, arbeitet aber 8-14 und 8-13 -
        hoechstens 18 h. Ihr Stundenkonto laeuft deshalb jede Woche weiter ins
        Minus, ohne dass der Planer etwas falsch macht, und sie steht dauerhaft
        oben auf der Liste. Das ist in den Stammdaten zu klaeren, nicht im Plan -
        deshalb ohne Punkte."""
        for mid, m in self.stamm.mitarbeiter.items():
            if not (m.im_plan and m.aktiv and m.soll_tage and m.stamm_schichten):
                continue
            if m.nur_obergrenze or m.praesenztage is not None:
                continue
            laengste = max((self.stamm.schichten[sid].dauer_h
                            for sid in m.stamm_schichten
                            if sid in self.stamm.schichten), default=0.0)
            moeglich = laengste * m.soll_tage
            if moeglich and moeglich < self.soll_stunden[mid] - 0.5:
                add("stammdaten", 1,
                    f"{m.name}: Vertrag {self.soll_stunden[mid]:.0f} h auf "
                    f"{m.soll_tage} Tage, die gewohnten Schichten geben hoechstens "
                    f"{moeglich:.1f} h her - das Stundenkonto laeuft dauerhaft ins "
                    f"Minus. In konfig/mitarbeiter.yaml klaeren.",
                    "hinweis", nur_melden=True)

    def tagesbilanz(self) -> tuple[int, int]:
        """(Plaetze im Laden, Personentage aus den Vertraegen) dieser Woche.

        Plaetze sind die Zielkopfzahlen aller offenen Tage; wer nicht gegen
        die Kopfzahl zaehlt (Azubi), bringt seinen Platz selbst mit. Die
        Differenz ist die Luecke, die die Reserve fuellen soll."""
        plaetze = sum(self.mindestwert(t, "kopfzahl",
                                       self.bedarf.kopfzahl.get(t, 0))[0]
                      for t in self.tage)
        vertrag = 0
        for mid, m in self.stamm.mitarbeiter.items():
            if not (m.im_plan and m.aktiv) or m.moeglichst_wenig:
                continue
            # Nur Tage, an denen der/die MA einen der Plaetze belegt. Der Azubi
            # belegt Mo-Do keinen - dort kommt er obendrauf oder springt ein.
            zaehlend = sum(1 for t in self.tage if m.zaehlt_am(t))
            vertrag += min(self._ziel(mid)[1], zaehlend)
        return plaetze, vertrag

    def reservebedarf(self) -> int:
        """Tage, die die Reserve auffuellen muss, damit der Laden voll ist."""
        plaetze, vertrag = self.tagesbilanz()
        return max(0, plaetze - vertrag)

    def _ueberhang(self, plan: Plan, add):
        """Wer den zusaetzlichen freien Tag bekommt - und wer sonst in Frage kaeme.

        In einer Woche ohne Urlaub gibt die Mannschaft mehr Personentage her,
        als der Laden braucht. Dann ist nicht die Frage, ob jemand unter sein
        Soll faellt, sondern wer. Der Planer entscheidet das ueber die Konten;
        der Hinweis macht die Entscheidung sichtbar und nennt die naechsten
        Kandidaten, damit man sie ueberstimmen kann. Kostet keine Punkte -
        es gibt nichts zu reparieren."""
        nachfrage, angebot = self.tagesbilanz()
        reserve = 0
        fehlt: dict[str, int] = {}
        for mid, m in self.stamm.mitarbeiter.items():
            if not (m.im_plan and m.aktiv):
                continue
            if all(not m.zaehlt_am(t) for t in self.tage):
                continue               # steht durchweg zusaetzlich im Laden
            tage = sum(1 for z in plan.zellen[mid].values() if z.arbeitet)
            if m.moeglichst_wenig:
                reserve += tage        # belegt Plaetze, ohne Soll zu haben
                continue
            soll_t = min(self._ziel(mid)[1], len(self.tage))
            if tage < soll_t:
                fehlt[mid] = soll_t - tage
        if angebot + reserve <= nachfrage and not fehlt:
            return

        konto = self.stundenkonto(plan)
        def beschriftung(mid, zusatz=""):
            stand = konto.get(mid)
            stand = f"{stand:+.1f} h" if stand is not None else "kein Konto"
            return f"{self.stamm.mitarbeiter[mid].name} ({stand}{zusatz})"

        rang = sorted(konto, key=lambda x: konto[x])
        offen = [beschriftung(x) for x in rang if x not in fehlt]
        vergeben = [beschriftung(x, f", {fehlt[x]} Tage" if fehlt[x] > 1 else "")
                    for x in sorted(fehlt, key=lambda x: -konto.get(x, 0))]

        text = (f"Der Laden hat {nachfrage} Plaetze, die Mannschaft gibt "
                f"{angebot} Personentage her")
        if reserve:
            text += f" und die Reserve belegt {reserve} davon"
        text += f". {sum(fehlt.values())} Tage unter Soll sind vergeben"
        text += (": " + ", ".join(vergeben)) if vergeben else ""
        if offen:
            text += (". Als naechstes waeren nach Stundenkonto dran: "
                     + ", ".join(offen[:3]))
        add("ueberhang", 1, text, "hinweis", nur_melden=True)

    def _termine(self, plan: Plan, add):
        for tm in self.vorgabe.termine:
            if tm.tag not in self.tage:
                continue
            passend = [mid for mid in tm.kandidaten
                       if (z := plan.zellen.get(mid, {}).get(tm.tag)) is not None
                       and z.arbeitet and z.schicht.bis == tm.ab]
            if len(passend) < tm.anzahl:
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
        """Sollstunden der Woche - brutto, inklusive Azubi.

        So rechnet die Kennzahlenauswertung der Filiale: Arbeitszeit in
        Stunden gegen Wochenumsatz, Ziel 105 EUR je Stunde. Bei 27.000 EUR
        Umsatz sind das 255 h. Steht ein erwarteter Umsatz in der
        Wochenvorgabe, werden die Sollstunden daraus gerechnet - eine
        Vorweihnachtswoche traegt mehr Stunden als eine im Februar.

        Das Budget haengt am Umsatz, nicht an der Anwesenheit: wer Urlaub
        hat, senkt den Umsatzbedarf nicht."""
        b = self.bedarf
        if b.umsatz_erwartet and b.umsatz_je_stunde:
            return b.umsatz_erwartet / b.umsatz_je_stunde
        return b.wochenstunden_gesamt

    def erreichbare_stunden(self) -> float:
        """Was die anwesende Mannschaft ueberhaupt leisten kann - brutto.

        Drei Grenzen zugleich: das Wochensoll samt Toleranz, die laengste
        Schicht, die der/die Einzelne arbeiten darf, und - seit die
        Zielkopfzahl eine Obergrenze ist - die Anzahl der Plaetze im Laden.
        In einer kurzen Woche mit Feiertag ist die letzte die engste: dann
        passen die Sollstunden aller gar nicht mehr hinein. Ohne diese
        Deckelung mahnt das Budget Stunden an, die niemand unterbringen kann,
        und der Planer baut anderswo Unsinn, um sie loszuwerden."""
        plaetze = sum(self.mindestwert(t, "kopfzahl",
                                       self.bedarf.kopfzahl.get(t, 0))[0]
                      for t in self.tage)
        kandidaten = []
        for mid, m in self.stamm.mitarbeiter.items():
            if not (m.im_plan and m.aktiv):
                continue
            if m.moeglichst_wenig:
                ziel, tage = self.soll_stunden[mid], m.soll_tage
            else:
                ziel, tage = self._ziel(mid)
            tage = min(tage, len(self.tage))
            tage = min(tage, sum(1 for t in self.tage if m.zaehlt_am(t)))
            if tage <= 0:
                continue
            if tage <= 0:
                continue
            toleranz = (m.stunden_toleranz_h if m.stunden_toleranz_h is not None
                        else self.stamm.regeln.stunden_toleranz_h)
            deckel = self.laengste_schicht.get(mid) or 0.0
            brutto = min(ziel + toleranz, tage * deckel) if deckel else ziel
            kandidaten.append((brutto / tage, tage))

        summe = 0.0
        for pro_tag, tage in sorted(kandidaten, reverse=True):
            # Die ergiebigsten Plaetze zuerst - das ist die Obergrenze.
            tage = min(tage, plaetze)
            plaetze -= tage
            summe += max(0.0, tage * pro_tag)
            if plaetze <= 0:
                break
        return summe

    def gesamtstunden(self, plan: Plan) -> float:
        """Die Kennzahl der Filiale: Anwesenheit brutto, alle zusammen.

        Kein Pausenabzug und der Azubi zaehlt mit - genau so steht es auf dem
        Auswertungsblatt, gegen das der Umsatz je Stunde gerechnet wird. Die
        Summenspalte je Mitarbeiter im Plan bleibt davon unberuehrt, die ist
        netto (Plan.netto_stunden)."""
        return sum(z.stunden
                   for reihe in plan.zellen.values()
                   for z in reihe.values())

    def nettostunden(self, plan: Plan) -> float:
        """Bezahlte Arbeitszeit ohne Pausen - was die Summenspalten ergeben."""
        pause = self.bedarf.pause_h
        return sum(z.netto_stunden(pause)
                   for reihe in plan.zellen.values()
                   for z in reihe.values())

    def bruttostunden(self, plan: Plan, alle: bool = True) -> float:
        """Anwesenheitsstunden ohne Pausenabzug."""
        return sum(z.stunden
                   for mid, reihe in plan.zellen.items()
                   if alle or self.stamm.mitarbeiter[mid].zaehlt_stundenbudget
                   for z in reihe.values())

    def schichtzahl(self, plan: Plan, alle: bool = False) -> int:
        """Wie viele Schichten - so viele Pausen gehen ab."""
        return sum(1
                   for mid, reihe in plan.zellen.items()
                   if alle or self.stamm.mitarbeiter[mid].zaehlt_stundenbudget
                   for z in reihe.values() if z.arbeitet)

    def _stundenbudget(self, plan: Plan, add):
        """Die 255 h sind eine Obergrenze, kein Ziel.

        Jede geplante Verkaeuferstunde kostet ein wenig: der Umsatz je Stunde
        steigt, wenn dieselbe Besetzung mit weniger Stunden auskommt. Nach
        unten halten die Besetzungskurve, die Arbeitstage und die beiden
        Konten dagegen - es soll sparsam geplant werden, nicht knapp."""
        ziel = self.gesamtbudget()
        if not ziel:
            return
        ist = self.gesamtstunden(plan)
        toleranz = self.bedarf.wochenstunden_gesamt_toleranz
        add("gesamtstunden_ueber", max(0.0, ist - ziel - toleranz),
            f"Gesamt {ist:.1f} h, Budget {ziel:.0f} h - {ist - ziel:.1f} h darueber"
            if ist - ziel > toleranz else "", "warnung")
        if ziel - ist > toleranz:
            erreichbar = self.erreichbare_stunden()
            knapp = min(ziel, erreichbar)
            add("gesamtstunden_unter", 0,
                f"Gesamt {ist:.1f} h brutto - {ziel - ist:.1f} h unter der "
                f"Obergrenze von {ziel:.0f} h"
                + (f" (mehr als {knapp:.0f} h waeren diese Woche ohnehin nicht "
                   f"unterzubringen)" if knapp < ziel - toleranz else ""),
                "hinweis", nur_melden=True)

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
                # Leichter Gegendruck ohne Meldung: die Reserve wird nur
                # eingesetzt, wenn die Besetzung es rechtfertigt.
                add("sparsam_einsetzen", stunden)

            soll_h, soll_t = self._ziel(mid)
            toleranz = (m.stunden_toleranz_h if m.stunden_toleranz_h is not None
                        else self.stamm.regeln.stunden_toleranz_h)
            # Ueber dem Soll ist teuer - das sind Ueberstunden, die jemand
            # nehmen muss. Unter dem Soll ist nur ein leichter Zug nach oben:
            # ob es ueberhaupt Minusstunden gibt, entscheidet die Besetzung,
            # und wen sie treffen, entscheiden die Konten in _konten.
            ueber_h = max(0.0, stunden - soll_h - toleranz)
            unter_h = 0.0 if m.nur_obergrenze else max(0.0, soll_h - stunden - toleranz)
            ueber_t = max(0, tage - soll_t)
            unter_t = 0 if m.nur_obergrenze else max(0, soll_t - tage)
            add("wochenstunden", ueber_h,
                f"{m.name}: {stunden:.1f} h statt {soll_h:.1f} h" if ueber_h >= 2 else "",
                "warnung")
            add("wochenstunden_unter", unter_h,
                f"{m.name}: {stunden:.1f} h statt {soll_h:.1f} h" if unter_h >= 2 else "")
            add("arbeitstage", ueber_t,
                f"{m.name}: {tage} Arbeitstage statt {soll_t}" if ueber_t >= 2 else "")
            add("arbeitstage_unter", unter_t,
                f"{m.name}: {tage} Arbeitstage statt {soll_t}" if unter_t >= 2 else "")
            if tage > m.max_tage:
                add("max_tage", tage - m.max_tage,
                    f"{m.name}: {tage} Arbeitstage, erlaubt sind {m.max_tage}", "fehler")

            grenze = self.stamm.regeln.max_wochenstunden
            if grenze and stunden > grenze:
                add("max_stunden", stunden - grenze,
                    f"{m.name}: {stunden:.1f} h in einer Woche, Obergrenze ist "
                    f"{grenze:.0f} h", "fehler")

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

            # Richtungswechsel: frueh auf spaet oder spaet auf frueh an zwei
            # aufeinanderfolgenden Tagen. Einer in der Woche ist in Ordnung,
            # zwei zerreissen den Rhythmus - Marino hatte in KW42 Di frueh ->
            # Mi spaet und Do spaet -> Fr frueh. Die Mittelschicht ist davon
            # ausgenommen, der Uebergang von und zu ihr faellt nicht auf.
            richtung = []
            for a, b_ in zip(self.tage, self.tage[1:]):
                za, zb = reihe[a], reihe[b_]
                if not (za.arbeitet and zb.arbeitet):
                    continue
                if TAGE.index(b_) - TAGE.index(a) != 1:
                    continue            # dazwischen liegt ein geschlossener Tag
                ka, kb = za.schicht.kategorie, zb.schicht.kategorie
                if {ka, kb} == {"frueh", "spaet"}:
                    richtung.append((a, b_, ka, kb))
            for i, (a, b_, ka, kb) in enumerate(richtung[1:], start=2):
                add("richtungswechsel", 1,
                    f"{m.name}: {i}. Schichtwechsel der Woche "
                    f"({TAG_LANG[a]} {ka} -> {TAG_LANG[b_]} {kb})", "warnung")

            if m.frueh_ab_koepfen:
                # Der Azubi ist fachlich noch nicht so weit, die Fruehschicht
                # zu zweit zu stemmen. Er darf frueh arbeiten, aber nur wenn
                # genug erfahrene Leute daneben stehen.
                for tag in self.tage:
                    z = reihe[tag]
                    if not (z.arbeitet and z.schicht.kategorie == "frueh"):
                        continue
                    koepfe = sum(1 for r in plan.zellen.values()
                                 if r[tag].arbeitet
                                 and r[tag].schicht.kategorie == "frueh")
                    if koepfe < m.frueh_ab_koepfen:
                        add("frueh_zu_duenn", m.frueh_ab_koepfen - koepfe,
                            f"{m.name}: {TAG_LANG[tag]} frueh mit nur {koepfe} "
                            f"Koepfen - er braucht mindestens "
                            f"{m.frueh_ab_koepfen}", "warnung")

            if m.kein_spaet_vor_frueh:
                # Fuer wen der Heimweg lang ist, ist der Wechsel von der
                # Spaetschicht in die Fruehschicht am Folgetag ausgeschlossen -
                # unabhaengig davon, ob die Ruhezeit formal reicht.
                for a, b_ in zip(self.tage, self.tage[1:]):
                    za, zb = reihe[a], reihe[b_]
                    if not (za.arbeitet and zb.arbeitet):
                        continue
                    if TAGE.index(b_) - TAGE.index(a) != 1:
                        continue          # kein direkt folgender Kalendertag
                    if za.schicht.kategorie == "spaet" and \
                            zb.schicht.kategorie == "frueh":
                        add("spaet_vor_frueh", 1,
                            f"{m.name}: {TAG_LANG[a]} spaet, {TAG_LANG[b_]} frueh - "
                            f"bei ihr ausgeschlossen (langer Heimweg)", "fehler")

            kurz = self._kurzgrenze(mid)
            for tag, z in reihe.items():
                if z.arbeitet and z.schicht.dauer_h < kurz:
                    # Fuer zwei, drei Stunden fahert niemand in den Laden. Ohne
                    # diese Bremse zerlegt der Planer die Schichten, um Stunden
                    # zu sparen, und die Leute stehen mit Splittern da.
                    add("kurzschicht", kurz - z.schicht.dauer_h,
                        f"{m.name}: {TAG_LANG[tag]} nur {z.schicht.dauer_h:.1f} h "
                        f"({z.schicht.label}) - unter {kurz:.0f} h", "warnung")

            if m.begleitung:
                # Eine neue Aushilfe soll die Spaetschicht nicht allein mit
                # Leuten stemmen, die selbst noch wenig Routine haben. Steht
                # sie in der Kategorie, muss jemand aus der Gruppe dieselbe
                # Kategorie haben.
                kat = m.begleitung.get("kategorie")
                gruppe = m.begleitung.get("gruppe", [])
                for tag in self.tage:
                    z = reihe[tag]
                    if not (z.arbeitet and (not kat or z.schicht.kategorie == kat)):
                        continue
                    dabei = [g for g in gruppe
                             if (y := plan.zellen.get(g, {}).get(tag)) is not None
                             and y.arbeitet
                             and (not kat or y.schicht.kategorie == kat)]
                    if not dabei:
                        namen = ", ".join(self.stamm.mitarbeiter[g].name
                                          for g in gruppe
                                          if g in self.stamm.mitarbeiter)
                        add("begleitung", 1,
                            f"{m.name}: {TAG_LANG[tag]} {kat or 'Schicht'} ohne "
                            f"Begleitung - gebraucht wird {namen}", "fehler")

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
                # Der Wunsch ist entweder eine Kategorie (Rohwer: Mo-Do frueh)
                # oder eine konkrete Schicht (C. Kurz: Mo 8-14, Mi 8-13).
                wunsch = m.schichtwunsch.get(tag)
                if wunsch and wunsch not in self.stamm.schichten:
                    ist = z.schicht.kategorie
                elif wunsch:
                    ist = z.schicht.id
                if wunsch and ist != wunsch:
                    add("schichtwunsch", 1,
                        f"{m.name}: {TAG_LANG[tag]} {ist} statt {wunsch}")
                if m.bevorzugte_kategorie and \
                        z.schicht.kategorie != m.bevorzugte_kategorie:
                    # Der Azubi soll moeglichst in der Mittelschicht stehen -
                    # da ist Zeit zum Lernen und Ueben. Spaet uebernimmt lieber
                    # jemand anderes, solange der Spaet-Anteil dadurch nicht
                    # dauerhaft unter sein Ziel faellt.
                    add("bevorzugte_kategorie", 1,
                        f"{m.name}: {TAG_LANG[tag]} {z.schicht.kategorie} statt "
                        f"{m.bevorzugte_kategorie}")

            for i, regel in enumerate(self.stamm.wochenwechsel.get(mid, [])):
                moeglich = [tag for tag in regel.tage
                            if tag in self.tage and self._einsetzbar(mid, tag)]
                seiten = [regel.seite(reihe[tag].schicht) for tag in regel.tage
                          if tag in self.tage and reihe[tag].arbeitet]
                kuerzel = "/".join(TAG_LANG[t][:2] for t in regel.tage)
                if regel.geschlossen and 0 < len(seiten) < len(moeglich):
                    # Der Block ist unteilbar: ein freier Tag muss den ganzen
                    # Block treffen, sonst steht sie einen Tag allein da.
                    add("wochenwechsel_unvollstaendig", len(moeglich) - len(seiten),
                        f"{m.name}: {kuerzel} gehoeren zusammen, belegt ist nur "
                        f"{len(seiten)} von {len(moeglich)} Tagen", "warnung")
                if not seiten:
                    continue
                if len(set(seiten)) > 1:
                    add("wochenwechsel_uneinheitlich", len(set(seiten)) - 1,
                        f"{m.name}: {kuerzel} sollen beide dieselbe Seite haben, "
                        f"sind {'/'.join(seiten)}", "warnung")
                    continue
                if not regel.wechselt:
                    continue          # nur der Block zaehlt, kein fester Takt
                letzte = self._letzte_seite.get((mid, i))
                if letzte and letzte == seiten[0]:
                    add("wochenwechsel", 1,
                        f"{m.name}: {kuerzel} schon die zweite Woche in Folge "
                        f"{seiten[0]}", "warnung")

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
