# Wocheneinsatzplan Winterbach - automatische Erzeugung

Erzeugt den Wochenplan aus Stammdaten + den Variablen, die sich jede Woche
aendern (Urlaub, Schule, Wunschfrei, Feiertage). Grundlage sind 14 digitalisierte
Altplaene aus KW28-KW41/2026.

Reines Python 3.11 + PyYAML, kein Solver-Paket, keine Datenbank.

## Schnellstart

```bash
pip install pyyaml

python -m schichtplan neu 2026-KW43        # Wochenvorgabe anlegen
$EDITOR wochen/2026-KW43.yaml              # Urlaub, Schule, Wuensche eintragen
python -m schichtplan plan wochen/2026-KW43.yaml
```

## Wochenablauf

```bash
python -m schichtplan ausgleich                          # wer haengt frueh/spaet schief?
python -m schichtplan neu 2026-KW43
$EDITOR wochen/2026-KW43.yaml
python -m schichtplan plan wochen/2026-KW43.yaml         # rechnen, pruefen, exportieren
# ... Plan aushaengen, ggf. von Hand nachbessern ...
python -m schichtplan uebernehmen ausgabe/2026-KW43.json # in die Historie legen
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
woche: 2026-KW43
datum_von: 2026-10-19
datum_bis: 2026-10-24

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
Block einfach weg. Zugelassen ist derzeit nur Kurka. Gaebe es mehrere
Kandidaten, sorgt `abwechselnd: true` dafuer, dass nicht zweimal dieselbe
Person drankommt; wer zuletzt dran war, erkennt der Planer am Schichtende in
der Historie, ohne festen Turnus:

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
`python -m schichtplan neu 2026-KW40` traegt die Feiertage der Woche gleich
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
python -m schichtplan neu 2026-KW52 --manuell
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

`python -m schichtplan plan wochen/2026-KW52.yaml` uebernimmt das unveraendert,
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
| J. Kurka | f w o | 40 | 5 | - | - | Frueh-Anker, **montags gesetzt**; Spaet nur im Notfall; freier Tag variabel (Di-Sa) |
| C. Rohwer | f w o | 40 | 5 | Mi | - | Mo-Do frueh, Fr/Sa im Wechsel frueh/spaet |
| A. Marino | f w o | 40 | 5 | Mo | - | |
| N. Sannzenbacher | f w | 30 | 4 | - | Mi, Do | freie Tage duerfen wandern, aber zusammen |
| S. Reich | w | 30 | 4 | Mo, Mi | - | Aenderung nur nach Absprache |
| I. Nachtrieb | f w | 24 | 3 (bis 5) | - | - | Monatsmittel, Wochentoleranz +/- 8 h |
| B. Kohl | w | 30 | 4 | - | - | zwei freie Tage, moeglichst zusammenhaengend |
| C. Kurz | f w o | 20 | 3 | Di | Fr, Sa | Muster Mo 8-14 / Mi 8-13 / Do 8-14 |
| U. Kurz | f w | bis 22 | bis 3 | Di | - | Reserve: Soll ist Obergrenze, drei Tage sind in Ordnung |
| A. Menzler | f w | 40* | 5* | - | - | Azubi und Springer, rund ein Viertel der Schichten spaet |

\* Menzler rechnet anders: 5 Praesenztage, Schichten **und** Schultage
zusammen. Ein Schultag deckt 8 h des Wochensolls ab, also vier Schichten bei
einem Schultag, drei bei zweien, fuenf ohne. Dadurch ist er auch dann dabei,
wenn sonst niemand fehlt. Seine Stunden zaehlen nicht gegen das 255-h-Budget,
und als Springer bekommt er keine Strafe fuer wechselnde Schichtarten.
Spaetschichten sind moeglich, wenn die Besetzung es braucht - eine feste
Obergrenze gibt es nicht. Die Regel gegen Spaet-Frueh-Wechsel gilt fuer ihn
wie fuer alle anderen.

Zwei Stellschrauben fuer Soll-Werte:

* `nur_obergrenze: true` macht `soll_stunden`/`soll_tage` zur Obergrenze -
  weniger ist straffrei, mehr kostet. So ist bei U. Kurz "so wenig wie
  moeglich" abgebildet, ohne dass drei Tage ein Verstoss waeren.
* `spaet_anteil: 0.25` gibt statt des 50/50-Ausgleichs einen festen Zielanteil
  Spaetschichten vor, gemessen ueber dasselbe rollierende Fenster.

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
* **Kurka steht montags in der Fruehschicht** - dieselbe Mechanik, Gruppe mit
  einer Person und `tage: [mo]`.

Eine Gruppenregel senkt ihren Anspruch automatisch, wenn die Beteiligten an dem
Tag im Urlaub, krank oder in der Schule sind. Sonst stuende bei jedem Urlaub
eine unerfuellbare Forderung im Plan, gegen die der Solver alles andere
abwaegt.

Dass Kohl und Reich nicht zusammen in der Spaetschicht stehen duerfen, folgt
daraus von selbst: beide koennen nur `w`, also fehlt Fleisch, sobald nur die
zwei da sind. Eine eigene Paarregel waere strenger als noetig - sie wuerde die
beiden auch trennen, wenn jemand mit `f` danebensteht. Sie liegt deshalb nur
als auskommentierte Vorlage in `team.yaml`.

## Urlaubs- und Wunschkalender

`daten/kalender.yaml` haelt, was am Wandkalender haengt. `neu` traegt daraus
Urlaub, freie Tage und Schichtwuensche in die Wochendatei ein - zusammen mit
den Berufsschultagen muss man dann meist gar nichts mehr von Hand eintippen.

Die Eintraege nennen den **Vornamen**, genau wie der Wandkalender. Aufgeloest
wird ueber das Feld `vorname` in `konfig/mitarbeiter.yaml`, damit die Zuordnung
an genau einer Stelle steht. Ein Vorname, den es dort nicht gibt, laesst den
Kalender gar nicht erst laden.

Das ist kein Schoenheitsdetail: Anna ist Marino und Alex ist Menzler, beide
also "A." - beim ersten Abtippen hatte ich die zwei vertauscht. Ueber
Kuerzel faellt so etwas niemandem auf, ueber Vornamen kann es nicht mehr
passieren.

| `art` | Wirkung |
|---|---|
| `urlaub` | harte Abwesenheit |
| `frei` | fest zugesagter freier Tag. Was am Wandkalender steht, ist mit der Person besprochen und sie plant damit - er wird nie ueberplant |
| `wunsch_frei` | weicher freier Tag, kann der Besetzung weichen. Kommt im Wandkalender bisher nicht vor |
| `wunsch_frueh` | "Vorname frueh", das heisst konkret die Schicht 6-14 |
| `frei_oder_frueh` | "frueh/frei" bzw. "morgens oder frei": bevorzugt frei, und wenn die Besetzung es doch verlangt, dann nur die Fruehschicht |
| `arbeitet` | hebt einen festen freien Tag auf ("Carina arbeiten" dienstags) |

Ein zugesagtes `frei` senkt auch das Wochensoll: wer sechs offene Tage hat und
einen davon frei bekommt, kann seine fuenf Solltage noch erfuellen - wer
zusaetzlich Urlaub hat, nicht mehr, und dann ist das kein Fehltag.

Zwei Listen daneben:

* `storniert` haelt durchgestrichene Eintraege samt Grund fest - so bleibt
  nachvollziehbar, dass sie gelesen und verworfen wurden.
* `zu_klaeren` sammelt alles, was auf dem Foto nicht eindeutig war. Diese
  Eintraege werden **nicht** angewendet; `neu` gibt sie als Frage aus. Die
  Liste ist derzeit leer, alle sieben Unklarheiten sind besprochen.

### "frueh oder frei"

Das Muster kommt viermal vor und ist mehr als ein Wunsch: gemeint ist
*entweder frei oder die Fruehschicht, nichts dazwischen*. Technisch sind das
zwei Dinge in der Wochenvorgabe - ein `wunsch_frei` fuer den Tag und ein
`nur_schichten`-Eintrag, der die Auswahl auf `6-14` einengt:

```yaml
wunsch_frei: {kurz_u: [sa]}
nur_schichten: {kurz_u: {sa: [6-14]}}
```

Reicht die Besetzung, bekommt die Person den Tag frei. Reicht sie nicht, steht
sie in der Fruehschicht - aber der Planer kann sie nicht ersatzweise in eine
Spaetschicht stecken.

## Konten: freie Samstage und Fehltage

Beides sind Fairnessfragen, die sich nicht in einer Woche entscheiden. Der
Planer fuehrt sie deshalb als Konto ueber mehrere Wochen.

### Freie Samstage

```bash
python -m schichtplan samstage
```

```
Mitarbeiter        moeglich  frei  Schnitt   Konto  Verlauf
C. Rohwer                12     0      2.2    -2.2  uAAAAAAAAAAA.A  <-- vertraglich zwingend
I. Nachtrieb             12     1      2.2    -1.2  AAAuAAAAAA_A.A  <-- Rueckstand
J. Kurka                 13     5      2.3    +2.7  A___A_A_AAAA.A
```

'Schnitt' ist die Quote freier Samstage ueber alle Teilnehmer, auf die eigenen
moeglichen Samstage gerechnet. Wer darunter liegt, bekommt Vorrang. Wer
Samstag ohnehin fest oder bevorzugt frei hat (C. Kurz), zaehlt nicht mit -
sonst verzerrt er den Schnitt.

**Drei Leute koennen rechnerisch nie samstags frei haben:** Rohwer, Marino und
Reich. Ihre festen freien Tage plus Solltage fuellen die offene Woche exakt aus
- Rohwer hat Mi frei und soll fuenf Tage arbeiten, also bleiben genau Mo, Di,
Do, Fr, Sa. Der Planer bestraft sie dafuer nicht, sonst zahlte er eine Steuer,
die er nie vermeiden kann. Wer ihnen einen freien Samstag geben will, muss den
festen freien Tag wandern lassen oder eine kuerzere Woche in Kauf nehmen.

### Fehltage

Wer unter seinem Soll bleibt, sammelt das im Ausgleichsfenster auf. Ueber
`einsatzprioritaet` laesst sich steuern, wen es bevorzugt treffen soll: Marino
steht auf 1.6, Rohwer auf 1.0 - derselbe Rueckstand wiegt bei Marino also
schwerer, ein zusaetzlicher freier Tag geht eher an Rohwer.

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

## Kalender und Altplaene

Die Altplaene sind aus **2026** - die Formulare tragen im Fuss zwar
"Stand: 09/25", das ist aber der Revisionsstand des Vordrucks, nicht das
Planjahr. Alle 14 Datumsangaben passen exakt auf die Kalenderwochen 2026 und
auf keine einzige aus 2025.

Das ist kein Schoenheitsfehler, `datum_von` steuert die Feiertagsrechnung:
der 03.10. ist 2026 ein Samstag und 2025 ein Freitag. Damit so etwas auffaellt
statt durchzurutschen, gibt es zwei Pruefungen.

* Eine Wochenvorgabe, deren `datum_von` nicht der Montag der genannten
  Kalenderwoche ist, wird abgelehnt.
* `analyse` und `plan` gleichen die als Feiertag markierten Spalten der
  Historie gegen den Kalender ab und melden Abweichungen.

Beide sind gruen: die einzige Feiertagsspalte in der Historie ist der Samstag
in KW40, und genau dort liegt der Tag der Deutschen Einheit 2026.

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
| `gruppenbesetzung` | in jeder Fruehschicht einer von Kurka / Rohwer / Marino |
| `unvertraeglich` | Paare, die nicht zusammenarbeiten duerfen (derzeit keins aktiv) |
| `termin` | Teamleitersitzung o. Ae. ist abgedeckt |
| `termin_wechsel` | Sitzung nicht zweimal hintereinander dieselbe Person |
| `ruhezeit_verletzung` | nie unter 10 h Ruhe |
| `max_stunden` | nie ueber 48 h in einer Woche (ArbZG §3) |
| `kopfzahl` | Zielkopfzahl je Tag; ein Kopf zu viel ist frei, zu wenig nicht |
| `besetzung_unter` / `_ueber` | Mindestbesetzungskurve ueber den Tag |
| `frueh_besetzung` / `schluss_besetzung` | genug Leute zum Aufbau und bis Ladenschluss |
| `gesamtstunden` | 255 h je Woche, ohne Azubi, gekuerzt um Ausfaelle |
| `wechsel_ueber_limit` | hoechstens 1 kurzer Wechsel (20 Uhr -> 6 Uhr) je MA und Woche |
| `wochenstunden` / `arbeitstage` | individuelles Wochenmodell |
| `wunsch_frei` / `wunsch_schicht` | Wuensche der Woche |
| `freie_tage_zusammenhaengend` | Kohls freie Tage aneinander |
| `frueh_spaet_ausgleich` | Frueh und Spaet gleichen sich ueber 4 Wochen aus |
| `spaet_anteil` | fester Zielanteil Spaetschichten statt 50/50 (Azubi: 25 %) |
| `frueh_ueber` | keine dritte Fruehschicht, wo zwei reichen |
| `vermiedene_schicht` | Kurka spaet nur im Notfall |
| `schichtwunsch` | Rohwer Mo-Do frueh |
| `schicht_verteilung` | Rohwer Fr/Sa im Wechsel frueh/spaet |
| `bevorzugter_freier_tag` | weiche freie Tage (Sannzenbacher Mi/Do, C. Kurz Fr/Sa) |
| `stammschicht` | jeder bekommt moeglichst seine gewohnte Schicht |
| `sparsam_einsetzen` | U. Kurz nur einsetzen, wenn es die Besetzung braucht |
| `zersplitterung` | nicht jeden Tag eine andere Schichtart |
| `samstag_konto` | Rueckstand bei freien Samstagen gegenueber dem Schnitt |
| `fehltage_konto` | aufgelaufene Tage unter Soll, mal Einsatzprioritaet |

### Stundenbudget

`wochenstunden_gesamt: 255` in `konfig/bedarf.yaml` ist das Budget fuer die
Umsatzziele je Verkaeuferstunde. Azubistunden zaehlen nicht mit
(`zaehlt_stundenbudget: false`).

Das Budget haengt am Umsatz, nicht an der Anwesenheit - Urlaub senkt es nicht.
Was die anwesende Mannschaft hoechstens leisten kann, steht daneben, sobald es
knapp wird:

```
Stunden gesamt    205.0 h (Budget 255 h, mit der anwesenden Mannschaft moeglich 166 h)
```

Deshalb sind die beiden Richtungen unterschiedlich gewichtet. **Ueber** Budget
ist eine Planungsentscheidung und verschlechtert den Umsatz je
Verkaeuferstunde - das kostet. **Unter** Budget liegt meist an Abwesenheiten
und laesst sich nicht wegplanen; das wird gemeldet, aber nur leicht gewichtet,
sonst kaempft es gegen die Besetzungsregeln.

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
