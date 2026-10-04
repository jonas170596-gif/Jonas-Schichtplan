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
    # Manche Schichten gelten nur an einem bestimmten Tag: C. Kurz faengt nur
    # samstags um 6 an, unter der Woche nie.
    ids = list(m.erlaubte_schichten) + list(m.zusatzschichten.get(tag, []))
    # Und manche Tage lassen umgekehrt nur eine bestimmte Auswahl zu: kommt
    # C. Kurz samstags, dann ab 6 - nicht erst um 8 wie unter der Woche.
    nur_tag = m.nur_schichten.get(tag)
    if nur_tag:
        ids = [s for s in ids if s in nur_tag]
    erlaubt = [stamm.schichten[s] for s in dict.fromkeys(ids)
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
            elif t in m.feste_freie_tage \
                    and t not in vorgabe.arbeitet.get(mid, []) \
                    and t not in vorgabe.kann_arbeiten.get(mid, []):
                reihe[t] = Zelle("frei", fixiert=True)
            else:
                reihe[t] = Zelle("frei", fixiert=handplan)
            for z in vorgabe.zusatz.get(mid, {}).get(t, []):
                reihe[t].zusatz.append(z)
        zellen[mid] = reihe
    return Plan(
        woche=vorgabe.woche, datum_von=vorgabe.datum_von, datum_bis=vorgabe.datum_bis,
        zellen=zellen, filiale=vorgabe.filiale, notiz=vorgabe.notiz,
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


def _abloesung(plan, beweglich, nach_tag, tage, rng, versuche: int = 6):
    """B loest A an einem Tag ab und nimmt dafuer die Schicht aus den eigenen
    Optionen, die A's am naechsten kommt.

    Der gewoehnliche Tausch am selben Tag verlangt, dass B genau A's Schicht
    darf - daran scheitert er meistens. C. Kurz kann samstags 6-14, 8-14 und
    8-16, aber kein 10-18; Rohwers freien Samstag findet der Planer deshalb
    mit dem Tausch nie. Die Kopfzahl bleibt gleich, nur die Kurve verschiebt
    sich ein wenig - den Rest raeumen die Einzelzuege auf."""
    for _ in range(versuche):
        tag = tage[rng.randrange(len(tage))]
        kand = nach_tag.get(tag)
        if not kand or len(kand) < 2:
            continue
        a, b_ = rng.sample(kand, 2)
        ma_a = beweglich[a][0]
        ma_b, _, opt_b = beweglich[b_]
        s_a = plan.zellen[ma_a][tag].schicht
        if s_a is None or plan.zellen[ma_b][tag].schicht is not None:
            continue
        moeglich = [s for s in opt_b if s is not None]
        if not moeglich:
            continue
        ersatz = min(moeglich,
                     key=lambda s: (abs(s.von - s_a.von), abs(s.bis - s_a.bis)))
        _setze(plan, ma_a, tag, None)
        _setze(plan, ma_b, tag, ersatz)
        return [(ma_a, tag, s_a), (ma_b, tag, None)]
    return None


def _politur(plan, beweglich, nach_tag, bewerter, wert: float,
             runden: int = 3) -> float:
    """Aufraeumen nach dem Abkuehlen: wen kann man aus einem Tag herausnehmen,
    wenn der Tag danach wieder zurechtgerueckt wird?

    Einen freien Samstag bekommt nur, wer ersetzt wird - und das verlangt
    meist drei Aenderungen auf einmal: A geht raus, B springt mit einer
    anderen Schicht ein, C rueckt nach. Jeder einzelne Schritt macht den Plan
    erst schlechter, deshalb findet ihn das Abkuehlen nicht. Hier wird der
    ganze Zug am Stueck probiert und nur behalten, wenn er sich lohnt."""
    for _ in range(runden):
        verbessert = False
        for i, (ma_a, tag, _) in enumerate(beweglich):
            s_a = plan.zellen[ma_a][tag].schicht
            if s_a is None:
                continue
            sicherung = [(beweglich[j][0], plan.zellen[beweglich[j][0]][tag].schicht)
                         for j in nach_tag.get(tag, [])]
            _setze(plan, ma_a, tag, None)
            # Den Tag wieder zurechtruecken: jede andere bewegliche Zelle des
            # Tages einmal durchprobieren und die beste Variante behalten.
            for j in nach_tag.get(tag, []):
                ma_b, _, opt_b = beweglich[j]
                if ma_b == ma_a:
                    continue
                jetzt = plan.zellen[ma_b][tag].schicht
                bestes, bester = jetzt, bewerter.bewerte(plan).punkte
                for kand in opt_b:
                    if kand is jetzt:
                        continue
                    _setze(plan, ma_b, tag, kand)
                    punkte = bewerter.bewerte(plan).punkte
                    if punkte < bester:
                        bestes, bester = kand, punkte
                _setze(plan, ma_b, tag, bestes)
            neu_wert = bewerter.bewerte(plan).punkte
            if neu_wert < wert:
                wert, verbessert = neu_wert, True
            else:
                for ma_, s_ in sicherung:
                    _setze(plan, ma_, tag, s_)
        if not verbessert:
            break
    return wert


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
            if wurf < 0.42:
                mid, tag, opts = beweglich[rng.randrange(len(beweglich))]
                alt = plan.zellen[mid][tag].schicht
                neu = opts[rng.randrange(len(opts))]
                if neu is alt:
                    continue
                _setze(plan, mid, tag, neu)
                rueck = [(mid, tag, alt)]
            elif wurf < 0.67:                       # Tausch am selben Tag
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
            elif wurf < 0.82 and len(bewerter.tage) >= 2:
                # Ringtausch ueber zwei Tage: A arbeitet am Montag und hat am
                # Mittwoch frei, B umgekehrt - beide tauschen. Die Kopfzahl
                # bleibt an beiden Tagen gleich, deshalb kommt der Planer so
                # an der Obergrenze vorbei. Mit Einzelzuegen ginge es nicht:
                # jeder Zwischenschritt ueber- oder unterbesetzt einen Tag.
                rueck = _ringtausch(plan, beweglich, stelle, bewerter.tage, rng)
                if rueck is None:
                    continue
            elif wurf < 0.90:
                # Ablaesung am selben Tag: der freie Samstag einer Person
                # entsteht nur, wenn jemand anderes einspringt - und zwar mit
                # einer Schicht, die er auch darf.
                rueck = _abloesung(plan, beweglich, nach_tag, bewerter.tage, rng)
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

        wert = _politur(plan, beweglich, nach_tag, bewerter, wert)
        if wert < bester_wert:
            bester_wert, bester_plan = wert, plan

    return Ergebnis(bester_plan, bewerter.bewerte(bester_plan, detail=True),
                    iterationen, start_wert)
