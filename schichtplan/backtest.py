"""Rueckrechnung: fuer jede historische Woche die damaligen Randbedingungen
(Urlaub, Schule, Krank, Feiertag) rekonstruieren, neu planen und mit dem
tatsaechlich geschriebenen Plan vergleichen.

Das ist die ehrliche Messung, ob die Konfiguration die Wirklichkeit trifft:
  * Trefferquote Arbeit/Frei je Zelle
  * Trefferquote exakte Schicht
  * Strafpunkte des Originals gegen die des generierten Plans
"""
from __future__ import annotations

from dataclasses import dataclass

from .bewertung import Bewerter
from .generator import erzeuge
from .historie import HistWoche
from .konfig import Stammdaten, Wochenvorgabe
from .modelle import ABWESEND, Plan, Schicht, Zelle, zu_text


def vorgabe_aus_historie(w: HistWoche, stamm: Stammdaten) -> Wochenvorgabe:
    offen = w.offene_tage()
    abwesend: dict[str, dict[str, str]] = {}
    for mid, reihe in w.plan.items():
        if mid not in stamm.mitarbeiter:
            continue
        for t, z in reihe.items():
            if t in offen and z.art in ABWESEND:
                abwesend.setdefault(mid, {})[t] = z.art
    return Wochenvorgabe(
        woche=w.woche, datum_von=w.datum_von, filiale="Winterbach",
        geschlossen=[t for t in stamm.bedarf.offene_tage if t not in offen],
        abwesend=abwesend,
    )


def plan_aus_historie(w: HistWoche, stamm: Stammdaten) -> Plan:
    """Originalplan als Plan-Objekt.

    Vier Zellen auf den Fotos haben keine Endzeit ("6-"). Sie werden mit der
    haeufigsten Katalogschicht gleichen Starts aufgefuellt, sonst zaehlt der
    Vergleich einen Lesefehler als Planungsfehler."""
    nach_zeit = {(s.von, s.bis): s for s in stamm.schichten.values()}
    nach_start: dict[int, Schicht] = {}
    for s in stamm.schichten.values():
        vorhanden = nach_start.get(s.von)
        if vorhanden is None or s.bis > vorhanden.bis:
            nach_start[s.von] = s
    zellen = {}
    for mid, reihe in w.plan.items():
        if mid not in stamm.mitarbeiter:
            continue
        neu = {}
        for t, z in reihe.items():
            if z.arbeitet and not z.verwertbar and z.von in nach_start:
                neu[t] = Zelle("schicht", nach_start[z.von], list(z.zusatz))
            elif z.verwertbar:
                s = nach_zeit.get((z.von, z.bis)) or Schicht(
                    f"{zu_text(z.von)}-{zu_text(z.bis)}", z.von, z.bis)
                neu[t] = Zelle("schicht", s, list(z.zusatz))
            else:
                neu[t] = Zelle("frei" if z.arbeitet else z.art, zusatz=list(z.zusatz))
        zellen[mid] = neu
    return Plan(w.woche, w.datum_von, "", zellen, "Winterbach", w.offene_tage())


@dataclass
class Vergleich:
    woche: str
    zellen: int
    treffer_anwesenheit: int
    treffer_schicht: int
    punkte_original: float
    punkte_generiert: float

    @property
    def quote_anwesenheit(self) -> float:
        return self.treffer_anwesenheit / self.zellen if self.zellen else 0.0

    @property
    def quote_schicht(self) -> float:
        return self.treffer_schicht / self.zellen if self.zellen else 0.0


def vergleiche(w: HistWoche, stamm: Stammdaten, *, seed: int = 1,
               iterationen: int = 30000, vorwochen: list[HistWoche] | None = None
               ) -> Vergleich:
    vorgabe = vorgabe_aus_historie(w, stamm)
    original = plan_aus_historie(w, stamm)
    erg = erzeuge(stamm, vorgabe, vorwochen, iterationen=iterationen, seed=seed)
    bewerter = Bewerter(stamm, vorgabe, vorwochen)

    zellen = treffer_a = treffer_s = 0
    for mid, reihe in erg.plan.zellen.items():
        if not stamm.mitarbeiter[mid].im_plan:
            continue
        for t in erg.plan.offene_tage:
            o = original.zellen.get(mid, {}).get(t)
            if o is None or o.art in ABWESEND:
                continue                      # war vorgegeben, kein Verdienst
            g = reihe[t]
            zellen += 1
            if o.arbeitet == g.arbeitet:
                treffer_a += 1
                if o.arbeitet and o.schicht.von == g.schicht.von \
                        and o.schicht.bis == g.schicht.bis:
                    treffer_s += 1
                elif not o.arbeitet:
                    treffer_s += 1
    return Vergleich(w.woche, zellen, treffer_a, treffer_s,
                     bewerter.bewerte(original).punkte, erg.bewertung.punkte)


def bericht(wochen: list[HistWoche], stamm: Stammdaten, *, seed: int = 1,
            iterationen: int = 30000) -> str:
    z = [f"{'Woche':<14}{'Zellen':>7}{'Anwesenheit':>13}{'Schicht':>10}"
         f"{'Punkte Orig.':>14}{'Punkte neu':>12}", "-" * 70]
    summe = [0, 0, 0, 0.0, 0.0]
    for i, w in enumerate(wochen):
        v = vergleiche(w, stamm, seed=seed, iterationen=iterationen,
                       vorwochen=wochen[:i])
        z.append(f"{v.woche:<14}{v.zellen:>7}{v.quote_anwesenheit:>12.0%}"
                 f"{v.quote_schicht:>10.0%}{v.punkte_original:>14.0f}"
                 f"{v.punkte_generiert:>12.0f}")
        summe[0] += v.zellen
        summe[1] += v.treffer_anwesenheit
        summe[2] += v.treffer_schicht
        summe[3] += v.punkte_original
        summe[4] += v.punkte_generiert
    n = len(wochen) or 1
    z.append("-" * 70)
    z.append(f"{'Gesamt':<14}{summe[0]:>7}{summe[1] / max(summe[0], 1):>12.0%}"
             f"{summe[2] / max(summe[0], 1):>10.0%}{summe[3] / n:>14.0f}"
             f"{summe[4] / n:>12.0f}")
    z.append("")
    z.append("Anwesenheit = Arbeit/Frei richtig getroffen, Schicht = exakt gleiche Zeiten.")
    z.append("Punkte: Strafpunkte nach eigenen Regeln - je niedriger, desto regelkonformer.")
    z.append("Liegt 'Punkte neu' deutlich unter 'Punkte Orig.', bewertet die Konfiguration")
    z.append("etwas anders als der Mensch geplant hat - dann Gewichte in regeln.yaml pruefen.")
    return "\n".join(z)
