# Wocheneinsatzplan Winterbach - automatische Erzeugung

Erzeugt den Wochenplan aus Stammdaten + den Variablen, die sich jede Woche
aendern (Urlaub, Schule, Wunschfrei, Feiertage). Grundlage sind 14 digitalisierte
Altplaene aus KW28-KW41/2025.

Reines Python 3.11 + PyYAML, kein Solver-Paket, keine Datenbank.

## Schnellstart

```bash
pip install pyyaml

python -m schichtplan neu 2025-KW43        # Wochenvorgabe anlegen
$EDITOR wochen/2025-KW43.yaml              # Urlaub, Schule, Wuensche eintragen
python -m schichtplan plan wochen/2025-KW43.yaml
```

## Wochenablauf

```bash
python -m schichtplan ausgleich                          # wer haengt frueh/spaet schief?
python -m schichtplan neu 2025-KW43
$EDITOR wochen/2025-KW43.yaml
python -m schichtplan plan wochen/2025-KW43.yaml         # rechnen, pruefen, exportieren
# ... Plan aushaengen, ggf. von Hand nachbessern ...
python -m schichtplan uebernehmen ausgabe/2025-KW43.json # in die Historie legen
```

Der letzte Schritt ist der wichtige: **nur uebernommene Plaene zaehlen fuer den
Frueh/Spaet-Ausgleich und die Samstags-Fairness.** Ohne ihn plant jede Woche
blind von vorn. Wurde der Plan nach dem Aushang noch von Hand geaendert, erst
die JSON in `ausgabe/` anpassen, dann uebernehmen - sonst stimmt die Bilanz nicht.

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

Termine, fuer die jemand frueher Schluss machen muss, kommen in dieselbe Datei.
Die Teamleitersitzung ist unregelmaessig - in Wochen ohne Sitzung laesst man den
Block einfach weg. `abwechselnd: true` heisst: nicht dieselbe Person wie beim
letzten Mal, egal wie lange das her ist. Wer zuletzt dran war, erkennt der
Planer am Schichtende in der Historie, er braucht dafuer keinen festen Turnus:

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

## Feiertage

Der Feiertagskalender fuer Baden-Wuerttemberg wird gerechnet, nicht gepflegt -
Ostersonntag nach der Gaussschen Osterformel, alles Bewegliche haengt daran.
`python -m schichtplan neu 2025-KW40` traegt die Feiertage der Woche gleich
unter `geschlossen` ein.

```bash
python -m schichtplan feiertage 2026
```

Rund um Feiertage verschiebt sich das Geschaeft, geregelt in
`konfig/bedarf.yaml` unter `feiertagsregeln`:

* **vor** einem Feiertag vier Personen bis Ladenschluss
* **nach** einem Feiertag drei Personen ab 6 Uhr

Welcher Tag betroffen ist, rechnet der Planer aus dem Kalender. Der Samstag vor
einem Feiertagsmontag zaehlt als Vortag, weil sonntags ohnehin zu ist. Die Werte
heben die normalen Mindestwerte an, senken sie nie.

Ein geschlossener Tag mitten in der Woche verkuerzt keine Abstaende: zwischen
einer Spaetschicht am Donnerstag und einer Fruehschicht am Samstag liegen bei
einem Feiertagsfreitag 34 Stunden, nicht 10. Genauso unterbricht er die Zaehlung
der Arbeitstage am Stueck und trennt zwei freie Tage nicht voneinander.

### Weihnachten und andere Sonderwochen

Weihnachts- und Silvesterwochen werden erkannt. Sie werden **von Hand geplant** -
der Planer rechnet dort nicht, er prueft nur und exportiert:

```bash
python -m schichtplan neu 2025-KW52 --manuell
```

Das legt `modus: manuell` an und schreibt gleich das ganze Raster mit allen
Mitarbeitern und Tagen in die Datei:

```yaml
fest:
  kurka_j:            # J. Kurka
    mo: 6-14
    di: 6-14
    mi: 5-14          # beliebige Zeiten, nicht nur Katalogschichten
    sa: 6-14
```

`python -m schichtplan plan wochen/2025-KW52.yaml` uebernimmt das unveraendert,
laesst aber alle Pruefungen darueber laufen und schreibt Druckplan und
e2n-CSVs wie sonst auch. Du bekommst also Handarbeit bei der Verteilung und
trotzdem die Kontrolle auf Faehigkeiten, Ruhezeiten und Besetzung.

Zwei Dinge helfen dabei:

**Bedarf je Woche uebersteuern** - am Heiligabend ist frueher Schluss und mehr
Betrieb:

```yaml
bedarf:
  oeffnung:
    mi: {von: "05:00", bis: "14:00"}
  kopfzahl: {mo: 8, di: 10, mi: 10, sa: 8}
  frueh_min: {mi: 6}
```

**Regeln abschalten**, die in der Woche keinen Sinn ergeben:

```yaml
regeln_aus: [gesamtstunden, wochenstunden, arbeitstage, frueh_spaet_ausgleich]
```

Beides geht auch in normalen Wochen, etwa fuer einen Aktionstag.

## Die Wochenmodelle

| | kann | Stunden | Tage | fest frei | bevorzugt frei | Besonderheit |
|---|---|---|---|---|---|---|
| J. Kurka | f w o | 40 | 5 | - | - | Frueh-Anker, Spaet nur im Notfall; freier Tag variabel |
| C. Rohwer | f w o | 40 | 5 | Mi | - | Mo-Do frueh, Fr/Sa im Wechsel frueh/spaet |
| A. Marino | f w o | 40 | 5 | Mo | - | |
| N. Sannzenbacher | f w | 30 | 4 | - | Mi, Do | freie Tage duerfen wandern, aber zusammen |
| S. Reich | w | 30 | 4 | Mo, Mi | - | Aenderung nur nach Absprache |
| I. Nachtrieb | f w | 24 | 3 (bis 5) | - | - | Monatsmittel, Wochentoleranz +/- 8 h |
| B. Kohl | w | 30 | 4 | - | - | zwei freie Tage, moeglichst zusammenhaengend |
| C. Kurz | f w o | 20 | 3 | Di | Fr, Sa | Muster Mo 8-14 / Mi 8-13 / Do 8-14 |
| U. Kurz | f w | Reserve | - | Di | - | so wenig wie moeglich, breit einsetzbar |
| A. Menzler | f w | 40* | 5* | - | - | Azubi und Springer, hoechstens 1 Spaetschicht |

\* Menzler rechnet anders: 5 Praesenztage, Schichten **und** Schultage
zusammen. Ein Schultag deckt 8 h des Wochensolls ab, also vier Schichten bei
einem Schultag, drei bei zweien, fuenf ohne. Dadurch ist er auch dann dabei,
wenn sonst niemand fehlt. Seine Stunden zaehlen nicht gegen das 255-h-Budget,
und als Springer bekommt er keine Strafe fuer wechselnde Schichtarten.

**fest frei** gilt immer. **bevorzugt frei** soll frei bleiben, darf aber
weichen, wenn die Besetzung es verlangt - der Plan weist es dann als Hinweis aus.

**Aenderung nur nach Absprache** heisst technisch: der Tag steht in
`feste_freie_tage` und wird nur ueberschrieben, wenn er in der Wochenvorgabe
unter `fest` auftaucht - dann hat die Wochenvorgabe Vorrang.

## Faehigkeiten

`f` Fleisch, `w` Wurst, `o` Ofen - je Mitarbeiter in `konfig/mitarbeiter.yaml`,
die Abdeckungsregeln in `konfig/team.yaml`:

* **f und w muessen durchgehend besetzt sein**, jede Halbstunde der Oeffnungszeit.
* **o muss morgens da sein**, mindestens eine Fruehschicht mit Ofen.

Dass Kohl und Reich nicht zusammen in der Spaetschicht stehen duerfen, folgt
daraus von selbst: beide koennen nur `w`, also fehlt Fleisch, sobald nur die
zwei da sind. Eine eigene Paarregel waere strenger als noetig - sie wuerde die
beiden auch trennen, wenn jemand mit `f` danebensteht. Sie liegt deshalb nur
als auskommentierte Vorlage in `team.yaml`.

## Frueh/Spaet-Ausgleich

```bash
python -m schichtplan ausgleich
```

```
Mitarbeiter        Frueh Spaet Mittel  Differenz  Verteilung
J. Kurka              18     1      0        +17  FFFFFFFFFFFFFFFFFFS  (ausgenommen)
S. Reich               6     3      1         +3  FFFFFFSSS  <-- schief
I. Nachtrieb           3     7      5         -4  FFFSSSSSSS  <-- schief
```

Rollierendes Fenster von 4 Wochen (`ausgleich_fenster_wochen`), Toleranz
2 Schichten. Wer darueber hinaus schief liegt, bekommt in der naechsten Woche
Gegendruck. Ausgenommen sind Kurka (Frueh-Anker), Rohwer (Mo-Do frueh ist
gesetzt, sein Ausgleich laeuft nur ueber Fr/Sa) und U. Kurz (Reserve).

**Das funktioniert nur mit gepflegter Historie** - siehe `uebernehmen` oben.

## Konfiguration

| Datei | Inhalt |
|---|---|
| `konfig/mitarbeiter.yaml` | Sollstunden, Solltage, feste freie Tage, erlaubte und gewohnte Schichten |
| `konfig/schichten.yaml` | Schichtkatalog (`6-14`, `11-20`, ...) inkl. an welchen Tagen erlaubt |
| `konfig/bedarf.yaml` | Kopfzahl, Frueh-/Schlussbesetzung, Mindestbesetzungskurve, Wochenstundenbudget |
| `konfig/team.yaml` | Faehigkeiten, deren Abdeckung, Gruppen- und Unvertraeglichkeitsregeln |
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

Stand heute: **76 % Anwesenheit** (Arbeit/Frei richtig) und **48 % exakt
dieselbe Schicht**. Zum Vergleich:

| Stand | Anwesenheit | Schicht |
|---|---|---|
| nur Muster aus den Fotos | 65 % | 42 % |
| + Wochenmodelle, Teamregeln, Termine | 75 % | 49 % |
| + Faehigkeiten, Frueh/Spaet-Ausgleich | 76 % | 48 % |
| + Feiertagsregeln, Azubimodell | 74 % | 44 % |

Die beiden letzten Zeilen zeigen, worauf man beim Messen achten muss: die Quote
faellt, obwohl die Regeln besser geworden sind. Das ist kein Rueckschritt,
sondern der Punkt, an dem der Planer bewusst anders plant als frueher von Hand:
Frueh und Spaet werden ausgeglichen, Menzler hat jetzt fest fuenf Praesenztage,
vor Feiertagen stehen vier Leute bis zum Schluss. Der Backtest misst gegen die
alte Praxis - wo die absichtlich verlassen wird, ist die Quote das falsche Mass.

Nuetzlich bleibt er trotzdem: faellt die Quote **ohne** dass eine Regel bewusst
geaendert wurde, stimmt etwas nicht.

Was noch fehlt: Umsatzspitzen, einzelne Absprachen. Regel in `konfig/`
ergaenzen, Backtest laufen lassen, Quote pruefen.

Die Spalten `Punkte Orig.` / `Punkte neu` zeigen dieselben Plaene nach den
eigenen Regeln bewertet. Liegt `Punkte neu` weit darunter, optimiert die
Konfiguration etwas anderes als der Mensch - dann sind die Gewichte schuld,
nicht der Planer.

## Laufzeit

Eine Woche rechnen dauert mit den Standardwerten (40 000 Iterationen,
4 Neustarts) rund 8 Sekunden, mit `--iterationen 80000` etwa 16. Mehr
Iterationen lohnen, wenn Hinweise stehen bleiben, die sich aufloesen lassen
sollten. `--seed` macht den Lauf reproduzierbar; ein anderer Seed liefert eine
andere gleichwertige Loesung - ganz brauchbar, wenn einem ein Plan nicht
gefaellt.

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
| `faehigkeit` | f und w durchgehend besetzt, o in der Fruehschicht |
| `zu_viel_spaet` | Azubi hoechstens eine Spaetschicht pro Woche |
| `gruppenbesetzung` | in jeder Fruehschicht einer von Kurka / Rohwer / Marino |
| `unvertraeglich` | Paare, die nicht zusammenarbeiten duerfen (derzeit keins aktiv) |
| `termin` | Teamleitersitzung o. Ae. ist abgedeckt |
| `termin_wechsel` | Sitzung nicht zweimal hintereinander dieselbe Person |
| `ruhezeit_verletzung` | nie unter 10 h Ruhe |
| `kopfzahl` | Zielkopfzahl je Tag; ein Kopf zu viel ist frei, zu wenig nicht |
| `besetzung_unter` / `_ueber` | Mindestbesetzungskurve ueber den Tag |
| `frueh_besetzung` / `schluss_besetzung` | genug Leute zum Aufbau und bis Ladenschluss |
| `gesamtstunden` | 255 h je Woche, ohne Azubi, gekuerzt um Ausfaelle |
| `wechsel_ueber_limit` | hoechstens 1 kurzer Wechsel (20 Uhr -> 6 Uhr) je MA und Woche |
| `wochenstunden` / `arbeitstage` | individuelles Wochenmodell |
| `wunsch_frei` / `wunsch_schicht` | Wuensche der Woche |
| `freie_tage_zusammenhaengend` | Kohls freie Tage aneinander |
| `frueh_spaet_ausgleich` | Frueh und Spaet gleichen sich ueber 4 Wochen aus |
| `vermiedene_schicht` | Kurka spaet nur im Notfall |
| `schichtwunsch` | Rohwer Mo-Do frueh |
| `schicht_verteilung` | Rohwer Fr/Sa im Wechsel frueh/spaet |
| `bevorzugter_freier_tag` | weiche freie Tage (Sannzenbacher Mi/Do, C. Kurz Fr/Sa) |
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
