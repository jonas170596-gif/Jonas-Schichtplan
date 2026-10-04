# Hinweise fuer Claude

Wochenplaner fuer die Metzgerei Thomas Kurz, Filiale Winterbach. Er erzeugt
den Wocheneinsatzplan aus Stammdaten plus dem, was sich jede Woche aendert,
und misst sich an 14 digitalisierten Altplaenen aus KW28-KW41/2026.

## Grundregeln

* **Nur Python 3.11 und PyYAML.** Kein Solver-Paket, keine Datenbank, kein
  Node, kein Flask. Die Weboberflaeche laeuft auf `http.server`, das Symbol
  wird mit `zlib` und `struct` gezeichnet. Wer eine Abhaengigkeit braucht,
  begruendet sie erst.
* **Deutsch, und zwar im Code.** Bezeichner, Dateinamen und Kommentare sind
  deutsch (`bewerte`, `erreichbare_stunden`, `wochenvorgabe`). Im Code und in
  Kommentaren ASCII - `ue` statt `ü`. Was der Nutzer auf dem Bildschirm
  liest, bekommt richtige Umlaute.
* **Kommentare sagen warum, nicht was.** Fast jede Regel hat einen Grund aus
  dem Laden: "um 18 Uhr ist zu, laenger geht nicht", "sie wohnt weit weg".
  Dieser Grund gehoert dazu, sonst dreht der naechste die Zahl wieder zurueck.

## Tests

```bash
python3 -m unittest discover -s tests -q      # 216 Tests, ~2 Minuten
```

Alles in `tests/test_schichtplan.py`. Zwei Dinge dabei beachten:

* Tests **bauen ihre Wochen selbst** ueber den Helfer `woche(...)`. Sie lesen
  keine Dateien aus `wochen/` - sonst bricht jede Planaenderung die Tests.
* Testausgabe **nie durch `grep` in einer `&&`-Kette** pruefen. grep gelingt
  auch bei Fehlschlaegen, die Kette laeuft weiter, und der Fehler landet im
  Commit. Das ist hier schon zweimal passiert.

## Was wo steht

| Datei | wofuer |
|---|---|
| `konfig/mitarbeiter.yaml` | Vertraege, erlaubte Schichten, Gewohnheiten, feste freie Tage |
| `konfig/regeln.yaml` | Gewichte aller Regeln - das Herz der Bewertung |
| `konfig/bedarf.yaml` | Kopfzahl, Besetzungskurve, Budget aus dem Umsatz |
| `konfig/schichten.yaml` | Schichtkatalog mit Kategorie je Schicht |
| `wochen/<KW>.yaml` | was sich woechentlich aendert: Urlaub, Schule, feste Vorgaben |
| `daten/historie/` | fertige Wochen - Grundlage fuer Konten und Fairness |
| `schichtplan/bewertung.py` | alle Regeln. Groesste Datei, hier passiert das Meiste |
| `schichtplan/generator.py` | Greedy-Start plus Abkuehlen mit fuenf Zugarten |

## Wenn du Gewichte aenderst

Ein Gewicht in `regeln.yaml` wirkt nie nur dort, wo man es erwartet. Nach
jeder Aenderung die vier Wochen durchrechnen und die Punkte vergleichen -
eine einzelne Woche sagt zu wenig:

```bash
for w in 2026-KW42 2026-KW43 2026-KW44 2026-KW45; do
  python3 -m schichtplan plan wochen/$w.yaml --historie daten/historie \
      --ausgabe ausgabe --iterationen 360000 --neustarts 12 --seed 11
  python3 -m schichtplan uebernehmen ausgabe/$w.json --historie daten/historie
done
```

Dabei rechnet jede Woche gegen die vorherige - deshalb das `uebernehmen`
dazwischen. Fuer Versuche mit einer **Kopie** der Historie arbeiten, nicht
mit `daten/historie` selbst.

`python -m schichtplan backtest` misst die Konfiguration zusaetzlich gegen
die 14 Altplaene. Liegt "Punkte neu" weit unter "Punkte Orig.", bewertet die
Konfiguration anders als der Mensch geplant hat - dann nachsehen, welche
Regel auf den Altplaenen anschlaegt, bevor man am Gewicht dreht.

Der Solver hat je Lauf ein paar Punkte Streuung. Unterschiede unter etwa 50
Punkten sind Rauschen, keine Verbesserung.

## Wochendateien

Sie sind voller Kommentare, die der Nutzer selbst liest. **Nie ueber ein neu
erzeugtes YAML schreiben** - das wirft sie weg. Die Oberflaeche aendert sie
zeilenweise im Text (`_fest_setzen`, `_tage_setzen`, `_notiz_setzen` in
`weboberflaeche.py`); fuer neue Felder genauso vorgehen.

Doppelte Schluessel sind ein echtes Risiko: YAML nimmt stillschweigend den
letzten. Der Lader meldet sie deshalb als Fehler - diese Pruefung nicht
entfernen, sie hat schon zwei stillschweigend verschwundene Vorgaben
gefunden.

## Weboberflaeche

`python -m schichtplan web`, dann <http://127.0.0.1:8777/>. Sie arbeitet
direkt auf `wochen/` und `ausgabe/`. Alles, was sie kann, geht auch von Hand
in der Datei - und umgekehrt bleibt jede Datei bearbeitbar, auch wenn die
Oberflaeche fuer ein neues Feld noch kein Formular hat. Deshalb liegt neben
jedem Formular der Rohtext.

Beim Aendern der Oberflaeche: das `hidden`-Attribut setzt `display:none` nur
ueber das Browser-Stylesheet, jede eigene `display`-Regel sticht es. Dafuer
gibt es `[hidden] { display:none !important }` in `stil.css` - stehen lassen.

## Offene Punkte

* **e2n**: siehe `docs/e2n.md`. Die REST-API schaltet der Mandant unter
  *Benutzer > Verwaltung > Schnittstellen > REST API* frei; was sie kann, ist
  oeffentlich nicht dokumentiert. Liegt eine Importvorlage vor, passt
  `python -m schichtplan e2n-vorlage <datei.csv> --schreiben` das Format
  selbst an, statt es zu raten.
* **Berufsschulplan** von A. Menzler endet bei `2027-KW05`. Danach plant das
  Werkzeug ihn als normal verfuegbar.
