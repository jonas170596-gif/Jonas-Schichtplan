"""Kommandozeile:

  python -m schichtplan analyse                    Muster der Altplaene anzeigen
  python -m schichtplan analyse --konfig-vorschlag Konfig aus Historie neu ableiten
  python -m schichtplan neu 2025-KW42              Wochenvorgabe anlegen
  python -m schichtplan plan wochen/2025-KW42.yaml Plan rechnen und exportieren
  python -m schichtplan pruefen ausgabe/2025-KW42.json wochen/2025-KW42.yaml
  python -m schichtplan backtest                   Konfig gegen die Altplaene messen
  python -m schichtplan ausgleich                  Frueh/Spaet-Bilanz je Mitarbeiter
  python -m schichtplan uebernehmen ausgabe/2025-KW43.json
                                                   fertigen Plan in die Historie legen
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

import yaml

from . import analyse as _analyse
from . import backtest as _backtest
from . import export
from .bewertung import Bewerter
from .bewertung import pruefen as _pruefen
from .generator import erzeuge
from .historie import lade_historie
from .konfig import KONFIG_DIR, lade_stammdaten, lade_wochenvorgabe
from .modelle import TAGE, Plan, Zelle, zu_index

VORLAGE = """# Wochenvorgabe {woche} - alles, was sich von Woche zu Woche aendert.
# Tageskuerzel: mo di mi do fr sa   (weglassen/'alle' = ganze Woche)

woche: {woche}
datum_von: {von}          # Montag
datum_bis: {bis}          # Samstag
filiale: Winterbach

# Tage, an denen der Laden zu ist (Feiertage)
geschlossen: []

# --- Abwesenheiten (hart) ---
urlaub: {{}}
#  reich_s: alle
#  kohl_b: [do, fr, sa]

schule: {{}}               # Berufsschule Azubi
#  menzler_a: [mi, do]

krank: {{}}
sonstige: {{}}

# --- Harte Vorgaben: genau diese Schicht / genau frei ---
fest: {{}}
#  kurka_j: {{sa: 6-14}}
#  marino_a: {{mo: frei}}

# --- Wuensche (weich, der Planer versucht sie zu erfuellen) ---
wunsch_frei: {{}}
#  nachtrieb_i: [mi]

wunsch_schicht: {{}}
#  kohl_b: {{fr: 6-13:30}}

# --- Termine: Schicht muss zu dieser Zeit enden ---
termine: []
#  - name: Teamleitersitzung
#    tag: di
#    ab: "13:30"
#    kandidaten: [kurka_j, rohwer_c]
#    anzahl: 1
#    abwechselnd: true      # nicht dieselbe Person wie beim letzten Mal

# --- Zusatzaufgaben, die im Plan vermerkt werden ---
zusatz: {{}}
#  rohwer_c: {{sa: [grossputz]}}

# --- Abweichendes Wochensoll (z. B. Stundenabbau) ---
soll_stunden: {{}}
#  kurz_u: 12

notiz: ""
"""


def _mitarbeiterliste() -> list[str]:
    return list(lade_stammdaten().mitarbeiter)


def cmd_analyse(args) -> int:
    wochen = lade_historie(args.historie)
    if not wochen:
        print("Keine finalen Altplaene in", args.historie, file=sys.stderr)
        return 1
    if args.konfig_vorschlag:
        ziel = pathlib.Path(args.konfig_vorschlag)
        ziel.mkdir(parents=True, exist_ok=True)
        for name, doc in _analyse.konfig_vorschlag(wochen).items():
            pfad = ziel / f"{name}.yaml"
            pfad.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
                            encoding="utf-8")
            print("geschrieben:", pfad)
        print("\nVorschlaege pruefen und nach konfig/ uebernehmen - sie ueberschreiben "
              "sonst handgepflegte Werte.")
        return 0
    print(_analyse.bericht(wochen))
    return 0


def cmd_neu(args) -> int:
    woche = args.woche
    jahr, _, kw = woche.partition("-KW")
    try:
        montag = dt.date.fromisocalendar(int(jahr), int(kw), 1)
    except ValueError:
        print(f"Wochenkennung muss 'JJJJ-KWnn' sein, nicht {woche!r}", file=sys.stderr)
        return 2
    pfad = pathlib.Path(args.ordner) / f"{woche}.yaml"
    if pfad.exists() and not args.ueberschreiben:
        print(f"{pfad} existiert bereits (--ueberschreiben erzwingt)", file=sys.stderr)
        return 1
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(VORLAGE.format(woche=woche, von=montag,
                                   bis=montag + dt.timedelta(days=5)), encoding="utf-8")
    print("angelegt:", pfad)
    print("Mitarbeiterkuerzel:", ", ".join(_mitarbeiterliste()))
    return 0


def cmd_plan(args) -> int:
    stamm = lade_stammdaten(args.konfig)
    vorgabe = lade_wochenvorgabe(args.vorgabe)
    vorwochen = lade_historie(args.historie) if args.historie else []

    erg = erzeuge(stamm, vorgabe, vorwochen,
                  iterationen=args.iterationen, neustarts=args.neustarts, seed=args.seed)
    plan, bew = erg.plan, erg.bewertung

    bewerter = Bewerter(stamm, vorgabe, vorwochen)
    ziel = pathlib.Path(args.ausgabe)
    ziel.mkdir(parents=True, exist_ok=True)
    basis = ziel / plan.woche
    dateien = {
        f"{basis}.html": export.als_html(plan, stamm, bew, bewerter=bewerter),
        f"{basis}.json": export.als_json(plan, stamm),
        f"{basis}.csv": export.als_csv(plan, stamm),
        f"{basis}-e2n-schichten.csv": export.als_e2n_csv(
            plan, stamm, arbeitsbereich=args.arbeitsbereich, pause_min=args.pause),
        f"{basis}-e2n-abwesenheiten.csv": export.als_abwesenheits_csv(plan, stamm),
    }
    for pfad, inhalt in dateien.items():
        pathlib.Path(pfad).write_text(inhalt, encoding="utf-8")

    print(_textplan(plan, stamm, bewerter))
    print(f"\nStrafpunkte: {bew.punkte:.0f}  (Greedy-Start: {erg.startpunkte:.0f})")
    _zeige_befunde(bew)
    print("\nGeschrieben:")
    for pfad in dateien:
        print("  ", pfad)
    return 1 if bew.fehler() else 0


def cmd_backtest(args) -> int:
    stamm = lade_stammdaten(args.konfig)
    wochen = lade_historie(args.historie)
    if not wochen:
        print("Keine finalen Altplaene in", args.historie, file=sys.stderr)
        return 1
    if args.woche:
        wochen = [w for w in wochen if w.woche in args.woche]
    print(_backtest.bericht(wochen, stamm, seed=args.seed, iterationen=args.iterationen))
    return 0


def cmd_ausgleich(args) -> int:
    """Frueh/Spaet-Verhaeltnis je Mitarbeiter ueber das rollierende Fenster."""
    stamm = lade_stammdaten(args.konfig)
    wochen = lade_historie(args.historie)
    fenster = args.fenster or stamm.regeln.ausgleich_fenster_wochen
    if not wochen:
        print("Keine Altplaene in", args.historie, file=sys.stderr)
        return 1
    betrachtet = wochen[-fenster:]
    print(f"Frueh/Spaet ueber {len(betrachtet)} Wochen "
          f"({betrachtet[0].woche} bis {betrachtet[-1].woche})\n")
    print(f"{'Mitarbeiter':<18}{'Frueh':>6}{'Spaet':>6}{'Mittel':>7}"
          f"{'Differenz':>11}  Verteilung")
    print("-" * 68)
    schief = []
    for mid, m in stamm.mitarbeiter.items():
        if not (m.im_plan and m.aktiv):
            continue
        zaehler = {"frueh": 0, "spaet": 0, "mittel": 0}
        for w in betrachtet:
            for z in w.plan.get(mid, {}).values():
                if z.verwertbar:
                    zaehler[stamm.kategorie_von(z.von, z.bis)] += 1
        f, s = zaehler["frueh"], zaehler["spaet"]
        if f + s == 0:
            balken = ""
        else:
            balken = "F" * f + "S" * s
        marke = ""
        if m.frueh_spaet_ausgleich and abs(f - s) > stamm.regeln.ausgleich_toleranz:
            marke = "  <-- schief"
            schief.append(m.name)
        elif not m.frueh_spaet_ausgleich:
            marke = "  (ausgenommen)"
        print(f"{m.name:<18}{f:>6}{s:>6}{zaehler['mittel']:>7}{f - s:>+11}"
              f"  {balken}{marke}")
    print()
    if schief:
        print("Schief: " + ", ".join(schief))
        print("Der Planer zieht das ueber die naechsten Wochen gerade, solange die "
              "fertigen Plaene mit 'uebernehmen' in der Historie landen.")
    else:
        print("Alle innerhalb der Toleranz von "
              f"{stamm.regeln.ausgleich_toleranz} Schichten.")
    return 0


def cmd_uebernehmen(args) -> int:
    """Fertigen Plan in die Historie legen, damit Ausgleich und Fairness ihn sehen."""
    stamm = lade_stammdaten(args.konfig)
    quelle = pathlib.Path(args.plan)
    roh = json.loads(quelle.read_text(encoding="utf-8"))
    roh["status"] = "final"
    roh.setdefault("quelle_foto", "")
    roh["notiz"] = (roh.get("notiz", "") + " " if roh.get("notiz") else "") \
        + f"generiert, uebernommen aus {quelle.name}"
    fehlend = [t for t in TAGE
               for reihe in roh["plan"].values() if t not in reihe]
    if fehlend:
        print(f"Plan ist unvollstaendig, es fehlen Tage: {sorted(set(fehlend))}",
              file=sys.stderr)
        return 1
    ziel = pathlib.Path(args.historie) / f"{roh['woche']}.json"
    if ziel.exists() and not args.ueberschreiben:
        print(f"{ziel} existiert bereits (--ueberschreiben erzwingt)", file=sys.stderr)
        return 1
    ziel.write_text(json.dumps(roh, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print("uebernommen:", ziel)
    print(f"Historie umfasst jetzt {len(lade_historie(args.historie))} finale Wochen.")
    return 0


def cmd_pruefen(args) -> int:
    stamm = lade_stammdaten(args.konfig)
    vorgabe = lade_wochenvorgabe(args.vorgabe)
    plan = _plan_aus_json(pathlib.Path(args.plan), stamm)
    vorwochen = lade_historie(args.historie) if args.historie else []
    bew = _pruefen(plan, stamm, vorgabe, vorwochen)
    print(_textplan(plan, stamm, Bewerter(stamm, vorgabe, vorwochen)))
    print(f"\nStrafpunkte: {bew.punkte:.0f}")
    _zeige_befunde(bew)
    return 1 if bew.fehler() else 0


def _plan_aus_json(pfad: pathlib.Path, stamm) -> Plan:
    roh = json.loads(pfad.read_text(encoding="utf-8"))
    nach_zeit = {(s.von, s.bis): s for s in stamm.schichten.values()}
    zellen = {}
    for mid, tage in roh["plan"].items():
        reihe = {}
        for t, c in tage.items():
            if c["art"] == "schicht":
                schluessel = (zu_index(c["von"]), zu_index(c["bis"]))
                schicht = nach_zeit.get(schluessel)
                if schicht is None:
                    from .modelle import Schicht, zu_text
                    schicht = Schicht(f"{zu_text(schluessel[0])}-{zu_text(schluessel[1])}",
                                      *schluessel)
                reihe[t] = Zelle("schicht", schicht, list(c.get("zusatz", [])))
            else:
                reihe[t] = Zelle(c["art"], zusatz=list(c.get("zusatz", [])))
        zellen[mid] = reihe
    return Plan(roh["woche"], roh["datum_von"], roh.get("datum_bis", ""), zellen,
                roh.get("filiale", ""), roh.get("tage", TAGE))


def _textplan(plan: Plan, stamm, bewerter=None) -> str:
    from .modelle import TAG_LANG
    tage = plan.offene_tage
    breite = 11
    kopf = f"{'Mitarbeiter':<18}" + "".join(f"{TAG_LANG[t][:9]:<{breite}}" for t in tage)
    zeilen = [f"{plan.woche}  {plan.datum_von} - {plan.datum_bis}  {plan.filiale}",
              kopf, "-" * len(kopf)]
    for mid, reihe in plan.zellen.items():
        m = stamm.mitarbeiter[mid]
        z = f"{m.name:<18}" + "".join(f"{reihe[t].label():<{breite}}" for t in tage)
        zeilen.append(f"{z}  {plan.stunden(mid):5.1f} h / {plan.arbeitstage(mid)} T")
    zeilen.append("-" * len(kopf))
    zeilen.append(f"{'Koepfe':<18}" + "".join(f"{plan.koepfe(t):<{breite}}" for t in tage))
    if bewerter is not None and bewerter.gesamtbudget():
        ist, ziel = bewerter.gesamtstunden(plan), bewerter.gesamtbudget()
        zeilen.append(f"{'Stunden gesamt':<18}{ist:.1f} h (Budget {ziel:.1f} h, "
                      f"Azubi nicht gezaehlt)")
    return "\n".join(zeilen)


def _zeige_befunde(bew) -> None:
    if not bew.befunde:
        print("Keine Regelverletzungen.")
        return
    for schwere, marke in (("fehler", "FEHLER "), ("warnung", "Warnung"), ("hinweis", "Hinweis")):
        for b in bew.befunde:
            if b.schwere == schwere:
                print(f"  {marke}  {b.text}  ({b.regel}, {b.punkte:.0f})")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="schichtplan", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--konfig", default=str(KONFIG_DIR), help="Ordner mit den Stammdaten")
    sub = p.add_subparsers(dest="befehl", required=True)

    a = sub.add_parser("analyse", help="Muster der Altplaene auswerten")
    a.add_argument("--historie", default="daten/historie")
    a.add_argument("--konfig-vorschlag", metavar="ORDNER",
                   help="Konfig-YAML aus der Historie ableiten")
    a.set_defaults(func=cmd_analyse)

    n = sub.add_parser("neu", help="Wochenvorgabe anlegen")
    n.add_argument("woche", help="z. B. 2025-KW42")
    n.add_argument("--ordner", default="wochen")
    n.add_argument("--ueberschreiben", action="store_true")
    n.set_defaults(func=cmd_neu)

    g = sub.add_parser("plan", help="Plan erzeugen")
    g.add_argument("vorgabe")
    g.add_argument("--ausgabe", default="ausgabe")
    g.add_argument("--historie", default="daten/historie",
                   help="fuer Fairness ueber Wochen hinweg; leer = aus")
    g.add_argument("--iterationen", type=int, default=40000)
    g.add_argument("--neustarts", type=int, default=4)
    g.add_argument("--seed", type=int, default=1)
    g.add_argument("--arbeitsbereich", default="", help="Spaltenwert fuer den e2n-Export")
    g.add_argument("--pause", type=int, default=0, help="Pausenminuten im e2n-Export")
    g.set_defaults(func=cmd_plan)

    bt = sub.add_parser("backtest", help="Konfiguration gegen die Altplaene messen")
    bt.add_argument("--historie", default="daten/historie")
    bt.add_argument("--woche", nargs="*", help="nur diese Wochen, z. B. 2025-KW41")
    bt.add_argument("--iterationen", type=int, default=20000)
    bt.add_argument("--seed", type=int, default=1)
    bt.set_defaults(func=cmd_backtest)

    au = sub.add_parser("ausgleich", help="Frueh/Spaet-Bilanz je Mitarbeiter")
    au.add_argument("--historie", default="daten/historie")
    au.add_argument("--fenster", type=int, help="Anzahl Wochen (sonst aus regeln.yaml)")
    au.set_defaults(func=cmd_ausgleich)

    ue = sub.add_parser("uebernehmen", help="fertigen Plan in die Historie legen")
    ue.add_argument("plan", help="JSON aus ausgabe/")
    ue.add_argument("--historie", default="daten/historie")
    ue.add_argument("--ueberschreiben", action="store_true")
    ue.set_defaults(func=cmd_uebernehmen)

    v = sub.add_parser("pruefen", help="bestehenden Plan gegen die Regeln pruefen")
    v.add_argument("plan")
    v.add_argument("vorgabe")
    v.add_argument("--historie", default="daten/historie")
    v.set_defaults(func=cmd_pruefen)

    args = p.parse_args(argv)
    return args.func(args)
