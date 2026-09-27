# Wocheneinsatzplan Winterbach - automatische Erzeugung

Erzeugt den Wochenplan aus Stammdaten + den Variablen, die sich jede Woche
aendern (Urlaub, Schule, Wunschfrei, Feiertage). Grundlage sind 14 digitalisierte
Altplaene aus KW28-KW41/2025.

Reines Python 3.11 + PyYAML, kein Solver-Paket, keine Datenbank.

## Schnellstart

```bash
pip install pyyaml

python -m schichtplan analyse              # was steckt in den Altplaenen?
python -m schichtplan neu 2025-KW43        # Wochenvorgabe anlegen
$EDITOR wochen/2025-KW43.yaml              # Urlaub, Schule, Wuensche eintragen
python -m schichtplan plan wochen/2025-KW43.yaml
```

Ergebnis in `ausgabe/`:

| Datei | wofuer |
|---|---|
| `<woche>.html` | Druckansicht im Layout des Papierplans (A4 quer) |
| `<woche>.csv` | dasselbe Raster fuer Excel |
| `<woche>.json` | maschinenlesbar, Eingabe fuer `pruefen` |
| `<woche>-e2n-schichten.csv` | eine Zeile je Schicht fuer e2n |
| `<woche>-e2n-abwesenheiten.csv` | Urlaub/Schule/Krank getrennt |

## Die Wochenvorgabe

Eine YAML-Datei je Woche. Alles optional - was nicht drinsteht, entscheidet
der Planer selbst.

```yaml
woche: 2025-KW43
datum_von: 2025-10-20
datum_bis: 2025-10-25

geschlossen: []                  # Feiertage

urlaub:
  reich_s: alle                  # ganze Woche
  kohl_b: [do, fr, sa]           # einzelne Tage
schule:
  menzler_a: [do]
krank: {}

fest:                            # harte Vorgabe, wird nicht angetastet
  kurka_j: {sa: 6-14}
  marino_a: {mo: frei}

wunsch_frei:                     # weich - der Planer versucht es
  nachtrieb_i: [mi]
wunsch_schicht:
  kohl_b: {fr: 6-13:30}

zusatz:                          # erscheint als Vermerk im Plan
  rohwer_c: {sa: [grossputz]}

soll_stunden:                    # abweichendes Wochensoll
  kurz_u: 12
```

Wiederkehrende Termine, fuer die jemand frueher Schluss machen muss, kommen
in dieselbe Datei - der Planer sucht sich dann einen der Kandidaten aus und
gibt ihm eine Schicht, die genau zu der Zeit endet:

```yaml
termine:
  - name: Teamleitersitzung
    tag: di
    ab: "13:30"
    kandidaten: [kurka_j, rohwer_c]
    anzahl: 1
```

**Feste freie Tage** stehen dagegen in `konfig/mitarbeiter.yaml`
(`feste_freie_tage`) und gelten in jeder Woche, ohne dass man sie neu eintraegt.
Nicht jeder hat welche - das Feld darf leer bleiben.

## Die Wochenmodelle

| | Stunden | Tage | feste freie Tage | Besonderheit |
|---|---|---|---|---|
| J. Kurka | 40 | 5 | - | freier Tag variabel; Frueh-Anker; Sitzungskandidat |
| C. Rohwer | 40 | 5 | Mi | Sitzungskandidat |
| A. Marino | 40 | 5 | Mo | |
| N. Sannzenbacher | 32* | 4 | - | |
| S. Reich | 30* | 4 | Mo, Mi | Aenderung nur nach Absprache |
| I. Nachtrieb | 24 | 3 (bis 5) | - | Monatsmittel, Wochentoleranz +/- 8 h |
| B. Kohl | 30 | 4 | - | zwei freie Tage, moeglichst zusammenhaengend |
| C. Kurz | 17* | 3 | Di, Fr, Sa | |
| U. Kurz | Reserve | - | Di | so wenig wie moeglich, breit einsetzbar |
| A. Menzler | 32 | 4 | - | Azubi, zaehlt nicht gegen das Stundenbudget |

\* aus der Historie abgeleitet, Vertragswert noch offen.

**Aenderung nur nach Absprache** heisst technisch: der Tag steht in
`feste_freie_tage` und wird nur ueberschrieben, wenn er in der Wochenvorgabe
unter `fest` auftaucht - dann hat die Wochenvorgabe Vorrang.

## Konfiguration

| Datei | Inhalt |
|---|---|
| `konfig/mitarbeiter.yaml` | Sollstunden, Solltage, feste freie Tage, erlaubte und gewohnte Schichten |
| `konfig/schichten.yaml` | Schichtkatalog (`6-14`, `11-20`, ...) inkl. an welchen Tagen erlaubt |
| `konfig/bedarf.yaml` | Kopfzahl, Frueh-/Schlussbesetzung, Mindestbesetzungskurve, Wochenstundenbudget |
| `konfig/team.yaml` | wer muss da sein, wer darf nicht zusammen - hier kommen auch die Qualifikationen rein |
| `konfig/regeln.yaml` | Gewichte aller Regeln, Ruhezeit, Toleranzen |

Die Startwerte wurden aus der Historie abgeleitet, nicht geraten. Neu ableiten
lassen (nachdem weitere Altplaene dazugekommen sind):

```bash
python -m schichtplan analyse --konfig-vorschlag /tmp/vorschlag
```

Die Vorschlaege dann von Hand nach `konfig/` uebernehmen - sonst gehen
handgepflegte Werte verloren.

## Wie gut trifft es?

```bash
python -m schichtplan backtest
```

Rekonstruiert fuer jede historische Woche die damaligen Randbedingungen,
plant neu und vergleicht mit dem, was tatsaechlich geschrieben wurde.

Stand heute: **75 % Anwesenheit** (Arbeit/Frei richtig) und **49 % exakt
dieselbe Schicht**. Vorher, nur mit den aus den Fotos abgeleiteten Mustern,
waren es 65 % / 42 % - die nachgereichten Wochenmodelle und Teamregeln haben
also messbar etwas gebracht.

Der Rest sind Regeln, die noch nirgends stehen: Qualifikationen (wer kann
Theke, wer Produktion), Umsatzspitzen, Absprachen. Genau dafuer ist der
Backtest da: Regel in `konfig/` ergaenzen, Backtest laufen lassen, Quote
muss steigen.

Die Spalten `Punkte Orig.` / `Punkte neu` zeigen dieselben Plaene nach den
eigenen Regeln bewertet. Liegt `Punkte neu` weit darunter, optimiert die
Konfiguration etwas anderes als der Mensch - dann sind die Gewichte schuld,
nicht der Planer.

## Neue Altplaene aufnehmen

Eine JSON-Datei je Woche in `daten/historie/`, Aufbau siehe
`daten/schema.md`. Danach `analyse`, `backtest` und die Samstags-Fairness
rechnen automatisch damit.

## Regeln, die der Planer kennt

Harte Vorgaben (werden nie verletzt, weil der Solver sie gar nicht anfasst):
Urlaub/Schule/Krank, `fest`, feste freie Tage, geschlossene Tage,
erlaubte Schichten je Mitarbeiter, an welchen Wochentagen eine Schicht zulaessig ist.

Gewichtete Ziele (`konfig/regeln.yaml`) - die Gewichte oben in der Liste sind so
hoch, dass sie praktisch hart sind:

| Regel | was sie will |
|---|---|
| `gruppenbesetzung` | in jeder Fruehschicht einer von Kurka / Rohwer / Marino |
| `unvertraeglich` | Kohl und Reich nie zusammen in der Spaetschicht |
| `termin` | Teamleitersitzung o. Ae. ist abgedeckt |
| `ruhezeit_verletzung` | nie unter 10 h Ruhe |
| `kopfzahl` | Zielkopfzahl je Tag; ein Kopf zu viel ist frei, zu wenig nicht |
| `besetzung_unter` / `_ueber` | Mindestbesetzungskurve ueber den Tag |
| `frueh_besetzung` / `schluss_besetzung` | genug Leute zum Aufbau und bis Ladenschluss |
| `gesamtstunden` | 255 h je Woche, ohne Azubi, gekuerzt um Ausfaelle |
| `wechsel_ueber_limit` | hoechstens 1 kurzer Wechsel (20 Uhr -> 6 Uhr) je MA und Woche |
| `wochenstunden` / `arbeitstage` | individuelles Wochenmodell |
| `wunsch_frei` / `wunsch_schicht` | Wuensche der Woche |
| `freie_tage_zusammenhaengend` | Kohls freie Tage aneinander |
| `stammschicht` | jeder bekommt moeglichst seine gewohnte Schicht |
| `sparsam_einsetzen` | U. Kurz nur einsetzen, wenn es die Besetzung braucht |
| `zersplitterung` | nicht jeden Tag eine andere Schichtart |
| `samstag_fairness` | freier Samstag im Turnus (standardmaessig aus) |

### Stundenbudget

`wochenstunden_gesamt: 255` in `konfig/bedarf.yaml` ist das Budget fuer die
Umsatzziele je Verkaeuferstunde. Azubistunden zaehlen nicht mit
(`zaehlt_stundenbudget: false`). Faellt jemand aus, sinkt das Budget
automatisch um dessen Sollstunden - bei einer Woche Urlaub von Marino also
auf 215 h. Der Ist-Wert steht unter jedem Plan, im Ausdruck grün oder rot.

## e2n

Kurzfassung: e2n hat eine REST-API mit selbst freischaltbarem API-Key
(Benutzer > Verwaltung > Schnittstellen > REST API). Ob darueber *Schichten
geschrieben* werden koennen, ist oeffentlich nicht dokumentiert - Details und
naechste Schritte in [`docs/e2n.md`](docs/e2n.md). Bis das geklaert ist, liefert
das Projekt CSV-Dateien im ueblichen Importformat.

## Tests

```bash
python -m unittest discover -s tests
```
