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
| C. Rohwer | f w o | 40 | 5 | Mi | - | Mo-Do frueh, Fr/Sa im Wechsel frueh/spaet; **ein freier Fr oder Sa ist erlaubt**, auch wenn sie dafuer unter fuenf Tage faellt |
| A. Marino | f w o | 40 | 5 | Mo | - | |
| N. Sannzenbacher | f w | 30 | 4 | - | Mi, Do | nur 6-14 oder 12-20; Mo/Di und Fr/Sa jeweils dieselbe Schicht; **nie Spaet vor Frueh** (langer Heimweg) |
| S. Reich | w | 30 | 4 | Mo, Mi | - | Aenderung nur nach Absprache |
| I. Nachtrieb | f w | 24 | 3 (bis 5) | - | - | Monatsmittel, Wochentoleranz +/- 8 h |
| B. Kohl | w | 30 | 4 | - | - | rund 7,5 h netto am Tag: 6-13:30, 8-15:30, 12-20, Sa 10-18 |
| C. Kurz | f w o | 17 | 3 | Di | Fr, Sa | feste Struktur Mo 8-14 / Mi 8-13 / Do 8-14; unter der Woche nie vor 8, samstags geht 6-14 |
| U. Kurz | f w | bis 22 | bis 3 | Di | - | Reserve: fuellt genau die Luecke zwischen Plaetzen und Vertragstagen |
| A. Menzler | f w | 40* | 5* | - | Mo, Di | Azubi und Springer; Mo-Do zaehlt er wahlweise mit; **keine Fruehschicht unter drei Koepfen** |

\* Menzler rechnet anders: 5 Praesenztage, Schichten **und** Schultage
zusammen. Ein Schultag deckt 8 h des Wochensolls ab, also vier Schichten bei
einem Schultag, drei bei zweien, fuenf ohne. Dadurch ist er auch dann dabei,
wenn sonst niemand fehlt. Seine Stunden zaehlen nicht gegen das 255-h-Budget,
und als Springer bekommt er keine Strafe fuer wechselnde Schichtarten.
Spaetschichten sind moeglich, wenn die Besetzung es braucht - eine feste
Obergrenze gibt es nicht. Die Regel gegen Spaet-Frueh-Wechsel gilt fuer ihn
wie fuer alle anderen.

Gegen die Zielkopfzahl zaehlt er **wahlweise** (`zaehlt_kopfzahl: [fr, sa]`).
Montag bis Donnerstag kommt er normalerweise als zweite Mittelschicht auf das
Tagesgeruest obendrauf - da ist Zeit zum Lernen und Ueben. Ist an einem Tag
sonst niemand zu bekommen, macht er die Mittelschicht auch allein und fuellt
den Platz. Beides ist recht, deshalb ist die Kopfzahl an diesen Tagen eine
Spanne: ueberzaehlig macht er nie, eine Luecke darf er schliessen. Freitag und
Samstag zaehlt er fest mit - so sind die Zielkopfzahlen aus den Altplaenen
gemittelt (Schnitt mit Azubi 6,79 bzw. 6,38 bei Ziel 7). Eine Wochenvorgabe,
die `bedarf.kopfzahl` uebersteuert, meint immer die Koepfe **ohne** ihn.

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

## Die Strafpunkte lesen

Der Planer sucht nicht nach "richtig", sondern nach der Variante mit den
wenigsten Strafpunkten. Jede Regel hat ein Gewicht in `konfig/regeln.yaml`,
und jede Verletzung kostet Gewicht mal Ausmass - eine fehlende Fruehschicht
1200, zwei fehlende 2400.

**Die absolute Zahl sagt fast nichts.** Sie haengt an der Woche: viele
Abwesende, ein Feiertag, knappe Besetzung - dann sind 4000 Punkte ein guter
Plan. Zwei Zahlen sind aussagekraeftig:

* **Der Vergleich zum Greedy-Start** (`3869 (Greedy-Start: 19684)`) zeigt, wie
  viel die Suche herausgeholt hat. Bleibt der Abstand klein, lohnt
  `--iterationen` hochzudrehen.
* **Die Liste darunter.** Nur die erklaert, woher die Punkte kommen.

Die Suche kennt vier Zuege: eine Zelle aendern, zwei Leute am selben Tag
tauschen, bei einer Person zwei Tage tauschen, und einen Ringtausch ueber zwei
Tage (A arbeitet montags und hat mittwochs frei, B umgekehrt - beide tauschen).
Die letzten beiden sind noetig, seit die Zielkopfzahl eine Obergrenze ist: mit
Einzelzuegen allein kaeme der Planer nicht mehr aus einem lokalen Optimum
heraus, weil jeder Zwischenschritt einen Tag ueber- oder unterbesetzt.

Dort zaehlt die Kennzeichnung mehr als die Punktzahl:

| | Bedeutung |
|---|---|
| `FEHLER` | etwas stimmt nicht - Faehigkeit unbesetzt, Ruhezeit verletzt, Pflichttag leer. Das gehoert angeschaut, bevor der Plan aushaengt. |
| `Warnung` | ein Ziel wurde verfehlt, meist weil ein anderes wichtiger war. Lesen und entscheiden. |
| `Hinweis` | Beobachtung ohne Handlungsbedarf. |

Ein Befund mit **0 Punkten** ist eine Meldung, an der der Planer nichts aendern
kann - etwa eine Unterdeckung, weil zu viele Leute im Urlaub sind. Die kostet
bewusst nichts, sonst wuerde der Planer anderswo Unsinn bauen, um sie
loszuwerden.

Zum Vergleichen taugen die Punkte nur **innerhalb derselben Woche**: zwei
Laeufe mit `--seed 1` und `--seed 2` gegeneinander, oder vorher/nachher bei
einer Regelaenderung. Zwischen verschiedenen Wochen sind sie bedeutungslos.

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
| `kopfzahl` / `kopfzahl_ueber` | Zielkopfzahl je Tag - sie ist zugleich Untergrenze und Obergrenze |
| `besetzung_unter` / `_ueber` | Mindestbesetzungskurve ueber den Tag |
| `frueh_besetzung` / `schluss_besetzung` | genug Leute zum Aufbau und bis Ladenschluss |
| `gesamtstunden_ueber` | 255 h je Woche sind eine **Obergrenze**, ohne Azubi |
| `besetzung_ueber` | ueberzaehlige Anwesenheit - der Hebel fuer den Umsatz je Stunde |
| `kurzschicht` | Splitterschichten unter drei Vierteln des Arbeitstags |
| `wechsel_ueber_limit` | hoechstens 1 kurzer Wechsel (20 Uhr -> 6 Uhr) je MA und Woche |
| `wochenstunden` / `arbeitstage` | ueber dem individuellen Wochenmodell - Ueberstunden |
| `wochenstunden_unter` | darunter - der Vertrag ist der Boden, seit das Budget nur noch deckelt |
| `arbeitstage_unter` | ein Tag weniger als vereinbart; die Verteilung regeln die Konten |
| `wunsch_frei` / `wunsch_schicht` | Wuensche der Woche |
| `freie_tage_zusammenhaengend` | Kohls freie Tage aneinander |
| `frueh_spaet_ausgleich` | Frueh und Spaet gleichen sich ueber 4 Wochen aus |
| `spaet_anteil` | fester Zielanteil Spaetschichten statt 50/50 (Azubi: 25 %) |
| `frueh_ueber` | keine dritte Fruehschicht, wo zwei reichen |
| `vermiedene_schicht` | Kurka spaet nur im Notfall |
| `schichtwunsch` | Rohwer Mo-Do frueh |
| `wochenwechsel_uneinheitlich` | die Tage eines Blocks liegen nicht auf derselben Seite |
| `wochenwechsel_unvollstaendig` | geschlossener Block nur halb belegt (Sannzenbacher Mo/Di) |
| `wochenwechsel` | Rohwer Fr/Sa zweite Woche in Folge dieselbe Seite |
| `schichtwunsch` (Schicht) | C. Kurz Mo 8-14 / Mi 8-13 / Do 8-14 |
| `spaet_vor_frueh` | Sannzenbacher nie Spaetschicht vor einer Fruehschicht |
| `bevorzugter_freier_tag` | weiche freie Tage (Sannzenbacher Mi/Do, C. Kurz Fr/Sa) |
| `stammschicht` | jeder bekommt moeglichst seine gewohnte Schicht |
| `sparsam_einsetzen` | leichter Gegendruck gegen Reservestunden, ohne Meldung |
| `reserve_ueber_bedarf` | Reservetag mehr, als die Luecke hergibt - kostet jemandem mit Vertrag einen Tag |
| `zersplitterung` | nicht jeden Tag eine andere Schichtart |
| `samstag_konto` | Rueckstand bei freien Samstagen gegenueber dem Schnitt |
| `fehltage_konto` | Tage unter Soll gegenueber dem Teamschnitt, mal Einsatzprioritaet |
| `minusstunden_konto` | Stundenkonto gegenueber dem Teamschnitt, mal Einsatzprioritaet |
| `ueberhang` | Hinweis ohne Punkte: wer den zusaetzlichen freien Tag bekam und wer sonst dran waere |
| `stammdaten` | Hinweis ohne Punkte: Vertragsstunden, die die gewohnten Schichten nicht hergeben |

### Ueberbesetzung und Minusstunden

Die Zielkopfzahl je Tag ist eine Obergrenze, kein Richtwert: mehr Leute als
`bedarf.kopfzahl` stehen nicht im Laden. In einer Woche, in der niemand Urlaub
hat, gibt die Mannschaft aber mehr Personentage her, als der Laden braucht -
dann bekommt jemand einen zusaetzlichen freien Tag.

Wen es trifft, entscheiden zwei rollierende Konten ueber
`ausgleich_fenster_wochen` (4 Wochen). Beide messen nicht gegen das eigene
Soll, sondern gegen den Schnitt der Mannschaft:

* `fehltage_konto` - Arbeitstage unter Soll,
* `minusstunden_konto` - Stunden unter Soll, vorzeichenbehaftet, sodass eine
  Woche mit Ueberstunden eine Woche mit Minusstunden zurueckzahlt.

Wer schon mehr Rueckstand hat als die anderen, ist teuer - der naechste freie
Tag trifft also jemand anderen. Liegen alle gleich weit zurueck, kostet das
nichts: dass es ueberhaupt Minusstunden gibt, ist keine Entscheidung des
Planers, sondern Folge der Besetzung.

Deshalb ist das persoenliche Wochensoll nach unten nur noch leicht gewichtet
(`wochenstunden_unter`, `arbeitstage_unter`). Nach oben bleibt es teuer -
Ueberstunden muss jemand tatsaechlich leisten.

Der Plan gibt die Entscheidung als Hinweis `ueberhang` aus: wie viele
Personentage die Woche uebrig hat, wer die zusaetzlichen freien Tage bekommen
hat und mit welchem Stundenkonto, und wer nach Konto als naechstes dran waere.
Damit laesst sich die Entscheidung von Hand ueberstimmen - dann den Tag in der
Wochenvorgabe unter `fest` eintragen.

Fest sind dabei die **Arbeitstage** - die hat jeder mit dem Chef vereinbart.
Die Vertragsstunden sind nur Orientierung dafuer, ob jemand im Plus oder Minus
steht: Kohl arbeitet vier Tage zu rund 7,5 h, Reich und Nachtrieb duerfen in
der Stundenzahl schwanken. Deshalb wiegt `arbeitstage` schwer und
`wochenstunden` leicht.

Die Reserve (U. Kurz) fuellt genau die Luecke zwischen den Plaetzen im Laden
und den Vertragstagen der Mannschaft. Jeder Reservetag darueber hinaus kostet
jemandem mit Vertrag einen Tag und wird als `reserve_ueber_bedarf` gemeldet;
die Stunden darunter sind kein Befund, dafuer ist die Reserve da.

Ein Sonderfall bleibt: wessen Vertragsstunden die gewohnten Schichten gar nicht
hergeben, laeuft dauerhaft ins Minus, ohne dass der Planer etwas falsch macht.
Das meldet der Hinweis `stammdaten`; zu klaeren ist es in
`konfig/mitarbeiter.yaml`.

### Sollstunden, Brutto und Netto

Zwei Stundenbegriffe stehen im Plan nebeneinander, und sie meinen verschiedene
Dinge:

* **Die Summenspalte je Mitarbeiter ist netto** - Anwesenheit minus einer
  halben Stunde Pause je Schicht (`pause_minuten`, ArbZG 4). Das ist die
  bezahlte Arbeitszeit.
* **Die Kennzahl der Filiale ist brutto** - Anwesenheit ohne Pausenabzug, und
  der Azubi zaehlt mit. Genau so steht es auf dem Auswertungsblatt:
  "Arbeitszeit in Stunden / EUR-Wochenumsatz (brutto)", Soll 105 EUR je Stunde.

Die Sollstunden kommen deshalb aus dem Umsatz und nicht aus einer festen Zahl:

```yaml
umsatz_je_stunde: 105       # konfig/bedarf.yaml
umsatz_erwartet: 27000      # -> 257 Sollstunden brutto
```

27.000 EUR bei 105 EUR/Std. sind die 255 h vom Blatt. Jede Wochenvorgabe kann
`umsatz_erwartet` ueberschreiben - eine Vorweihnachtswoche traegt mehr Stunden
als eine im Februar. Ohne Umsatzangabe greift `wochenstunden_gesamt` als
Rueckfall.

Die 14 Altplaene liegen mit diesem Massstab im Schnitt bei 257,3 h brutto und
treffen das Soll damit fast genau - nach der frueheren Rechnung (netto, ohne
Azubi) waren es 216,9 h, und das Budget schien dauerhaft um 40 h unterschritten.

### Sparsam planen

Die Sollstunden sind eine **Obergrenze, kein Ziel**. Dieselbe Besetzung mit weniger
Stunden hebt den Umsatz je Verkaeuferstunde, also wird nach unten nichts
bestraft - nur gemeldet. Was die Stunden trotzdem oben haelt:

* die Mindestbesetzungskurve `besetzung_min` - das ist die eigentliche
  Untergrenze des Plans,
* `wochenstunden_unter`: der Vertrag jedes Einzelnen ist der Boden. Ohne ihn
  plant der Planer alle auf die Mindestbesetzung herunter. Wie hart der Boden
  je Person ist, steuert `stundenprioritaet`: Kurka, Marino, Sannzenbacher und
  der Azubi sollen ihre Stunden am ehesten erreichen (1,6), Rohwer darf eher
  darunter bleiben (0,5) - dafuer bekommt sie eher einen freien Samstag. Der
  Samstagsausgleich selbst bleibt davon unberuehrt und gilt fuer alle gleich,
* `kurzschicht`: keine Splitter. Die Untergrenze ist je Person drei Viertel
  ihres normalen Arbeitstags, mindestens `min_schicht_h` - fuer eine
  40-Stunden-Kraft also sechs Stunden, fuer C. Kurz gut vier.

Nach unten zieht `besetzung_ueber`: jede Halbstunde, in der mehr als eine
Person ueber der Kurve steht. Genau das schiebt eine Spaetschicht von 11 Uhr
auf 14 Uhr, wo sie um 11 nicht gebraucht wird. Wer feste Startzeiten hat
(Sannzenbacher und Kohl 12 Uhr, Marino und Rohwer 11 Uhr), hat 14-20 gar nicht
in `erlaubte_schichten` - verschoben werden koennen nur Menzler, Nachtrieb,
Reich und U. Kurz.

Wie viel das ausmacht, haengt an der Woche: in KW42 sind es rund 20 h gegenueber
der alten Rechnung, in der das Budget ein Ziel war und die Leute ueber ihre
Vertragsstunden hinaus eingeplant wurden.

### Aushilfe aus einer anderen Filiale

Wenn mehrere gleichzeitig Urlaub haben, reicht die eigene Mannschaft nicht.
Dann kommt jemand aus einer anderen Filiale dazu - nur fuer diese eine Woche,
deshalb steht sie in der Wochenvorgabe und nicht in den Stammdaten:

```yaml
aushilfe:
  - id: aushilfe_1
    name: "M. Weber (Schorndorf)"
    faehigkeiten: [f, w]        # f = Fleisch, w = Wurst, o = Ofen
    soll_stunden: 32
    soll_tage: 4
    tage: [do, fr, sa]          # weglassen = ganze Woche
```

Sie zaehlt gegen Kopfzahl, Besetzungskurve und Faehigkeiten, nimmt aber an
keinem der rollierenden Konten teil - naechste Woche ist sie wieder weg. Und
sie wird nur eingesetzt, soweit die eigene Mannschaft nicht reicht
(`nur_bei_bedarf`, voreingestellt).

**Damit laesst sich der Ersatzbedarf ausrechnen.** Man setzt sie offen an -
alle Tage, genug Stunden - und laesst planen. Was dann in ihrer Zeile steht,
ist genau die Liste, die in der anderen Filiale angefragt werden muss:

```yaml
aushilfe:
  - id: ersatz
    name: "Ersatz noetig"
    faehigkeiten: [f, w, o]
    soll_stunden: 48
    soll_tage: 6
```

In KW44 (Kurka, Kohl und Menzler gleichzeitig im Urlaub, zehn Personentage zu
wenig) faellt der Plan damit von 6645 auf 3780 Strafpunkte, und Freitag und
Samstag sind wieder voll besetzt.

### Mitten in der Woche umplanen

Faellt jemand am Mittwoch aus, sind Montag und Dienstag schon gearbeitet. Die
duerfen sich nicht mehr aendern:

```
python -m schichtplan plan wochen/2026-KW44.yaml \
       --ab mi --bestehend ausgabe/2026-KW44.json
```

Alles vor dem genannten Tag wird aus dem bestehenden Plan uebernommen und
festgesetzt, der Rest neu gerechnet. Den Ausfall vorher unter `krank`
eintragen - Urlaub und Krankheit gehen den uebernommenen Zellen vor.

### Konten auf einen Blick

```
python -m schichtplan konten --html ausgabe/konten.html
```

Frueh/Spaet, freie Samstage und das Stundenkonto in einer Tabelle, dazu der
Wochenverlauf je Mitarbeiter als Spur. Das beantwortet die Frage, die beim
Planen wirklich zaehlt: wer ist insgesamt dran?

### Pausen

Von jeder Schicht geht eine halbe Stunde Pause ab (`pause_minuten` in
`konfig/bedarf.yaml`). Die Summenspalte im Plan und das Budget sind deshalb
**Nettostunden** - die Zeit, die als Verkaeuferstunde zaehlt. Die Anwesenheit
steht daneben:

```
Stunden gesamt    249.5 h netto (Budget 255 h; 266.5 h Anwesenheit minus Pausen)
```

Die Sollstunden je Mitarbeiter in `konfig/mitarbeiter.yaml` sind dagegen
**Anwesenheitszeiten** - sie stammen aus den Papierplaenen, wo 6-14 als acht
Stunden steht. Wer 40 h auf fuenf Schichten hat, kommt damit auf 37.5 h netto.

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
