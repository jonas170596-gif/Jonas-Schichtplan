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

**Feste freie Tage** stehen dagegen in `konfig/mitarbeiter.yaml`
(`feste_freie_tage`) und gelten in jeder Woche, ohne dass man sie neu eintraegt.
Nicht jeder hat welche - das Feld darf leer bleiben. Aktuell gesetzt ist nur
C. Kurz (Di/Fr/Sa), weil das Muster in 12 Altplaenen stabil ist.

## Konfiguration

| Datei | Inhalt |
|---|---|
| `konfig/mitarbeiter.yaml` | Sollstunden, Solltage, feste freie Tage, erlaubte und gewohnte Schichten |
| `konfig/schichten.yaml` | Schichtkatalog (`6-14`, `11-20`, ...) inkl. an welchen Tagen erlaubt |
| `konfig/bedarf.yaml` | Kopfzahl, Frueh-/Schlussbesetzung und Mindestbesetzungskurve je Tag |
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

Stand heute: **65 % Anwesenheit** (Arbeit/Frei richtig) und **42 % exakt
dieselbe Schicht**. Der Rest sind Regeln, die noch nirgends stehen -
Qualifikationen (wer kann Theke, wer Produktion), persoenliche Absprachen,
Umsatzspitzen. Genau dafuer ist der Backtest da: Regel in `konfig/` ergaenzen,
Backtest laufen lassen, Quote muss steigen.

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

Gewichtete Ziele (`konfig/regeln.yaml`):
Kopfzahl je Tag, Mindestbesetzung je Zeitfenster, Frueh- und Schlussbesetzung,
Wochenstunden, Arbeitstage, max. Tage am Stueck, Ruhezeit (11 h Ziel, 10 h
Untergrenze), Wunschfrei, Wunschschicht, Gewohnheitsschichten,
Zersplitterung, Samstags-Fairness (standardmaessig aus).

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
