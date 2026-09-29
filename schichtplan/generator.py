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


def _ringtausch(plan, beweglich, stelle, tage, rng, versuche: int = 6):
    """A und B tauschen ihre Tage - die Kopfzahl bleibt an beiden gleich.

    Gesucht sind zwei Tage und zwei Mitarbeiter, sodass A am ersten Tag
    arbeitet und am zweiten frei hat und B genau umgekehrt. Danach ist es
    andersherum. Gibt die Rueckabwicklung zurueck, oder None."""
    for _ in range(versuche):
        tag_x, tag_y = rng.sample(tage, 2)
        i = rng.randrange(len(beweglich))
        ma_a, tag_a, _ = beweglich[i]
        if tag_a != tag_x or plan.zellen[ma_a][tag_x].schicht is None:
            continue
        j = stelle.get((ma_a, tag_y))
        if j is None or plan.zellen[ma_a][tag_y].schicht is not None:
            continue
        kandidaten = [k for k in range(len(beweglich))
                      if beweglich[k][1] == tag_y and beweglich[k][0] != ma_a
                      and plan.zellen[beweglich[k][0]][tag_y].schicht is not None]
        if not kandidaten:
            continue
        k = kandidaten[rng.randrange(len(kandidaten))]
        ma_b = beweglich[k][0]
        l = stelle.get((ma_b, tag_x))
        if l is None or plan.zellen[ma_b][tag_x].schicht is not None:
            continue
        s_a, s_b = plan.zellen[ma_a][tag_x].schicht, plan.zellen[ma_b][tag_y].schicht
        if s_a not in beweglich[l][2] or s_b not in beweglich[j][2]:
            continue                      # der andere darf die Schicht nicht
        rueck = [(ma_a, tag_x, s_a), (ma_a, tag_y, None),
                 (ma_b, tag_x, None), (ma_b, tag_y, s_b)]
        _setze(plan, ma_a, tag_x, None)
        _setze(plan, ma_a, tag_y, s_b)
        _setze(plan, ma_b, tag_x, s_a)
        _setze(plan, ma_b, tag_y, None)
        return rueck
    return None


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
    nach_ma: dict[str, list[int]] = {}
    for i, (mid, tag, _) in enumerate(beweglich):
        nach_tag.setdefault(tag, []).append(i)
        nach_ma.setdefault(mid, []).append(i)
    mit_mehreren = [mid for mid, idx in nach_ma.items() if len(idx) >= 2]
    stelle = {(mid, tag): i for i, (mid, tag, _) in enumerate(beweglich)}

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
            wurf = rng.random()
            if wurf < 0.45:
                mid, tag, opts = beweglich[rng.randrange(len(beweglich))]
                alt = plan.zellen[mid][tag].schicht
                neu = opts[rng.randrange(len(opts))]
                if neu is alt:
                    continue
                _setze(plan, mid, tag, neu)
                rueck = [(mid, tag, alt)]
            elif wurf < 0.70:                       # Tausch am selben Tag
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
            elif wurf < 0.85 and len(bewerter.tage) >= 2:
                # Ringtausch ueber zwei Tage: A arbeitet am Montag und hat am
                # Mittwoch frei, B umgekehrt - beide tauschen. Die Kopfzahl
                # bleibt an beiden Tagen gleich, deshalb kommt der Planer so
                # an der Obergrenze vorbei. Mit Einzelzuegen ginge es nicht:
                # jeder Zwischenschritt ueber- oder unterbesetzt einen Tag.
                rueck = _ringtausch(plan, beweglich, stelle, bewerter.tage, rng)
                if rueck is None:
                    continue
            elif mit_mehreren:
                # Derselbe Mensch, zwei Tage getauscht - schiebt eine Schicht
                # von Mittwoch auf Dienstag, ohne den Umweg ueber einen Tag
                # mit falscher Kopfzahl.
                mid = mit_mehreren[rng.randrange(len(mit_mehreren))]
                a, b_ = rng.sample(nach_ma[mid], 2)
                _, tag_a, opt_a = beweglich[a]
                _, tag_b, opt_b = beweglich[b_]
                s_a = plan.zellen[mid][tag_a].schicht
                s_b = plan.zellen[mid][tag_b].schicht
                if s_a is s_b or s_b not in opt_a or s_a not in opt_b:
                    continue
                _setze(plan, mid, tag_a, s_b)
                _setze(plan, mid, tag_b, s_a)
                rueck = [(mid, tag_a, s_a), (mid, tag_b, s_b)]
            else:
                continue

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
