"""Teamleiteruebersicht: was man zur Woche wissen muss, auf einer Seite.

Der Papierplan haengt im Laden und zeigt nur die Schichten. Die Teamleitung
braucht daneben die Begruendung: welche Zugestaendnisse diese Woche gemacht
wurden, wo die Mannschaft in den rollierenden Konten steht, und was fuer die
naechste Woche ansteht.
"""
from __future__ import annotations

import html

from .bewertung import SCHWEREGRADE, Bewerter
from .konfig import Stammdaten
from .modelle import Plan

_CSS = """
@page { size: A4 portrait; margin: 12mm; }
body { font-family:'Segoe UI',Arial,sans-serif; color:#222; background:#fff;
       margin:0; font-size:10pt; }
h1 { font-size:15pt; margin:0 0 1mm; }
h2 { font-size:11pt; margin:6mm 0 2mm; padding-bottom:1mm;
     border-bottom:1px solid #ccd; }
p.unter { color:#555; margin:0 0 4mm; font-size:9.5pt; }
table { border-collapse:collapse; width:100%; font-size:9.5pt; }
th, td { border:1px solid #ccd; padding:1.4mm 2mm; text-align:right; }
th { background:#eceff1; font-weight:600; font-size:8.5pt; }
td.l, th.l { text-align:left; }
td.ma { text-align:left; font-weight:600; }
tr:nth-child(even) td { background:#fafbfc; }
.kennzahl { display:flex; gap:4mm; margin:0 0 4mm; flex-wrap:wrap; }
.kachel { border:1px solid #ccd; border-radius:1.5mm; padding:2mm 3mm;
          min-width:30mm; }
.kachel b { display:block; font-size:13pt; }
.kachel span { font-size:8.5pt; color:#555; }
.grad { margin:0 0 2.5mm; padding:1.5mm 0 1.5mm 3mm; border-left:1.2mm solid #999; }
.grad h3 { margin:0 0 1mm; font-size:9.5pt; letter-spacing:0.3pt; }
.grad ul { margin:0; padding-left:5mm; }
.grad li { margin-bottom:0.6mm; }
.grad.fehler { border-color:#b00020; background:#fdf2f3; } .grad.fehler h3 { color:#b00020; }
.grad.warnung { border-color:#c47f00; background:#fdf8ee; } .grad.warnung h3 { color:#8a5a00; }
.grad.hinweis { border-color:#8d9199; background:#f7f8f9; } .grad.hinweis h3 { color:#4a4f57; }
.pkt { color:#888; }
.gut { color:#1b7f3b; } .schlecht { color:#b00020; font-weight:600; } .grau { color:#999; }
.fuss { margin-top:6mm; font-size:8.5pt; color:#777; }
"""


def als_html(plan: Plan, stamm: Stammdaten, bewertung, bewerter: Bewerter,
             kontozeilen=None) -> str:
    e = html.escape
    kw = plan.woche

    ist = bewerter.gesamtstunden(plan)
    soll = bewerter.gesamtbudget()
    netto = bewerter.nettostunden(plan)
    plaetze, vertrag = bewerter.tagesbilanz()
    fehler = len(bewertung.fehler())
    warnungen = len(bewertung.warnungen())

    kacheln = [
        ("Arbeitszeit", f"{ist:.0f} h", f"Soll {soll:.0f} h brutto"),
        ("bezahlt", f"{netto:.0f} h", "nach Pausenabzug"),
        ("Plaetze", f"{plaetze}", f"Vertragstage {vertrag}"),
        ("Befunde", f"{fehler} / {warnungen}",
         "Fehler / Warnungen"),
    ]
    kachel_html = "".join(
        f'<div class="kachel"><span>{e(t)}</span><b>{e(w)}</b>'
        f'<span>{e(u)}</span></div>' for t, w, u in kacheln)

    bloecke = []
    for schwere, titel, erklaerung in SCHWEREGRADE:
        gruppe = sorted((b for b in bewertung.befunde if b.schwere == schwere),
                        key=lambda b: -b.punkte)
        if not gruppe:
            continue
        eintraege = "".join(
            f'<li>{e(b.text)} <span class="pkt">({e(b.regel)})</span></li>'
            for b in gruppe)
        bloecke.append(f'<div class="grad {schwere}"><h3>{titel} &middot; '
                       f'{len(gruppe)} &middot; {erklaerung}</h3>'
                       f'<ul>{eintraege}</ul></div>')
    befund_html = "".join(bloecke) or "<p>Keine Befunde.</p>"

    stunden = []
    for mid, m in stamm.mitarbeiter.items():
        if not (m.im_plan and m.aktiv):
            continue
        tage = sum(1 for z in plan.zellen[mid].values() if z.arbeitet)
        soll_h, soll_t = bewerter._ziel(mid)
        if not (tage or soll_t):
            continue
        h = plan.netto_stunden(mid, stamm.bedarf.pause_h)
        abw = h - (soll_h - soll_t * stamm.bedarf.pause_h)
        klasse = "gut" if abs(abw) <= 3 else "schlecht"
        stunden.append(
            f'<tr><td class="ma">{e(m.name)}</td><td>{tage}</td>'
            f'<td>{soll_t}</td><td>{h:.1f}</td>'
            f'<td class="{klasse}">{abw:+.1f}</td></tr>')

    konto_html = ""
    if kontozeilen:
        tol = stamm.regeln.ausgleich_toleranz
        reihen = []
        for z in kontozeilen:
            fs = ("grau" if not z.ausgleich else
                  "schlecht" if abs(z.diff) > tol else "gut")
            sa = ("grau" if z.sa_zwingend or not z.sa_moeglich else
                  "schlecht" if z.sa_konto < -stamm.regeln.samstag_toleranz else "gut")
            reihen.append(
                f'<tr><td class="ma">{e(z.name)}</td>'
                f'<td class="{fs}">{z.diff:+d}</td>'
                f'<td>{z.sa_frei} / {z.sa_moeglich}</td>'
                f'<td class="{sa}">{z.sa_konto:+.1f}</td>'
                f'<td>{z.stunden:+.1f} h</td></tr>'
                if z.stunden == z.stunden else
                f'<tr><td class="ma">{e(z.name)}</td>'
                f'<td class="{fs}">{z.diff:+d}</td>'
                f'<td>{z.sa_frei} / {z.sa_moeglich}</td>'
                f'<td class="{sa}">{z.sa_konto:+.1f}</td><td>-</td></tr>')
        konto_html = f"""<h2>Rollierende Konten</h2>
<table><tr><th class="l">Mitarbeiter</th><th>Frueh/Spaet</th>
<th>Samstage frei</th><th>Konto</th><th>Stunden</th></tr>
{''.join(reihen)}</table>"""

    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<title>Teamleiteruebersicht {e(kw)}</title><style>{_CSS}</style></head><body>
<h1>Teamleiteruebersicht {e(kw)}</h1>
<p class="unter">{e(plan.filiale or '')} &middot; {e(plan.datum_von)} bis
   {e(plan.datum_bis or '')}</p>
<div class="kennzahl">{kachel_html}</div>

<h2>Was diese Woche auffaellt</h2>
{befund_html}

<h2>Stunden und Tage je Mitarbeiter</h2>
<table><tr><th class="l">Mitarbeiter</th><th>Tage</th><th>Soll</th>
<th>Stunden netto</th><th>gegen Soll</th></tr>
{''.join(stunden)}</table>
{konto_html}
<p class="fuss">Erzeugt vom Schichtplaner. Die Befunde sind Hinweise des
Planers, keine Vorschriften - was hier als Zugestaendnis steht, war die
guenstigste Loesung unter den geltenden Regeln.</p>
</body></html>
"""
