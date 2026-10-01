"""Kontenuebersicht: Frueh/Spaet, freie Samstage und Stundenkonto in einer Tabelle.

Die drei rollierenden Konten einzeln anzusehen beantwortet die Frage nicht, die
beim Planen zaehlt: wer ist insgesamt dran? Deshalb hier nebeneinander, mit dem
Wochenverlauf als Spur.
"""
from __future__ import annotations

import html
from dataclasses import dataclass

from .bewertung import Bewerter
from .konfig import Stammdaten


@dataclass
class Zeile:
    name: str
    soll: str
    frueh: int
    spaet: int
    mittel: int
    ausgleich: bool             # nimmt am Frueh/Spaet-Ausgleich teil
    sa_moeglich: int
    sa_frei: int
    sa_soll: float
    sa_zwingend: bool
    stunden: float              # Stundenkonto, + = Rueckstand
    spur: str                   # Wochenverlauf: F/S/M/_/u/.

    @property
    def diff(self) -> int:
        return self.frueh - self.spaet

    @property
    def sa_konto(self) -> float:
        return self.sa_frei - self.sa_soll


def sammle(stamm: Stammdaten, wochen: list, fenster: int | None = None) -> list[Zeile]:
    """Eine Zeile je Mitarbeiter, gerechnet ueber die uebergebenen Wochen."""
    fenster = fenster or stamm.regeln.ausgleich_fenster_wochen
    eng = wochen[-fenster:] if fenster else wochen
    # Fuer die Konten braucht der Bewerter eine Wochenvorgabe; die letzte Woche
    # der Historie dient als Platzhalter. Als Vorwochen gehen ALLE Wochen ein,
    # auch die letzte - sonst fehlt in der Tabelle genau die Woche, die man
    # gerade gerechnet hat, und ein frisch vergebener freier Samstag taucht
    # nicht auf.
    from .backtest import vorgabe_aus_historie
    bew = Bewerter(stamm, vorgabe_aus_historie(wochen[-1], stamm), wochen)
    samstage = bew.samstagskonto()
    stunden = bew.stundenkonto()

    zeilen = []
    for mid, m in stamm.mitarbeiter.items():
        if not (m.im_plan and m.aktiv):
            continue
        zaehler = {"frueh": 0, "spaet": 0, "mittel": 0}
        for w in eng:
            for z in w.plan.get(mid, {}).values():
                if z.verwertbar:
                    zaehler[stamm.kategorie_von(z.von, z.bis)] += 1
        spur = ""
        for w in eng:
            reihe = w.plan.get(mid, {})
            offen = w.offene_tage()
            for tag in w.plan.get(mid, {}):
                pass
            for tag in offen:
                z = reihe.get(tag)
                if z is None:
                    spur += "."
                elif z.verwertbar:
                    spur += {"frueh": "F", "spaet": "S"}.get(
                        stamm.kategorie_von(z.von, z.bis), "M")
                elif z.art == "frei":
                    spur += "_"
                else:
                    spur += "u"
            spur += " "
        moeglich, frei, soll = samstage.get(mid, (0, 0, 0.0))
        zeilen.append(Zeile(
            name=m.name,
            soll=f"{m.soll_stunden:.0f}/{m.soll_tage}" if m.soll_stunden else "-",
            frueh=zaehler["frueh"], spaet=zaehler["spaet"], mittel=zaehler["mittel"],
            ausgleich=m.frueh_spaet_ausgleich,
            sa_moeglich=moeglich, sa_frei=frei, sa_soll=soll,
            sa_zwingend=bew.samstag_zwingend(mid),
            stunden=stunden.get(mid, float("nan")),
            spur=spur.strip(),
        ))
    return zeilen


def als_text(zeilen: list[Zeile], stamm: Stammdaten, titel: str) -> str:
    aus = [titel, ""]
    aus.append(f"{'Mitarbeiter':<18}{'Soll':>7} | {'Frueh':>5}{'Spaet':>6}{'Diff':>6}"
               f" | {'Sa frei':>8}{'Schnitt':>8}{'Konto':>7} | {'Stunden':>8}")
    aus.append("-" * 78)
    for z in zeilen:
        fs = f"{z.frueh:>5}{z.spaet:>6}{z.diff:>+6}" if z.ausgleich or z.diff \
            else f"{z.frueh:>5}{z.spaet:>6}{'':>6}"
        sa = (f"{z.sa_frei:>3}/{z.sa_moeglich:<4}{z.sa_soll:>8.1f}{z.sa_konto:>+7.1f}"
              if z.sa_moeglich else f"{'-':>8}{'':>8}{'':>7}")
        std = f"{z.stunden:>+8.1f}" if z.stunden == z.stunden else f"{'-':>8}"
        marken = []
        if not z.ausgleich:
            marken.append("Ausgleich ausgenommen")
        elif abs(z.diff) > stamm.regeln.ausgleich_toleranz:
            marken.append("Frueh/Spaet schief")
        if z.sa_zwingend:
            marken.append("Samstag zwingend")
        elif z.sa_moeglich and z.sa_konto < -stamm.regeln.samstag_toleranz:
            marken.append("Samstag im Rueckstand")
        aus.append(f"{z.name:<18}{z.soll:>7} | {fs} | {sa} | {std}"
                   + ("   " + ", ".join(marken) if marken else ""))
    aus += ["",
            "Diff   Fruehschichten minus Spaetschichten im Fenster.",
            "Konto  freie Samstage gegenueber dem Schnitt der Mannschaft;",
            "       negativ heisst Rueckstand.",
            "Stunden  Soll minus Ist ueber das Fenster; positiv heisst Minusstunden."]
    return "\n".join(aus)


_CSS = """
body { font-family: 'Segoe UI', Arial, sans-serif; margin: 10mm; color:#222;
       background:#fff; }
h1 { font-size:14pt; margin:0 0 1mm; }
p.unter { color:#555; font-size:9.5pt; margin:0 0 5mm; }
table { border-collapse:collapse; width:100%; font-size:10pt; }
th, td { border:1px solid #ccd; padding:1.6mm 2.4mm; text-align:right; }
th { background:#eceff1; font-weight:600; font-size:9pt; }
td.ma { text-align:left; font-weight:600; }
td.spur { text-align:left; font-family:'DejaVu Sans Mono',monospace; font-size:8.5pt;
          color:#555; letter-spacing:0.4px; }
tr:nth-child(even) td { background:#fafbfc; }
.gut { color:#1b7f3b; }
.schlecht { color:#b00020; font-weight:600; }
.grau { color:#999; }
.gruppe { border-left:1.5px solid #99a; }
.legende { margin-top:5mm; font-size:9pt; color:#555; }
.legende b { color:#222; }
@media print { body { margin:0; } }
"""


def als_html(zeilen: list[Zeile], stamm: Stammdaten, titel: str) -> str:
    e = html.escape
    tol_fs = stamm.regeln.ausgleich_toleranz
    tol_sa = stamm.regeln.samstag_toleranz
    tol_h = stamm.regeln.minusstunden_toleranz_h

    def zelle(wert: str, klasse: str = "") -> str:
        return f'<td class="{klasse}">{wert}</td>'

    reihen = []
    for z in zeilen:
        fs_klasse = "grau" if not z.ausgleich else (
            "schlecht" if abs(z.diff) > tol_fs else "gut")
        sa_klasse = ("grau" if z.sa_zwingend or not z.sa_moeglich else
                     "schlecht" if z.sa_konto < -tol_sa else "gut")
        h_klasse = ("grau" if z.stunden != z.stunden else
                    "schlecht" if z.stunden > tol_h else "gut")
        reihen.append(
            "<tr>"
            + zelle(e(z.name), "ma") + zelle(e(z.soll))
            + zelle(str(z.frueh), "gruppe") + zelle(str(z.spaet))
            + zelle(f"{z.diff:+d}", fs_klasse)
            + zelle(f"{z.sa_frei} / {z.sa_moeglich}" if z.sa_moeglich else "-", "gruppe")
            + zelle(f"{z.sa_soll:.1f}" if z.sa_moeglich else "")
            + zelle(f"{z.sa_konto:+.1f}" if z.sa_moeglich else "", sa_klasse)
            + zelle(f"{z.stunden:+.1f} h" if z.stunden == z.stunden else "-",
                    "gruppe " + h_klasse)
            + zelle(e(z.spur), "spur")
            + "</tr>")

    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><title>Konten</title>
<style>{_CSS}</style></head><body>
<h1>Konten der Mannschaft</h1>
<p class="unter">{e(titel)}</p>
<table>
<tr><th rowspan="2">Mitarbeiter</th><th rowspan="2">Soll</th>
    <th colspan="3" class="gruppe">Frueh / Spaet</th>
    <th colspan="3" class="gruppe">freie Samstage</th>
    <th rowspan="2" class="gruppe">Stunden&shy;konto</th>
    <th rowspan="2">Verlauf je Woche</th></tr>
<tr><th class="gruppe">F</th><th>S</th><th>Diff</th>
    <th class="gruppe">frei</th><th>Schnitt</th><th>Konto</th></tr>
{''.join(reihen)}
</table>
<div class="legende">
<p><b>Diff</b> Fruehschichten minus Spaetschichten im Fenster.
   Grau = nimmt am Ausgleich nicht teil, rot = mehr als {tol_fs} Schichten schief.</p>
<p><b>Samstage</b> frei von moeglich, daneben der Schnitt der Mannschaft auf die
   eigenen moeglichen Samstage gerechnet. <b>Konto</b> negativ heisst Rueckstand;
   rot ab {tol_sa:.0f} Samstag. Grau = Samstag ist vertraglich zwingend.</p>
<p><b>Stundenkonto</b> Soll minus Ist ueber das Fenster. Positiv heisst
   Minusstunden; rot ab {tol_h:.0f} h ueber dem Schnitt der Mannschaft.</p>
<p><b>Verlauf</b> F = Frueh, S = Spaet, M = Mittel, _ = frei,
   u = Urlaub/krank/Schule, . = Feiertag. Ein Block je Woche.</p>
</div>
</body></html>
"""
