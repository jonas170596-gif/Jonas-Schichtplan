"""Ausgabeformate: Papierplan (HTML/Druck), CSV, e2n-Schichtliste, JSON."""
from __future__ import annotations

import csv
import datetime as dt
import html
import io
import json

from .bewertung import SCHWEREGRADE
from .konfig import Stammdaten
from .modelle import TAG_LANG, Plan, zu_zeit


def _datum(plan: Plan, tag: str) -> dt.date:
    start = dt.date.fromisoformat(plan.datum_von)
    from .modelle import TAGE
    return start + dt.timedelta(days=TAGE.index(tag))


# --------------------------------------------------------------------- #
def als_json(plan: Plan, stamm: Stammdaten) -> str:
    doc = {
        "woche": plan.woche,
        "datum_von": plan.datum_von,
        "datum_bis": plan.datum_bis,
        "filiale": plan.filiale,
        "status": "generiert",
        "tage": plan.offene_tage,
        "plan": {
            mid: {
                t: ({"art": "schicht", "von": zu_zeit(z.schicht.von),
                     "bis": zu_zeit(z.schicht.bis), "zusatz": z.zusatz}
                    if z.arbeitet else {"art": z.art, "zusatz": z.zusatz})
                for t, z in reihe.items()
            }
            for mid, reihe in plan.zellen.items()
        },
    }
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def als_csv(plan: Plan, stamm: Stammdaten) -> str:
    """Breites Raster wie auf dem Papier - gut zum Gegenlesen in Excel."""
    puffer = io.StringIO()
    w = csv.writer(puffer, delimiter=";")
    w.writerow(["Mitarbeiter"] + [TAG_LANG[t] for t in plan.offene_tage]
               + ["Stunden", "Tage"])
    for mid, reihe in plan.zellen.items():
        m = stamm.mitarbeiter[mid]
        w.writerow([m.name] + [reihe[t].label() for t in plan.offene_tage]
                   + [f"{plan.stunden(mid):.1f}".replace(".", ","),
                      plan.arbeitstage(mid)])
    return puffer.getvalue()


def als_e2n_csv(plan: Plan, stamm: Stammdaten, *,
                arbeitsbereich: str = "", pause_min: int = 0) -> str:
    """Eine Zeile je Schicht - das Format, das Dienstplan-Importe erwarten.
    Spaltennamen ggf. an die eigene e2n-Importvorlage anpassen."""
    puffer = io.StringIO()
    w = csv.writer(puffer, delimiter=";")
    w.writerow(["Mitarbeiter", "Personalnummer", "Datum", "Beginn", "Ende",
                "Pause_Minuten", "Arbeitsbereich", "Notiz"])
    for mid, reihe in plan.zellen.items():
        m = stamm.mitarbeiter[mid]
        for t in plan.offene_tage:
            z = reihe[t]
            if not z.arbeitet:
                continue
            w.writerow([m.name, "", _datum(plan, t).strftime("%d.%m.%Y"),
                        zu_zeit(z.schicht.von), zu_zeit(z.schicht.bis),
                        pause_min, arbeitsbereich, ", ".join(z.zusatz)])
    return puffer.getvalue()


def als_abwesenheits_csv(plan: Plan, stamm: Stammdaten) -> str:
    """Urlaub/Schule/Krank getrennt - in e2n eigene Datensatzart."""
    puffer = io.StringIO()
    w = csv.writer(puffer, delimiter=";")
    w.writerow(["Mitarbeiter", "Datum", "Art"])
    for mid, reihe in plan.zellen.items():
        m = stamm.mitarbeiter[mid]
        for t in plan.offene_tage:
            if reihe[t].art in ("urlaub", "schule", "krank", "sonstige"):
                w.writerow([m.name, _datum(plan, t).strftime("%d.%m.%Y"), reihe[t].art])
    return puffer.getvalue()


# --------------------------------------------------------------------- #
_CSS = """
@page { size: A4 landscape; margin: 10mm; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", Arial, sans-serif; color:#111; margin:0; padding:10mm; }
.kopf { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:6mm; }
.kopf h1 { font-size:15pt; margin:0 0 2mm; text-align:center; flex:1; }
.meta { font-size:10.5pt; line-height:1.6; white-space:nowrap; }
.meta b { font-weight:600; }
table { width:100%; border-collapse:collapse; table-layout:fixed; }
th, td { border:1px solid #333; padding:3mm 2mm; font-size:10.5pt; text-align:center;
         height:11mm; vertical-align:middle; }
th { background:#eceff1; font-weight:700; }
td.ma { text-align:left; font-weight:600; background:#fafafa; }
td.frei { color:#777; }
td.abw { color:#777; font-style:italic; background:#f4f4f4; }
td.zu { background:repeating-linear-gradient(45deg,#fff,#fff 6px,#eee 6px,#eee 12px); }
td.summe { font-size:9.5pt; color:#444; background:#fafafa; }
th.summe { font-size:9.5pt; }
.zusatz { display:block; font-size:8pt; color:#555; }
.fuss { margin-top:4mm; font-size:8.5pt; color:#555; display:flex; justify-content:space-between; }
.budget { margin-top:4mm; font-size:10pt; }
.hinweise { margin-top:5mm; font-size:9pt; }
.hinweise ul { margin:1mm 0 0; padding-left:5mm; }
.hinweise li { margin-bottom:0.8mm; }
.grad { margin-top:3mm; padding:1.5mm 0 1.5mm 3mm; border-left:1.2mm solid #999; }
.grad h4 { margin:0; font-size:9pt; letter-spacing:0.3pt; }
.grad .was { font-weight:400; color:#555; }
.grad.fehler  { border-color:#b00020; background:#fdf2f3; }
.grad.fehler h4  { color:#b00020; }
.grad.warnung { border-color:#c47f00; background:#fdf8ee; }
.grad.warnung h4 { color:#8a5a00; }
.grad.hinweis { border-color:#8d9199; background:#f7f8f9; }
.grad.hinweis h4 { color:#4a4f57; }
.grad .pkt { color:#777; }
@media print { .hinweise { page-break-before:avoid; }
               .grad { break-inside:avoid; } }
"""


def als_html(plan: Plan, stamm: Stammdaten, bewertung=None,
             titel: str | None = None, bewerter=None) -> str:
    e = html.escape
    tage = plan.offene_tage
    alle = [t for t in stamm.bedarf.offene_tage]
    kw = plan.woche.split("-")[-1]
    kopf = titel or f"Wocheneinsatzplan {plan.filiale or ''}".strip()

    zeilen = []
    for mid, reihe in plan.zellen.items():
        m = stamm.mitarbeiter[mid]
        tds = [f'<td class="ma">{e(m.name)}</td>']
        for t in alle:
            z = reihe.get(t)
            if z is None or z.art == "feiertag":
                tds.append('<td class="zu"></td>')
                continue
            klasse = ("frei" if z.art == "frei"
                      else "abw" if not z.arbeitet else "")
            inhalt = e(z.schicht.label) if z.arbeitet else e(z.label())
            if z.zusatz:
                inhalt += f'<span class="zusatz">+ {e(", ".join(z.zusatz))}</span>'
            tds.append(f'<td class="{klasse}">{inhalt}</td>')
        netto = plan.netto_stunden(mid, stamm.bedarf.pause_h)
        schichten = plan.arbeitstage(mid)
        praesenz = plan.praesenztage(mid, tuple(m.abwesenheit_stunden))
        tage_text = (f"{praesenz} Tage" if praesenz == schichten
                     else f"{praesenz} Tage ({schichten} + {praesenz - schichten} Schule)")
        tds.append(f'<td class="summe">{netto:.1f} h<span class="zusatz">'
                   f'{tage_text}</span></td>')
        zeilen.append("<tr>" + "".join(tds) + "</tr>")

    budget = ""
    if bewerter is not None and bewerter.gesamtbudget():
        ist, ziel = bewerter.gesamtstunden(plan), bewerter.gesamtbudget()
        ampel = "#1b7f3b" if abs(ist - ziel) <= \
            stamm.bedarf.wochenstunden_gesamt_toleranz else "#b00020"
        erreichbar = bewerter.erreichbare_stunden()
        zusatz = (f", diese Woche unterzubringen sind hoechstens {erreichbar:.0f} h"
                  if erreichbar < ziel - stamm.bedarf.wochenstunden_gesamt_toleranz
                  else "")
        budget = (f'<div class="budget">Verkaeuferstunden gesamt: '
                  f'<b style="color:{ampel}">{ist:.1f} h netto</b> '
                  f'(Budget {ziel:.0f} h{e(zusatz)}; '
                  f'{bewerter.bruttostunden(plan):.1f} h Anwesenheit abzueglich '
                  f'{stamm.bedarf.pause_minuten} min Pause je Schicht, '
                  f'Azubistunden nicht gezaehlt)</div>')

    hinweise = ""
    if bewertung is not None:
        if bewertung.befunde:
            bloecke = []
            for schwere, titel, erklaerung in SCHWEREGRADE:
                gruppe = sorted((b for b in bewertung.befunde if b.schwere == schwere),
                                key=lambda b: -b.punkte)
                if not gruppe:
                    continue
                summe = sum(b.punkte for b in gruppe)
                eintraege = "".join(
                    f'<li>{e(b.text)} <span class="pkt">({e(b.regel)}, '
                    f'{b.punkte:.0f})</span></li>' for b in gruppe)
                bloecke.append(
                    f'<div class="grad {schwere}"><h4>{titel} &middot; {len(gruppe)} '
                    f'&middot; {summe:.0f} Punkte <span class="was">- {erklaerung}'
                    f'</span></h4><ul>{eintraege}</ul></div>')
            hinweise = (f'<div class="hinweise"><b>Hinweise des Planers '
                        f'({bewertung.punkte:.0f} Strafpunkte)</b>'
                        f'{"".join(bloecke)}</div>')
        else:
            hinweise = ('<div class="hinweise"><b>Keine Regelverletzungen.</b></div>')

    kopfzeilen = "".join(f"<th>{TAG_LANG[t]}</th>" for t in alle)
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<title>{e(kopf)} {e(kw)}</title><style>{_CSS}</style></head><body>
<div class="kopf">
  <div class="meta"><b>Woche:</b> {e(kw)}<br><b>Datum von:</b> {e(plan.datum_von)}
    &nbsp; <b>bis:</b> {e(plan.datum_bis or '')}</div>
  <h1>{e(kopf)}</h1>
  <div class="meta" style="text-align:right">Generiert<br>{dt.date.today():%d.%m.%Y}</div>
</div>
<table>
  <thead><tr><th style="width:15%">Mitarbeiter</th>{kopfzeilen}
    <th class="summe" style="width:10%">Summe netto</th></tr></thead>
  <tbody>{''.join(zeilen)}</tbody>
</table>
{budget}
{hinweise}
<div class="fuss"><span>{e(plan.filiale)}</span><span>schichtplan-generator</span></div>
</body></html>
"""
