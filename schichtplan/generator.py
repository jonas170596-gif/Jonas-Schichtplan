"""Planerzeugung: Greedy-Start + Simulated Annealing auf der Strafpunktfunktion.

Der Suchraum ist klein (rund 11 Mitarbeiter x 6 Tage x ~20 Schichtoptionen),
deshalb reicht lokale Suche ohne externen Solver - keine Zusatzabhaengigkeit,
und neue Regeln kosten nur eine Zeile in bewertung.py.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .bewertung import Bewerter, Bewertung
from .konfig import Stammdaten, Wochenvorgabe
from .modelle import Plan, Schicht, Zelle, schicht_aus_text


@dataclass
class Ergebnis:
    plan: Plan
    bewertung: Bewertung
    iterationen: int
    startpunkte: float


def _optionen(stamm: Stammdaten, mid: str, tag: str,
              vorgabe: Wochenvorgabe | None = None) -> list[Schicht | None]:
    """Was an dem Tag in Frage kommt: frei oder eine erlaubte Schicht.

    `nur_schichten` in der Wochenvorgabe engt das weiter ein - so laesst sich
    "an dem Tag entweder frei oder die Fruehschicht" abbilden."""
    m = stamm.mitarbeiter[mid]
    erlaubt = [stamm.schichten[s] for s in m.erlaubte_schichten
               if tag in stamm.schichten[s].tage]
    if vorgabe is not None:
        nur = vorgabe.nur_schichten.get(mid, {}).get(tag)
        if nur:
            unbekannt = [s for s in nur if s not in stamm.schichten]
            if unbekannt:
                raise ValueError(f"nur_schichten[{mid}][{tag}]: unbekannt {unbekannt}")
            gefiltert = [s for s in erlaubt if s.id in nur]
            if not gefiltert:
                raise ValueError(
                    f"nur_schichten[{mid}][{tag}]: {nur} - davon darf "
                    f"{m.name} an dem Tag keine einzige arbeiten")
            erlaubt = gefiltert
    return [None] + erlaubt


def _feste_schicht(stamm: Stammdaten, mid: str, tag: str, wert: str) -> Schicht:
    """Wert aus `fest`: entweder eine Katalog-ID oder eine freie Zeitangabe."""
    if wert in stamm.schichten:
        return stamm.schichten[wert]
    try:
        return schicht_aus_text(str(wert))
    except ValueError as fehler:
        raise ValueError(f"fest[{mid}][{tag}]: {fehler}") from None


def grundgeruest(stamm: Stammdaten, vorgabe: Wochenvorgabe) -> Plan:
    """Plan mit allen harten Vorgaben; freie Zellen stehen auf 'frei'.

    Im Modus 'manuell' wird jede Zelle fixiert - der Solver findet dann nichts
    Bewegliches vor und der Plan bleibt so, wie er in der Vorgabe steht."""
    handplan = vorgabe.modus == "manuell"
    tage = stamm.bedarf.offene_tage
    zellen: dict[str, dict[str, Zelle]] = {}
    for mid, m in stamm.mitarbeiter.items():
        if not m.aktiv:
            continue
        reihe: dict[str, Zelle] = {}
        for t in tage:
            if t in vorgabe.geschlossen:
                reihe[t] = Zelle("feiertag", fixiert=True)
            elif not m.im_plan:
                reihe[t] = Zelle("nicht_im_plan", fixiert=True)
            elif t in vorgabe.abwesend.get(mid, {}):
                reihe[t] = Zelle(vorgabe.abwesend[mid][t], fixiert=True)
            elif t in vorgabe.fest.get(mid, {}):
                wert = vorgabe.fest[mid][t]
                if wert in ("frei", "Frei", False):
                    reihe[t] = Zelle("frei", fixiert=True)
                else:
                    reihe[t] = Zelle("schicht", _feste_schicht(stamm, mid, t, wert),
                                     fixiert=True)
            elif t in m.feste_freie_tage and t not in vorgabe.arbeitet.get(mid, []):
                reihe[t] = Zelle("frei", fixiert=True)
            else:
                reihe[t] = Zelle("frei", fixiert=handplan)
            for z in vorgabe.zusatz.get(mid, {}).get(t, []):
                reihe[t].zusatz.append(z)
        zellen[mid] = reihe
    return Plan(
        woche=vorgabe.woche, datum_von=vorgabe.datum_von, datum_bis=vorgabe.datum_bis,
        zellen=zellen, filiale=vorgabe.filiale,
        offene_tage=[t for t in tage if t not in vorgabe.geschlossen],
    )


def _setze(plan: Plan, mid: str, tag: str, schicht: Schicht | None) -> None:
    z = plan.zellen[mid][tag]
    if schicht is None:
        z.art, z.schicht = "frei", None
    else:
        z.art, z.schicht = "schicht", schicht


def _greedy(plan: Plan, stamm: Stammdaten, vorgabe: Wochenvorgabe,
            bewerter: Bewerter, rng: random.Random) -> None:
    """Erst Frueh- und Schlussschichten besetzen, dann auf Kopfzahl auffuellen -
    liefert einen brauchbaren Startpunkt statt reinem Zufall."""
    b = bewerter.bedarf
    for tag in bewerter.tage:
        frei = [mid for mid in plan.zellen
                if not plan.zellen[mid][tag].fixiert
                and stamm.mitarbeiter[mid].im_plan]
        rng.shuffle(frei)
        # Kandidaten mit hohem Stammgewicht fuer die jeweilige Kategorie zuerst
        def kandidaten(pruef):
            paare = []
            for mid in frei:
                if plan.zellen[mid][tag].arbeitet:
                    continue
                for s in _optionen(stamm, mid, tag, vorgabe):
                    if s is not None and pruef(s):
                        paare.append((stamm.mitarbeiter[mid].stamm_schichten.get(s.id, 0), mid, s))
            paare.sort(key=lambda p: -p[0])
            return paare

        for _ in range(b.frueh_min.get(tag, 0)):
            p = kandidaten(lambda s: s.von <= b.frueh_bis)
            if p:
                _setze(plan, p[0][1], tag, p[0][2])
        for _ in range(b.schluss_min.get(tag, 0)):
            p = kandidaten(lambda s: s.bis >= b.oeffnung[tag][1])
            if p:
                _setze(plan, p[0][1], tag, p[0][2])
        while plan.koepfe(tag) < b.kopfzahl.get(tag, 0):
            p = kandidaten(lambda s: True)
            if not p:
                break
            _setze(plan, p[0][1], tag, p[0][2])


def erzeuge(stamm: Stammdaten, vorgabe: Wochenvorgabe,
            vorwochen: list | None = None, *,
            iterationen: int = 40000, neustarts: int = 4,
            seed: int | None = None) -> Ergebnis:
    bewerter = Bewerter(stamm, vorgabe, vorwochen)
    rng = random.Random(seed)

    beweglich = []          # (mid, tag, optionen)
    basis = grundgeruest(stamm, vorgabe)
    for mid, reihe in basis.zellen.items():
        if not stamm.mitarbeiter[mid].im_plan:
            continue
        for tag in bewerter.tage:
            if not reihe[tag].fixiert:
                beweglich.append((mid, tag, _optionen(stamm, mid, tag, vorgabe)))
    if not beweglich:
        return Ergebnis(basis, bewerter.bewerte(basis, detail=True), 0, 0.0)

    nach_tag: dict[str, list[int]] = {}
    for i, (_, tag, _) in enumerate(beweglich):
        nach_tag.setdefault(tag, []).append(i)

    bester_plan, bester_wert, start_wert = None, math.inf, math.inf
    schritte = max(1, iterationen // neustarts)

    for lauf in range(neustarts):
        plan = grundgeruest(stamm, vorgabe)
        _greedy(plan, stamm, vorgabe, bewerter, rng)
        wert = bewerter.bewerte(plan).punkte
        start_wert = min(start_wert, wert)
        t0, t1 = max(wert * 0.05, 50.0), 0.5

        for i in range(schritte):
            temp = t0 * (t1 / t0) ** (i / schritte)
            if rng.random() < 0.65:
                mid, tag, opts = beweglich[rng.randrange(len(beweglich))]
                alt = plan.zellen[mid][tag].schicht
                neu = opts[rng.randrange(len(opts))]
                if neu is alt:
                    continue
                _setze(plan, mid, tag, neu)
                rueck = [(mid, tag, alt)]
            else:                                   # Tausch am selben Tag
                tag = bewerter.tage[rng.randrange(len(bewerter.tage))]
                kand = nach_tag.get(tag)
                if not kand or len(kand) < 2:
                    continue
                a, b_ = rng.sample(kand, 2)
                ma_a, _, opt_a = beweglich[a]
                ma_b, _, opt_b = beweglich[b_]
                s_a = plan.zellen[ma_a][tag].schicht
                s_b = plan.zellen[ma_b][tag].schicht
                if s_a is s_b or s_b not in opt_a or s_a not in opt_b:
                    continue
                _setze(plan, ma_a, tag, s_b)
                _setze(plan, ma_b, tag, s_a)
                rueck = [(ma_a, tag, s_a), (ma_b, tag, s_b)]

            neu_wert = bewerter.bewerte(plan).punkte
            delta = neu_wert - wert
            if delta <= 0 or rng.random() < math.exp(-delta / temp):
                wert = neu_wert
            else:
                for m_, t_, s_ in rueck:
                    _setze(plan, m_, t_, s_)

        if wert < bester_wert:
            bester_wert, bester_plan = wert, plan

    return Ergebnis(bester_plan, bewerter.bewerte(bester_plan, detail=True),
                    iterationen, start_wert)
