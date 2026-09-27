# Format der digitalisierten Altplaene

Eine JSON-Datei je Woche in `daten/historie/`, Dateiname = `woche`.

```jsonc
{
  "woche": "2025-KW41",              // JJJJ-KWnn; Entwuerfe mit Suffix -v1, -v2
  "datum_von": "2025-10-05",         // Montag, ISO
  "datum_bis": "2025-10-10",         // Samstag
  "filiale": "Winterbach",
  "status": "final",                 // final | entwurf - nur "final" wird ausgewertet
  "quelle_foto": "2ad1a66d-image.jpg",
  "notiz": "optional",
  "tage": ["mo","di","mi","do","fr","sa"],
  "plan": {
    "kurka_j": {
      "mo": {"art": "schicht", "von": "06:00", "bis": "14:00", "zusatz": []},
      "di": {"art": "schicht", "von": "06:00", "bis": "13:30", "zusatz": []},
      "do": {"art": "frei", "zusatz": []}
      // ... alle sechs Tage muessen vorhanden sein
    }
  }
}
```

## Zellarten

| `art` | Papierplan | zaehlt als Arbeitszeit |
|---|---|---|
| `schicht` | `6-14`, `6-13:30` | ja |
| `frei` | `Frei` | nein |
| `urlaub` | `Urlaub` / `u` | nein |
| `schule` | `Schule` | nein |
| `krank` | `Krank` | nein |
| `feiertag` | durchgestrichene Spalte | nein, Tag gilt als geschlossen |
| `nicht_im_plan` | `-` | nein, Zeile wird nur mitgedruckt |
| `sonstige` | sonstige Abwesenheit | nein |

## Konventionen

* Zeiten nur auf volle oder halbe Stunden (`"13:30"`), sonst wirft der Loader.
* `zusatz` fuer Vermerke neben der Zeit: `schulung`, `grossputz`, `inventur`.
* Zellen, die auf dem Foto keine Endzeit haben (`"6-"`), bekommen
  `"bis": null` und `"unklar": true`. Sie fliessen nicht in die Statistik ein.
* Wird ein Plan nach Aushang geaendert, kommt die Erstfassung als eigene Datei
  mit `-v1` und `status: entwurf` dazu. So bleibt sichtbar, wie oft und wo
  kurzfristig umgeplant wird.
