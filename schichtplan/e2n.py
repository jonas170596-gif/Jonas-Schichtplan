"""Den e2n-Export an eine echte Importvorlage anpassen.

Welche Spalten e2n erwartet, steht nicht in diesem Projekt - und e2n war
beim Bauen nicht erreichbar. Statt die Namen zu raten und bei jedem Irrtum
am Code zu drehen, liest dieses Modul die Kopfzeile einer Datei aus e2n
(Importvorlage oder ein Export, egal) und schreibt daraus konfig/e2n.yaml.

    python -m schichtplan e2n-vorlage vorlage.csv

Was sich nicht zuordnen laesst, wird gemeldet statt still verschluckt.
"""
from __future__ import annotations

import csv
import pathlib
import re

# Spaltennamen, die uns ueber den Weg laufen koennen, je Feld. Verglichen
# wird kleingeschrieben und ohne Trennzeichen, "Pers.-Nr." trifft also
# "persnr".
SYNONYME: dict[str, tuple[str, ...]] = {
    "personalnummer": ("personalnummer", "persnr", "persnummer",
                       "mitarbeiternummer", "manr", "manummer", "nummer",
                       "employeenumber", "staffnumber", "id", "token"),
    "nachname":       ("nachname", "name", "familienname", "lastname",
                       "surname"),
    "vorname":        ("vorname", "firstname", "givenname"),
    "mitarbeiter":    ("mitarbeiter", "mitarbeiterin", "person", "employee",
                       "namevollstaendig", "vollername", "anzeigename"),
    "datum":          ("datum", "tag", "date", "schichtdatum", "von datum"),
    "beginn":         ("beginn", "start", "startzeit", "beginnzeit", "von",
                       "anfang", "starttime", "beginnuhrzeit"),
    "ende":           ("ende", "end", "endzeit", "bis", "schluss", "endtime",
                       "endeuhrzeit"),
    "pause":          ("pause", "pausen", "pauseminuten", "pauseminuten",
                       "pausezeit", "break", "breakminutes", "pausendauer"),
    "dauer":          ("dauer", "stunden", "arbeitszeit", "sollstunden",
                       "duration", "hours"),
    "arbeitsbereich": ("arbeitsbereich", "bereich", "abteilung", "position",
                       "taetigkeit", "schichtart", "dienstart", "workarea",
                       "department"),
    "notiz":          ("notiz", "bemerkung", "kommentar", "hinweis", "note",
                       "comment"),
    "art":            ("art", "abwesenheitsart", "abwesenheit", "grund",
                       "typ", "fehlzeit", "fehlzeitart", "absencetype"),
}

# Welche Felder eine Schichtdatei ausmachen und welche eine Abwesenheitsdatei.
SCHICHTFELDER = ("mitarbeiter", "nachname", "vorname", "personalnummer",
                 "datum", "beginn", "ende", "pause", "dauer",
                 "arbeitsbereich", "notiz")
ABWESENDFELDER = ("mitarbeiter", "nachname", "vorname", "personalnummer",
                  "datum", "art", "notiz")


def _schluessel(text: str) -> str:
    ersetzt = (text.strip().lower()
               .replace("ä", "ae").replace("ö", "oe")
               .replace("ü", "ue").replace("ß", "ss"))
    return re.sub(r"[^a-z0-9]", "", ersetzt)


def _feld(spalte: str) -> str | None:
    """Welches unserer Felder meint diese Spalte? None, wenn unklar."""
    s = _schluessel(spalte)
    if not s:
        return None
    for feld, namen in SYNONYME.items():
        if s in (_schluessel(n) for n in namen):
            return feld
    # Zweiter Anlauf: Teiltreffer, damit "Beginn (Uhrzeit)" noch landet.
    for feld, namen in SYNONYME.items():
        for n in namen:
            k = _schluessel(n)
            if len(k) >= 4 and (s.startswith(k) or k in s):
                return feld
    return None


def lies_kopf(pfad: pathlib.Path) -> tuple[list[str], str, str]:
    """(Spalten, Trennzeichen, Zeichensatz) der Datei."""
    roh = pfad.read_bytes()
    zeichensatz = "utf-8-sig" if roh.startswith(b"\xef\xbb\xbf") else "utf-8"
    try:
        text = roh.decode(zeichensatz)
    except UnicodeDecodeError:
        zeichensatz = "cp1252"       # was Excel unter Windows gern ausgibt
        text = roh.decode(zeichensatz, errors="replace")
    erste = next((z for z in text.splitlines() if z.strip()), "")
    if not erste:
        raise ValueError(f"{pfad.name} ist leer")
    trennzeichen = max((";", ",", "\t", "|"), key=erste.count)
    if erste.count(trennzeichen) == 0:
        raise ValueError(
            f"{pfad.name}: in der ersten Zeile steht kein Trennzeichen - "
            f"ist das wirklich eine CSV-Datei?")
    spalten = next(csv.reader([erste], delimiter=trennzeichen))
    return [s.strip() for s in spalten], trennzeichen, zeichensatz


def zuordnung(spalten: list[str]) -> tuple[dict[str, str], list[str], str]:
    """(Feld -> Spaltenname, nicht zugeordnete Spalten, welche Datei das ist).

    Ob es um Schichten oder Abwesenheiten geht, verraet die Datei selbst:
    Beginn und Ende gibt es nur bei Schichten, eine Art nur bei
    Abwesenheiten.
    """
    gefunden: dict[str, str] = {}
    offen: list[str] = []
    for spalte in spalten:
        feld = _feld(spalte)
        if feld and feld not in gefunden:
            gefunden[feld] = spalte
        else:
            offen.append(spalte)
    if "beginn" in gefunden or "ende" in gefunden:
        welche = "schichten"
    elif "art" in gefunden:
        welche = "abwesenheiten"
    else:
        welche = "schichten"
    erlaubt = SCHICHTFELDER if welche == "schichten" else ABWESENDFELDER
    for feld in list(gefunden):
        if feld not in erlaubt:
            offen.append(gefunden.pop(feld))
    return gefunden, offen, welche


def reihenfolge(spalten: list[str], gefunden: dict[str, str]) -> list[str]:
    """Die Felder in der Reihenfolge, in der sie in der Vorlage stehen."""
    nach_spalte = {spalte: feld for feld, spalte in gefunden.items()}
    return [nach_spalte[s] for s in spalten if s in nach_spalte]


def als_yaml(format, bemerkung: str = "") -> str:
    """Das Format als konfig/e2n.yaml - von Hand gesetzt, damit die
    Kommentare drin bleiben."""
    def block(spalten, folge, einzug="    "):
        breite = max((len(f) for f in folge), default=0) + 1
        zeilen = [f"{einzug}{f + ':':<{breite}} {spalten[f]}" for f in folge]
        return "\n".join(zeilen)

    kopf = ["# Wie der e2n-Export aussieht."]
    if bemerkung:
        kopf.append(f"# {bemerkung}")
    kopf.append("#")
    kopf.append("# Erzeugt mit 'python -m schichtplan e2n-vorlage'. Von Hand")
    kopf.append("# aendern geht auch - es ist nur eine YAML-Datei.")
    arten = "\n".join(f"    {k + ':':<10} {v}" for k, v in format.arten.items())
    return f"""{chr(10).join(kopf)}

trennzeichen: "{format.trennzeichen}"
zeichensatz: {format.zeichensatz}
datumsformat: "{format.datumsformat}"
zeitformat: "{format.zeitformat}"

# Eine Zeile je Schicht.
schichten:
  spalten:
{block(format.schicht_spalten, format.schicht_reihenfolge)}
  reihenfolge: [{", ".join(format.schicht_reihenfolge)}]

# Urlaub, Krankheit und Berufsschule - in e2n eine eigene Datensatzart.
abwesenheiten:
  spalten:
{block(format.abwesend_spalten, format.abwesend_reihenfolge)}
  reihenfolge: [{", ".join(format.abwesend_reihenfolge)}]
  arten:
{arten}
"""


def uebernehmen(vorlage: pathlib.Path, bisher) -> tuple[object, dict]:
    """Das Format aus einer Vorlage ableiten. Gibt (Format, Bericht) zurueck."""
    import dataclasses
    spalten, trennzeichen, zeichensatz = lies_kopf(vorlage)
    gefunden, offen, welche = zuordnung(spalten)
    if not gefunden:
        raise ValueError(
            f"{vorlage.name}: keine der {len(spalten)} Spalten war zuzuordnen. "
            f"Kopfzeile: {', '.join(spalten[:8])}")
    folge = reihenfolge(spalten, gefunden)
    aenderung = {"trennzeichen": trennzeichen, "zeichensatz": zeichensatz}
    if welche == "schichten":
        aenderung |= {"schicht_spalten": gefunden, "schicht_reihenfolge": folge}
    else:
        aenderung |= {"abwesend_spalten": gefunden,
                      "abwesend_reihenfolge": folge}
    neu = dataclasses.replace(bisher, **aenderung)
    bericht = {"welche": welche, "gefunden": gefunden, "offen": offen,
               "spalten": spalten, "trennzeichen": trennzeichen,
               "zeichensatz": zeichensatz,
               "fehlend": [f for f in (("datum", "beginn", "ende")
                                       if welche == "schichten"
                                       else ("datum", "art"))
                           if f not in gefunden]}
    return neu, bericht
