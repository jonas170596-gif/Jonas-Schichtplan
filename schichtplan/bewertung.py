"""Bewertung eines Plans: alle Regeln als gewichtete Strafpunkte.

Der Generator minimiert `Bewertung.punkte`. Fuer den Menschen gibt es
`pruefen()`, das dieselben Regeln als Klartextliste ausgibt.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .konfig import Stammdaten, Wochenvorgabe
from .modelle import TAGE, TAG_LANG, Plan


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
        b = stamm.bedarf
        self.tage = [t for t in b.offene_tage if t not in vorgabe.geschlossen]
        self.slots = {t: list(range(*b.oeffnung[t])) for t in self.tage}
        self.min_kurve = {t: [b.min_am_slot(t, s) for s in self.slots[t]] for t in self.tage}
        self.soll_stunden = {
            mid: vorgabe.soll_stunden.get(mid, m.soll_stunden)
            for mid, m in stamm.mitarbeiter.items()
        }
        # Urlaub kuerzt nicht die Stunden pro Tag, sondern die Anzahl moeglicher Tage.
        # Wer 40 h auf 5 Tage hat und einen Tag Urlaub nimmt, arbeitet die restlichen
        # Tage normal weiter - genau so steht es in den Altplaenen.
        self.verfuegbare_tage = {
            mid: sum(1 for t in self.tage if t not in vorgabe.abwesend.get(mid, {}))
            for mid in stamm.mitarbeiter
        }

    def _ziel(self, mid: str) -> tuple[float, int]:
        """(Zielstunden, Zieltage) fuer diese Woche."""
        m = self.stamm.mitarbeiter[mid]
        moeglich = self.verfuegbare_tage[mid]
        tage = min(m.soll_tage, moeglich)
        pro_tag = self.soll_stunden[mid] / m.soll_tage if m.soll_tage else 0.0
        return pro_tag * tage, tage

    # ------------------------------------------------------------------ #
    def bewerte(self, plan: Plan, detail: bool = False) -> Bewertung:
        erg = Bewertung()
        add = self._sammler(erg, detail)
        self._besetzung(plan, add)
        self._arbeitszeit(plan, add)
        self._wuensche(plan, add)
        self._qualitaet(plan, add)
        return erg

    def _sammler(self, erg: Bewertung, detail: bool):
        def add(regel: str, faktor: float, text: str = "", schwere: str = "hinweis"):
            if faktor <= 0:
                return
            p = self.g.get(regel, 0.0) * faktor
            erg.punkte += p
            if detail and text:
                erg.befunde.append(Befund(regel, p, text, schwere))
        return add

    # ---- Besetzung ---------------------------------------------------- #
    def _besetzung(self, plan: Plan, add):
        b = self.stamm.bedarf
        for t in self.tage:
            zellen = [r[t] for r in plan.zellen.values() if r[t].arbeitet]
            koepfe = len(zellen)
            ziel = b.kopfzahl.get(t, koepfe)
            weg = max(0, abs(koepfe - ziel) - b.kopfzahl_toleranz)
            if weg:
                add("kopfzahl", weg,
                    f"{TAG_LANG[t]}: {koepfe} Mitarbeiter statt {ziel}"
                    f" (Toleranz +/-{b.kopfzahl_toleranz})",
                    "fehler" if weg > 1 else "warnung")

            frueh = sum(1 for z in zellen if z.schicht.von <= b.frueh_bis)
            fehlt = b.frueh_min.get(t, 0) - frueh
            if fehlt > 0:
                add("frueh_besetzung", fehlt,
                    f"{TAG_LANG[t]}: nur {frueh} Fruehschichten, {b.frueh_min[t]} noetig", "fehler")

            schluss_zeit = b.oeffnung[t][1]
            schluss = sum(1 for z in zellen if z.schicht.bis >= schluss_zeit)
            fehlt = b.schluss_min.get(t, 0) - schluss
            if fehlt > 0:
                add("schluss_besetzung", fehlt,
                    f"{TAG_LANG[t]}: nur {schluss} bis Ladenschluss, {b.schluss_min[t]} noetig",
                    "fehler")

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
            soll_h, soll_t = self._ziel(mid)
            weg_h = max(0.0, abs(stunden - soll_h) - self.stamm.regeln.stunden_toleranz_h)
            add("wochenstunden", weg_h,
                f"{m.name}: {stunden:.1f} h statt {soll_h:.1f} h" if weg_h >= 2 else "",
                "warnung")
            add("arbeitstage", abs(tage - soll_t),
                f"{m.name}: {tage} Arbeitstage statt {soll_t}"
                if abs(tage - soll_t) >= 2 else "")
            if tage > m.max_tage:
                add("max_tage", tage - m.max_tage,
                    f"{m.name}: {tage} Arbeitstage, erlaubt sind {m.max_tage}", "fehler")

            folge = max_folge = 0
            for t in self.tage:
                folge = folge + 1 if reihe[t].arbeitet else 0
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

    # ---- Qualitaet ------------------------------------------------------ #
    def _qualitaet(self, plan: Plan, add):
        ruhe_slots = int(self.stamm.regeln.ruhezeit_h * 2)
        ruhe_hart = int(self.stamm.regeln.ruhezeit_min_h * 2)
        for mid, m in self.stamm.mitarbeiter.items():
            if not m.im_plan:
                continue
            reihe = plan.zellen[mid]
            for a, b_ in zip(self.tage, self.tage[1:]):
                za, zb = reihe[a], reihe[b_]
                if za.arbeitet and zb.arbeitet:
                    pause = (48 - za.schicht.bis) + zb.schicht.von
                    if pause < ruhe_hart:
                        add("ruhezeit_verletzung", (ruhe_hart - pause) / 2,
                            f"{m.name}: nur {pause / 2:.1f} h Ruhe zwischen "
                            f"{TAG_LANG[a]} und {TAG_LANG[b_]} "
                            f"(Untergrenze {self.stamm.regeln.ruhezeit_min_h} h)", "fehler")
                    elif pause < ruhe_slots:
                        add("ruhezeit", (ruhe_slots - pause) / 2,
                            f"{m.name}: {pause / 2:.1f} h Ruhe zwischen "
                            f"{TAG_LANG[a]} und {TAG_LANG[b_]}", "warnung")
            if m.stamm_schichten:
                fremd = sum(1 - m.stamm_schichten.get(z.schicht.id, 0.0)
                            for z in reihe.values() if z.arbeitet)
                add("stammschicht", fremd)
            verschieden = {z.schicht.id for z in reihe.values() if z.arbeitet}
            add("zersplitterung", max(0, len(verschieden) - 2))

            if self.stamm.regeln.samstage_frei_pro_x and "sa" in self.tage:
                fenster = self.vorwochen[-(self.stamm.regeln.samstage_frei_pro_x - 1):]
                sa_gearbeitet = sum(
                    1 for w in fenster
                    if mid in w.plan and w.plan[mid].get("sa")
                    and w.plan[mid]["sa"].arbeitet)
                if reihe["sa"].arbeitet:
                    sa_gearbeitet += 1
                if sa_gearbeitet >= self.stamm.regeln.samstage_frei_pro_x:
                    add("samstag_fairness", 1,
                        f"{m.name}: {sa_gearbeitet} Samstage in Folge gearbeitet", "warnung")


def pruefen(plan: Plan, stamm: Stammdaten, vorgabe: Wochenvorgabe,
            vorwochen: list | None = None) -> Bewertung:
    return Bewerter(stamm, vorgabe, vorwochen).bewerte(plan, detail=True)
