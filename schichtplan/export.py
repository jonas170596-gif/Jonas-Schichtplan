"""Ausgabeformate: Papierplan (HTML/Druck), CSV, e2n-Schichtliste, JSON."""
from __future__ import annotations

import csv
import datetime as dt
import html
import io
import json

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
        "notiz": plan.notiz,
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


def als_e2n_csv(plan: Plan, stamm: Stammdaten, *, arbeitsbereich: str = "",
                pause_min: int = 0, format=None) -> str:
    """Eine Zeile je Schicht, im Format aus konfig/e2n.yaml."""
    from .konfig import E2N_STANDARD
    f = format or E2N_STANDARD
    puffer = io.StringIO()
    w = csv.writer(puffer, delimiter=f.trennzeichen)
    w.writerow(f.kopf("schichten"))
    felder = f.felder("schichten")
    for mid, reihe in plan.zellen.items():
        m = stamm.mitarbeiter[mid]
        for t in plan.offene_tage:
            z = reihe[t]
            if not z.arbeitet:
                continue
            werte = {
                "mitarbeiter": m.name,
                "nachname": m.name.split(". ")[-1],
                "vorname": m.vorname,
                "personalnummer": m.personalnummer,
                "datum": _datum(plan, t).strftime(f.datumsformat),
                "beginn": _zeit(z.schicht.von, f),
                "ende": _zeit(z.schicht.bis, f),
                "pause": pause_min,
                "dauer": f"{z.schicht.dauer_h:.2f}".replace(".", ","),
                "arbeitsbereich": arbeitsbereich,
                "notiz": ", ".join(z.zusatz),
            }
            w.writerow([werte.get(feld, "") for feld in felder])
    return puffer.getvalue()


def als_abwesenheits_csv(plan: Plan, stamm: Stammdaten, *, format=None) -> str:
    """Urlaub, Krankheit und Berufsschule - in e2n eine eigene Datensatzart."""
    from .konfig import E2N_STANDARD
    f = format or E2N_STANDARD
    puffer = io.StringIO()
    w = csv.writer(puffer, delimiter=f.trennzeichen)
    w.writerow(f.kopf("abwesenheiten"))
    felder = f.felder("abwesenheiten")
    for mid, reihe in plan.zellen.items():
        m = stamm.mitarbeiter[mid]
        for t in plan.offene_tage:
            art = reihe[t].art
            if art not in ("urlaub", "schule", "krank", "sonstige"):
                continue
            werte = {
                "mitarbeiter": m.name,
                "nachname": m.name.split(". ")[-1],
                "vorname": m.vorname,
                "personalnummer": m.personalnummer,
                "datum": _datum(plan, t).strftime(f.datumsformat),
                "art": f.arten.get(art, art),
            }
            w.writerow([werte.get(feld, "") for feld in felder])
    return puffer.getvalue()


def _zeit(slot: int, f) -> str:
    """Slotindex als Uhrzeit im eingestellten Format."""
    text = zu_zeit(slot)
    if f.zeitformat == "%H:%M":
        return text
    stunde, minute = (int(x) for x in text.split(":"))
    return dt.time(stunde % 24, minute).strftime(f.zeitformat)


# --------------------------------------------------------------------- #
_CSS = """
@page { size: A4 AUSRICHTUNG; margin: 10mm; }
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
tr.zusatz-zeile td.ma { font-weight:600; color:#555; font-style:italic; }
td.leer { background:repeating-linear-gradient(0deg,#fff,#fff 10px,#f4f4f4 10px,#f4f4f4 11px); }
.fuss { margin-top:4mm; font-size:8.5pt; color:#555; display:flex; justify-content:space-between; }
.budget { margin-top:4mm; font-size:10pt; }
.notiz { margin-top:4mm; padding:2.5mm 3mm; border:1px solid #bbb;
         border-radius:1mm; font-size:10pt; line-height:1.5; }
@media print {                """


def _schluessel(text: str) -> str:
    """Zeilenname auf Vergleichbares reduzieren: Palmstrasse == Palmstrasse."""
    ersetzt = text.lower().replace("\u00df", "ss").replace("\u00e4", "ae") \
                  .replace("\u00f6", "oe").replace("\u00fc", "ue")
    return "".join(c for c in ersetzt if c.isalnum())


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
        # Aushilfen, die diese Woche gar nicht eingeteilt sind, bekommen eine
        # leere Zeile statt sechsmal "Frei" - so wie frueher die Leerzeile
        # unten auf dem Formular. Falls doch jemand einspringt, kann man es
        # von Hand eintragen.
        if m.moeglichst_wenig and not any(z.arbeitet for z in reihe.values()):
            leer = "".join('<td class="leer"></td>' for _ in alle)
            zeilen.append(f'<tr class="zusatz-zeile"><td class="ma">'
                          f'{e(m.name)}</td>{leer}'
                          f'<td class="summe leer"></td></tr>')
            continue
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

    # Leerzeilen zum Eintragen von Hand - auf dem Papierplan steht unten die
    # Zeile fuer die Aushilfe aus der Palmstrasse. Ist die Aushilfe in dieser
    # Woche schon eingeplant, steht sie oben mit ihren Schichten drin; dann
    # waere die Leerzeile dieselbe Zeile ein zweites Mal.
    gesetzt = {_schluessel(stamm.mitarbeiter[mid].name) for mid in plan.zellen}
    for beschriftung in stamm.bedarf.zusatzzeilen:
        if _schluessel(beschriftung) in gesetzt:
            continue
        leer = "".join('<td class="leer"></td>' for _ in alle)
        zeilen.append(f'<tr class="zusatz-zeile"><td class="ma">{e(beschriftung)}</td>'
                      f'{leer}<td class="summe leer"></td></tr>')

    budget = ""
    if bewerter is not None and bewerter.gesamtbudget():
        ist, ziel = bewerter.gesamtstunden(plan), bewerter.gesamtbudget()
        ampel = "#1b7f3b" if abs(ist - ziel) <= \
            stamm.bedarf.wochenstunden_gesamt_toleranz else "#b00020"
        erreichbar = bewerter.erreichbare_stunden()
        zusatz = (f", diese Woche unterzubringen sind hoechstens {erreichbar:.0f} h"
                  if erreichbar < ziel - stamm.bedarf.wochenstunden_gesamt_toleranz
                  else "")
        b = stamm.bedarf
        umsatz = (f' bei {b.umsatz_erwartet:,.0f} EUR Umsatz und '
                  f'{b.umsatz_je_stunde:.0f} EUR/Std.'.replace(",", ".")
                  if b.umsatz_erwartet and b.umsatz_je_stunde else "")
        budget = (f'<div class="budget">Arbeitszeit gesamt: '
                  f'<b style="color:{ampel}">{ist:.1f} h brutto</b> '
                  f'(Soll {ziel:.0f} h{e(umsatz)}{e(zusatz)}) &mdash; '
                  f'{bewerter.nettostunden(plan):.1f} h bezahlt, abzueglich '
                  f'{bewerter.schichtzahl(plan, alle=True)} &times; '
                  f'{b.pause_minuten} min Pause</div>')

    # Der Papierplan haengt im Laden aus - dort haben Befunde nichts zu
    # suchen. Sie stehen in der Teamleiteruebersicht und in der Oberflaeche.
    # Was hier hingehoert, ist die freie Bemerkung der Woche.
    hinweise = ""
    if plan.notiz:
        zeilen_notiz = "<br>".join(e(z) for z in plan.notiz.splitlines() if z.strip())
        hinweise = f'<div class="notiz">{zeilen_notiz}</div>'

    kopfzeilen = "".join(f"<th>{TAG_LANG[t]}</th>" for t in alle)
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<title>{e(kopf)} {e(kw)}</title>
<style>{_CSS.replace("AUSRICHTUNG", "portrait" if stamm.bedarf.papier_hoch else "landscape")}</style>
</head><body>
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
