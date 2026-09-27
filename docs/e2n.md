# Uebergabe an e2n

## Was es an Schnittstellen gibt

e2n hat eine **REST-API mit API-Key**, die der Mandant selbst freischaltet:

> Benutzer > Verwaltung > Schnittstellen > REST API

Sobald der Schalter an ist, wird ein API-Key erzeugt (und laesst sich dort auch
erneuern). Quelle: e2n-Hilfecenter, Artikel *API-Access* bzw. *Wo finde ich den
API-Key?*.

**Was diese API kann, ist oeffentlich nicht dokumentiert.** Die oeffentlich
auffindbaren Integrationen (APRO, helloTESS, Lightspeed) schieben Kassen- und
Umsatzdaten *nach* e2n, damit die Planung umsatzgestuetzt rechnen kann. Ob
Schichten per API *geschrieben* werden koennen, steht nirgends frei zugaenglich
- das beantwortet nur die Doku hinter dem eigenen Login oder der e2n-Support.

Fuer Mitarbeiterstammdaten gibt es ausserdem einen gesicherten Datei-Import
(Benutzer > Verwaltung > Mandant > Mitarbeiterimport, .xls oder CSV UTF-8).
Ein entsprechender Datei-Import fuer den Dienstplan ist in der oeffentlichen
Hilfe nicht beschrieben.

## Wie dieses Projekt damit umgeht

Der Export ist zweistufig, damit der Weg nach e2n austauschbar bleibt:

1. `ausgabe/<woche>-e2n-schichten.csv` - eine Zeile je Schicht:
   `Mitarbeiter; Personalnummer; Datum; Beginn; Ende; Pause_Minuten; Arbeitsbereich; Notiz`
2. `ausgabe/<woche>-e2n-abwesenheiten.csv` - Urlaub/Schule/Krank getrennt,
   weil das in e2n eine eigene Datensatzart ist.

Spaltennamen und -reihenfolge stehen in `schichtplan/export.py` und sind in
zwei Minuten an eine echte Importvorlage angepasst.

## Naechster Schritt, um es vollautomatisch zu machen

Drei Dinge werden gebraucht, dann ist der API-Adapter schnell gebaut:

1. API-Key aus dem eigenen Mandanten (Benutzer > Verwaltung > Schnittstellen).
2. Die API-Doku hinter dem Login - Basis-URL, Authentifizierungsart
   (Header? Query-Parameter?) und ob es einen Endpunkt fuer Schichten gibt.
3. Die internen e2n-IDs der Mitarbeiter und des Arbeitsbereichs/der Position,
   damit die Zuordnung eindeutig ist (dafuer ist die Spalte `Personalnummer`
   im CSV schon vorgesehen).

Wenn es keinen Schreib-Endpunkt fuer Schichten gibt, bleiben zwei Wege:
Datei-Import (falls e2n einen fuer Dienstplaene anbietet - beim Support
erfragen) oder Browser-Automatisierung der Manager-Oberflaeche.
Letzteres funktioniert, ist aber gegenueber jedem Oberflaechen-Update
anfaellig - erst die API-Frage klaeren.
