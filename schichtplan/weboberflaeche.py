"""Weboberflaeche: Wochenvorgabe bearbeiten, rechnen, Plan ansehen.

Bewusst nur mit der Standardbibliothek - kein Flask, kein Node, nichts zu
installieren. 'python -m schichtplan web' startet den Server, der Browser
macht den Rest.

Die Oberflaeche arbeitet direkt auf den YAML-Dateien in wochen/. Alles, was
sie kann, laesst sich auch von Hand in der Datei machen - und umgekehrt
bleibt jede Datei bearbeitbar, auch wenn die Oberflaeche fuer ein neues Feld
noch kein Formular hat. Deshalb liegt neben jedem Formular der Rohtext.
"""
from __future__ import annotations

import datetime as _dt
import http.server
import json
import pathlib
import threading
import traceback
import urllib.parse
import webbrowser

import yaml

from . import lauf as _lauf
from .bewertung import SCHWEREGRADE, Bewerter
from .generator import _optionen
from .historie import lade_historie
from .konfig import lade_stammdaten, lade_wochenvorgabe, mit_aushilfen
from .modelle import TAGE, TAG_LANG, schicht_aus_text, zu_zeit

HIER = pathlib.Path(__file__).parent / "web"


ZUSTAENDE = {
    # Wert in der Oberflaeche -> (Block in der Wochendatei, Beschriftung)
    "urlaub":     ("urlaub", "Urlaub"),
    "krank":      ("krank", "Krank"),
    "schule":     ("schule", "Schule"),
    "sonstige":   ("sonstige", "Sonstige"),
    "wunsch_frei": ("wunsch_frei", "Wunsch frei"),
}
TAGESLISTEN = tuple(block for block, _ in ZUSTAENDE.values())


def _blockgrenzen(zeilen: list[str], block: str) -> tuple[int, int]:
    """(Zeile mit 'block:', erste Zeile danach, die nicht mehr dazugehoert).

    Fehlt der Block, wird er am Ende angelegt - so laesst sich auch eine
    Wochendatei bearbeiten, in der 'krank:' noch gar nicht vorkommt.
    """
    anfang = next((i for i, z in enumerate(zeilen)
                   if z.rstrip().startswith(f"{block}:")), None)
    if anfang is None:
        while zeilen and not zeilen[-1].strip():
            zeilen.pop()
        zeilen.extend(["", f"{block}:"])
        return len(zeilen) - 1, len(zeilen)
    ende = len(zeilen)
    for i in range(anfang + 1, len(zeilen)):
        if zeilen[i] and not zeilen[i][0].isspace() and not zeilen[i].startswith("#"):
            ende = i
            break
    while ende > anfang + 1 and not zeilen[ende - 1].strip():
        ende -= 1
    return anfang, ende


def _eintrag(zeilen: list[str], anfang: int, ende: int, mid: str) -> int | None:
    marke = f"  {mid}:"
    return next((i for i in range(anfang + 1, ende)
                 if zeilen[i].startswith(marke)), None)


def _einfuegen(zeilen: list[str], anfang: int, ende: int, zeile: str) -> None:
    """Hinter den letzten echten Eintrag des Blocks, sonst gleich darunter."""
    nach = anfang
    for i in range(anfang + 1, ende):
        if zeilen[i].startswith("  ") and not zeilen[i].lstrip().startswith("#"):
            nach = i
    zeilen.insert(nach + 1, zeile)


def _leerer_block(zeilen: list[str], anfang: int) -> None:
    """'block:' ohne Eintraege braucht ein {} - sonst ist der Wert None."""
    kopf = zeilen[anfang].split(":", 1)[0]
    zeilen[anfang] = f"{kopf}: {{}}"


def _notiz_setzen(text: str, inhalt: str) -> str:
    """Die Zeile 'notiz:' ersetzen - mehrzeilig als YAML-Block."""
    zeilen = [z for z in text.splitlines()]
    anfang = next((i for i, z in enumerate(zeilen)
                   if z.rstrip().startswith("notiz:")), None)
    if anfang is None:
        while zeilen and not zeilen[-1].strip():
            zeilen.pop()
        zeilen.append("")
        anfang = len(zeilen)
        zeilen.append('notiz: ""')
    ende = anfang + 1
    while ende < len(zeilen) and (not zeilen[ende].strip()
                                  or zeilen[ende].startswith("  ")):
        if zeilen[ende].strip() and not zeilen[ende].startswith("  "):
            break
        if not zeilen[ende].strip() and ende + 1 < len(zeilen) \
                and not zeilen[ende + 1].startswith("  "):
            break
        ende += 1
    sauber = inhalt.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not sauber:
        neu = ['notiz: ""']
    elif "\n" in sauber:
        neu = ["notiz: |-"] + [f"  {z}" for z in sauber.split("\n")]
    else:
        neu = ["notiz: " + yaml.safe_dump(sauber, allow_unicode=True,
                                          default_flow_style=True).strip()
               .removesuffix("\n...").strip()]
    return "\n".join(zeilen[:anfang] + neu + zeilen[ende:]) + "\n"


def _fest_setzen(text: str, mid: str, tag: str, wert: str) -> str:
    """Einen Eintrag im Block 'fest:' setzen oder entfernen.

    Von Hand im Text statt ueber ein neu geschriebenes YAML: die
    Wochendateien sind voller Kommentare, und die sollen eine Korrektur aus
    der Oberflaeche heraus ueberleben.
    """
    zeilen = text.splitlines()
    anfang, ende = _blockgrenzen(zeilen, "fest")
    stelle = _eintrag(zeilen, anfang, ende, mid)

    eintrag, kommentar = {}, ""
    if stelle is not None:
        roh = zeilen[stelle][len(f"  {mid}:"):]
        if " #" in roh:
            roh, kommentar = roh.split(" #", 1)
            kommentar = "  #" + kommentar
        eintrag = yaml.safe_load(roh) or {}
    if wert in ("", "auto"):
        eintrag.pop(tag, None)
    else:
        eintrag[tag] = wert

    if not eintrag:
        if stelle is not None:
            del zeilen[stelle]
            if not any(zeilen[i].startswith("  ") and
                       not zeilen[i].lstrip().startswith("#")
                       for i in range(anfang + 1, ende - 1)):
                _leerer_block(zeilen, anfang)
        return "\n".join(zeilen) + "\n"

    geordnet = {t: eintrag[t] for t in TAGE if t in eintrag}
    geordnet.update({k: v for k, v in eintrag.items() if k not in TAGE})
    inhalt = ", ".join(f"{k}: {v}" for k, v in geordnet.items())
    zeile = f"  {mid}: {{{inhalt}}}{kommentar}"
    if stelle is None:
        zeilen[anfang] = zeilen[anfang].split(":", 1)[0] + ":"
        _einfuegen(zeilen, anfang, ende, zeile)
    else:
        zeilen[stelle] = zeile
    return "\n".join(zeilen) + "\n"


def _tage_setzen(text: str, block: str, mid: str, tag: str, an: bool) -> str:
    """Einen Tag in einem Block mit Tageslisten setzen oder streichen.

    Das sind 'urlaub', 'krank', 'schule', 'sonstige' und 'wunsch_frei' - dort
    steht je Person eine Liste von Tagen. 'alle' wird dabei zur vollen Woche
    aufgeloest, sobald ein einzelner Tag daraus verschwindet.
    """
    zeilen = text.splitlines()
    anfang, ende = _blockgrenzen(zeilen, block)
    stelle = _eintrag(zeilen, anfang, ende, mid)

    tage, kommentar = [], ""
    if stelle is not None:
        roh = zeilen[stelle][len(f"  {mid}:"):]
        if " #" in roh:
            roh, kommentar = roh.split(" #", 1)
            kommentar = "  #" + kommentar
        wert = yaml.safe_load(roh)
        if wert in ("alle", "Alle"):
            tage = list(TAGE)
        elif isinstance(wert, str):
            tage = [wert]
        elif wert:
            tage = list(wert)
    tage = [t for t in TAGE if t in tage]
    if an and tag not in tage:
        tage.append(tag)
    elif not an and tag in tage:
        tage.remove(tag)
    tage = [t for t in TAGE if t in tage]

    if not tage:
        if stelle is not None:
            del zeilen[stelle]
            if not any(zeilen[i].startswith("  ") and
                       not zeilen[i].lstrip().startswith("#")
                       for i in range(anfang + 1, ende - 1)):
                _leerer_block(zeilen, anfang)
        return "\n".join(zeilen) + "\n"

    wert = "alle" if len(tage) == len(TAGE) else "[" + ", ".join(tage) + "]"
    zeile = f"  {mid}: {wert}{kommentar}"
    if stelle is None:
        zeilen[anfang] = zeilen[anfang].split(":", 1)[0] + ":"
        _einfuegen(zeilen, anfang, ende, zeile)
    else:
        zeilen[stelle] = zeile
    return "\n".join(zeilen) + "\n"


class Werkstatt:
    """Haelt die Pfade und die laufenden Rechenauftraege."""

    def __init__(self, konfig: str, wochen: str, ausgabe: str, historie: str):
        self.konfig = pathlib.Path(konfig)
        self.wochen = pathlib.Path(wochen)
        self.ausgabe = pathlib.Path(ausgabe)
        self.historie = pathlib.Path(historie)
        self.auftraege: dict[str, dict] = {}
        self.sperre = threading.Lock()

    # ---- Stammdaten ---------------------------------------------------- #
    def stammdaten(self):
        return lade_stammdaten(self.konfig)

    def vorwochen(self, bis: str | None = None):
        wochen = lade_historie(self.historie) if self.historie.exists() else []
        return [w for w in wochen if bis is None or w.woche < bis]

    # ---- Wochenliste --------------------------------------------------- #
    def liste(self) -> list[dict]:
        eintraege = []
        for pfad in sorted(self.wochen.glob("*.yaml")):
            name = pfad.stem
            plan = self.ausgabe / f"{name}.json"
            eintraege.append({
                "woche": name,
                "geplant": plan.exists(),
                "uebernommen": (self.historie / f"{name}.json").exists(),
                "geaendert": _dt.datetime.fromtimestamp(
                    pfad.stat().st_mtime).strftime("%d.%m. %H:%M"),
            })
        return eintraege

    def vorwoche_fehlt(self, name: str) -> str | None:
        """Steht die Woche davor schon in der Historie?

        Frueh/Spaet-Ausgleich, Samstagskonto und Stundenkonto rechnen ueber
        das rollierende Fenster. Fehlt die Vorwoche, plant der Planer blind
        und verteilt die Fairness gegen einen veralteten Stand. Das ist kein
        Fehler, aber man sollte es wissen.
        """
        try:
            jahr, kw = name.split("-KW")
            montag = _dt.date.fromisocalendar(int(jahr), int(kw), 1)
        except ValueError:
            return None
        vorher = montag - _dt.timedelta(days=7)
        j, w, _ = vorher.isocalendar()
        davor = f"{j}-KW{w:02d}"
        if (self.historie / f"{davor}.json").exists():
            return None
        geplant = (self.ausgabe / f"{davor}.json").exists()
        if not self.pfad(davor).exists() and not geplant:
            return None          # die Woche gibt es gar nicht, also kein Thema
        return davor

    def pfad(self, woche: str) -> pathlib.Path:
        """Pfad zur Wochendatei - mit Schutz gegen Ausbrueche aus dem Ordner."""
        ziel = (self.wochen / f"{woche}.yaml").resolve()
        if ziel.parent != self.wochen.resolve():
            raise ValueError(f"unzulaessiger Wochenname: {woche}")
        return ziel

    # ---- Eine Woche ---------------------------------------------------- #
    def woche(self, name: str) -> dict:
        pfad = self.pfad(name)
        if not pfad.exists():
            raise FileNotFoundError(f"{name} gibt es nicht")
        antwort: dict = {"woche": name, "yaml": pfad.read_text(encoding="utf-8")}
        try:
            vorgabe = lade_wochenvorgabe(pfad)
            stamm = mit_aushilfen(self.stammdaten(), vorgabe)
        except Exception as fehler:          # kaputte Datei soll nicht die
            antwort["fehler"] = str(fehler)  # ganze Seite lahmlegen
            return antwort
        bewerter = Bewerter(stamm, vorgabe, self.vorwochen(bis=vorgabe.woche))
        antwort["notiz"] = vorgabe.notiz
        antwort["kopf"] = {"von": vorgabe.datum_von, "bis": vorgabe.datum_bis,
                           "filiale": vorgabe.filiale, "modus": vorgabe.modus,
                           "pause_h": stamm.bedarf.pause_h,
                           "budget": round(bewerter.gesamtbudget())}
        antwort["mitarbeiter"] = [
            {"id": mid, "name": m.name, "soll_h": m.soll_stunden,
             "soll_tage": m.soll_tage, "aushilfe": bool(vorgabe.aushilfe) and any(
                 a.get("id") == mid for a in vorgabe.aushilfe),
             "schichten": [{"id": s.id, "kategorie": s.kategorie}
                           for t in TAGE
                           for s in _optionen(stamm, mid, t, vorgabe) if s]
             and {t: [{"id": s.id, "kategorie": s.kategorie}
                      for s in _optionen(stamm, mid, t, vorgabe) if s]
                  for t in TAGE}}
            for mid, m in stamm.mitarbeiter.items() if m.im_plan]
        antwort["bedarf"] = {
            "kopfzahl": dict(stamm.bedarf.kopfzahl),
            "offene_tage": list(stamm.bedarf.offene_tage),
        }
        # Was in der Wochendatei vorgegeben ist - die Oberflaeche faerbt die
        # Zellen danach und kann die Woche auch ohne Plan schon zeigen.
        gesetzt: dict[str, dict[str, str]] = {}
        for mid, tage in vorgabe.abwesend.items():
            for t_, art in tage.items():
                gesetzt.setdefault(mid, {})[t_] = art
        for mid, tage in vorgabe.wunsch_frei.items():
            for t_ in tage:
                gesetzt.setdefault(mid, {}).setdefault(t_, "wunsch_frei")
        for mid, tage in vorgabe.fest.items():
            for t_, schicht in tage.items():
                gesetzt.setdefault(mid, {})[t_] = (
                    "frei" if str(schicht).lower() == "frei" else str(schicht))
        antwort["vorgabe"] = gesetzt
        antwort["vorwoche_fehlt"] = self.vorwoche_fehlt(name)
        plan = self.ausgabe / f"{name}.json"
        if plan.exists():
            antwort["plan"] = json.loads(plan.read_text(encoding="utf-8"))
            antwort["befunde"], antwort["punkte"] = self._bewertung(name)
            antwort["kategorien"] = {
                s.id: s.kategorie for s in stamm.schichten.values()}
        return antwort

    def _bewertung(self, name: str) -> tuple[list[dict] | None, float | None]:
        """(Befunde, Gesamtpunkte) zum gespeicherten Plan.

        Der Lauf aus der Oberflaeche legt beides als Datei ab; stammt der Plan
        aus der Kommandozeile, wird hier nachgerechnet - sonst stuende ein
        fremder Plan ohne Bewertung da. Die Gesamtpunkte sind mehr als die
        Summe der angezeigten Befunde: vieles kostet Punkte, ohne dass es
        einen Satz wert waere.
        """
        datei = self.ausgabe / f"{name}-befunde.json"
        if datei.exists():
            roh = json.loads(datei.read_text(encoding="utf-8"))
            if isinstance(roh, dict):
                return roh.get("befunde"), roh.get("punkte")
            return roh, None                      # Datei aus einer alten Fassung
        from .cli import _plan_aus_json
        from .bewertung import pruefen
        quelle = self.ausgabe / f"{name}.json"
        if not quelle.exists():
            return None, None
        vorgabe = lade_wochenvorgabe(self.pfad(name))
        stamm = mit_aushilfen(self.stammdaten(), vorgabe)
        bew = pruefen(_plan_aus_json(quelle, stamm), stamm, vorgabe,
                      self.vorwochen(bis=name))
        return ([{"regel": b.regel, "punkte": round(b.punkte), "text": b.text,
                  "schwere": b.schwere} for b in bew.befunde if b.text],
                round(bew.punkte))

    def speichern(self, name: str, text: str) -> dict:
        """Rohtext schreiben - aber erst, wenn er sich laden laesst."""
        pfad = self.pfad(name)
        sicherung = pfad.read_text(encoding="utf-8") if pfad.exists() else None
        pfad.write_text(text, encoding="utf-8")
        try:
            lade_wochenvorgabe(pfad)
        except Exception as fehler:
            if sicherung is not None:
                pfad.write_text(sicherung, encoding="utf-8")
            raise ValueError(f"nicht gespeichert - {fehler}") from None
        return {"ok": True}

    def zelle(self, name: str, mid: str, tag: str, wert: str) -> dict:
        """Eine Zelle setzen - Schicht, frei, Urlaub, Wunschfrei, was auch immer.

        Alles landet in der Wochendatei: Schichten und ein festes "frei"
        unter 'fest', Abwesenheiten und Wuensche in ihrem eigenen Block. Was
        hier steht, ist eine Vorgabe und bleibt beim naechsten Rechnen stehen.

        Gibt es schon einen gerechneten Plan, wird die Aenderung gleich in
        ihn uebernommen und die Woche neu bewertet - sonst sprae'nge die Zelle
        beim naechsten Zeichnen auf den alten Wert zurueck.
        """
        if tag not in TAGE:
            raise ValueError(f"unbekannter Tag: {tag}")
        pfad = self.pfad(name)
        text = pfad.read_text(encoding="utf-8")

        # Erst raeumen: dieselbe Zelle darf nicht in zwei Bloecken stehen.
        for block in TAGESLISTEN:
            text = _tage_setzen(text, block, mid, tag, False)
        zustand = ZUSTAENDE.get(wert)
        if zustand:
            text = _fest_setzen(text, mid, tag, "auto")
            text = _tage_setzen(text, zustand[0], mid, tag, True)
        else:
            text = _fest_setzen(text, mid, tag, wert)

        antwort = self.speichern(name, text) | {"yaml": text}
        antwort.update(self._plan_nachziehen(name, mid, tag, wert))
        return antwort

    def notiz(self, name: str, text: str) -> dict:
        """Die freie Bemerkung der Woche setzen.

        Sie steht unter 'notiz:' in der Wochendatei und landet unten auf dem
        Papierplan - fuer alles, was sich nicht in Schichten ausdruecken
        laesst: "Mittwoch Lieferung 7 Uhr", "Samstag Grossputz".
        """
        pfad = self.pfad(name)
        neu = _notiz_setzen(pfad.read_text(encoding="utf-8"), text)
        antwort = self.speichern(name, neu) | {"yaml": neu, "notiz": text}
        if (self.ausgabe / f"{name}.json").exists():
            self._neu_schreiben(name)       # die Notiz steht im Papierplan
        return antwort

    def _plan_nachziehen(self, name: str, mid: str, tag: str, wert: str) -> dict:
        """Die Handkorrektur in den gespeicherten Plan uebernehmen.

        Der Plan wird dabei nicht neu gerechnet - nur diese eine Zelle
        geaendert, neu bewertet und die Ausgabedateien neu geschrieben. Wer
        die Woche danach rechnen laesst, bekommt die Zelle als Vorgabe
        wieder, weil sie in der Wochendatei steht.
        """
        quelle = self.ausgabe / f"{name}.json"
        if not quelle.exists():
            return {}
        roh = json.loads(quelle.read_text(encoding="utf-8"))
        reihe = roh.get("plan", {}).get(mid)
        if reihe is None:
            return {}
        if wert in ("", "auto", "frei"):
            reihe[tag] = {"art": "frei", "zusatz": []}
        elif wert in ZUSTAENDE:
            reihe[tag] = {"art": ZUSTAENDE[wert][0], "zusatz": []}
        else:
            von, bis = schicht_aus_text(str(wert)).von, schicht_aus_text(str(wert)).bis
            reihe[tag] = {"art": "schicht", "von": zu_zeit(von),
                          "bis": zu_zeit(bis), "zusatz": []}
        quelle.write_text(json.dumps(roh, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
        (self.ausgabe / f"{name}-befunde.json").unlink(missing_ok=True)
        self._neu_schreiben(name)
        befunde, punkte = self._bewertung(name)
        return {"plan": roh, "befunde": befunde, "punkte": punkte}

    def _neu_schreiben(self, name: str) -> None:
        """Papierplan und Exporte aus dem gespeicherten Plan neu erzeugen."""
        from .cli import _plan_aus_json
        from .bewertung import pruefen
        vorgabe = lade_wochenvorgabe(self.pfad(name))
        stamm = mit_aushilfen(self.stammdaten(), vorgabe)
        vorwochen = self.vorwochen(bis=name)
        plan = _plan_aus_json(self.ausgabe / f"{name}.json", stamm)
        # Die Notiz steht in der Wochenvorgabe, nicht in der Planjson - sonst
        # faende sie den Weg auf den Papierplan erst beim naechsten Rechnen.
        plan.notiz = vorgabe.notiz
        bew = pruefen(plan, stamm, vorgabe, vorwochen)
        _lauf.schreibe(plan, stamm, bew, Bewerter(stamm, vorgabe, vorwochen),
                       vorwochen, self.ausgabe)

    # ---- Rechnen ------------------------------------------------------- #
    def starte(self, name: str, einstellungen: dict) -> str:
        kennung = f"{name}-{_dt.datetime.now():%H%M%S%f}"
        auftrag = {"woche": name, "stand": "laeuft", "meldungen": []}
        with self.sperre:
            self.auftraege[kennung] = auftrag
        faden = threading.Thread(target=self._rechne, daemon=True,
                                 args=(kennung, name, einstellungen))
        faden.start()
        return kennung

    def _rechne(self, kennung: str, name: str, einst: dict) -> None:
        auftrag = self.auftraege[kennung]
        try:
            vorgabe = lade_wochenvorgabe(self.pfad(name))
            stamm = mit_aushilfen(self.stammdaten(), vorgabe)
            vorwochen = self.vorwochen(bis=vorgabe.woche)
            erg = _lauf.plane(stamm, vorgabe, vorwochen,
                              iterationen=int(einst.get("iterationen", 120000)),
                              neustarts=int(einst.get("neustarts", 6)),
                              seed=einst.get("seed"))
            bewerter = Bewerter(stamm, vorgabe, vorwochen)
            dateien, meldungen = _lauf.schreibe(
                erg.plan, stamm, erg.bewertung, bewerter, vorwochen, self.ausgabe,
                pdf=bool(einst.get("pdf")))
            befunde = [{"regel": b.regel, "punkte": round(b.punkte),
                        "text": b.text, "schwere": b.schwere}
                       for b in erg.bewertung.befunde if b.text]
            (self.ausgabe / f"{name}-befunde.json").write_text(
                json.dumps({"punkte": round(erg.bewertung.punkte),
                            "befunde": befunde}, ensure_ascii=False, indent=2),
                encoding="utf-8")
            if (davor := self.vorwoche_fehlt(name)):
                meldungen.append(
                    f"{davor} steht noch nicht in der Historie - Konten und "
                    f"Ausgleich rechnen deshalb gegen einen alten Stand.")
            auftrag.update(stand="fertig", punkte=round(erg.bewertung.punkte),
                           start=round(erg.startpunkte), befunde=befunde,
                           dateien=[pathlib.Path(d).name for d in dateien],
                           meldungen=meldungen)
        except Exception as fehler:
            auftrag.update(stand="fehler", fehler=str(fehler),
                           spur=traceback.format_exc())

    def uebernehmen(self, name: str) -> dict:
        quelle = self.ausgabe / f"{name}.json"
        if not quelle.exists():
            raise FileNotFoundError("Fuer diese Woche gibt es noch keinen Plan")
        roh = json.loads(quelle.read_text(encoding="utf-8"))
        fehlend = sorted({t for t in TAGE
                          for reihe in roh["plan"].values() if t not in reihe})
        if fehlend:
            raise ValueError(f"Plan unvollstaendig, es fehlen: {', '.join(fehlend)}")
        roh["status"] = "final"
        roh.setdefault("quelle_foto", "")
        roh["notiz"] = ((roh.get("notiz", "") + " ") if roh.get("notiz") else "") \
            + "generiert, uebernommen ueber die Weboberflaeche"
        self.historie.mkdir(parents=True, exist_ok=True)
        ziel = self.historie / f"{name}.json"
        ziel.write_text(json.dumps(roh, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        return {"ok": True, "wochen": len(lade_historie(self.historie))}

    def konten(self) -> str:
        from . import konten as _konten
        wochen = self.vorwochen()
        if not wochen:
            return "<p>Noch keine Wochen in der Historie.</p>"
        return _konten.als_html(_konten.sammle(self.stammdaten(), wochen))


# ---- HTTP ------------------------------------------------------------- #
class _Handler(http.server.BaseHTTPRequestHandler):
    werkstatt: Werkstatt = None          # wird in starte() gesetzt
    server_version = "Schichtplan"

    def log_message(self, format, *args):      # noqa: A002 - Signatur der Basis
        pass                                   # kein Zugriffslog im Terminal

    # -- Werkzeug --
    def _sende(self, inhalt: bytes, typ: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(inhalt)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(inhalt)

    def _json(self, daten, code: int = 200) -> None:
        self._sende(json.dumps(daten, ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8", code)

    def _datei(self, pfad: pathlib.Path) -> None:
        typen = {".html": "text/html; charset=utf-8",
                 ".css": "text/css; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8",
                 ".json": "application/json; charset=utf-8",
                 ".csv": "text/csv; charset=utf-8",
                 ".pdf": "application/pdf",
                 ".svg": "image/svg+xml",
                 ".png": "image/png",
                 ".ico": "image/x-icon"}
        if not pfad.exists() or not pfad.is_file():
            self._json({"fehler": f"{pfad.name} gibt es nicht"}, 404)
            return
        self._sende(pfad.read_bytes(),
                    typen.get(pfad.suffix, "application/octet-stream"))

    def _koerper(self) -> dict:
        laenge = int(self.headers.get("Content-Length") or 0)
        if not laenge:
            return {}
        return json.loads(self.rfile.read(laenge).decode("utf-8"))

    # -- Routen --
    def do_GET(self) -> None:                   # noqa: N802 - Name der Basis
        pfad = urllib.parse.urlparse(self.path).path
        w = self.werkstatt
        try:
            if pfad in ("/", "/index.html"):
                self._datei(HIER / "index.html")
            elif pfad in ("/app.js", "/stil.css"):
                self._datei(HIER / pfad.lstrip("/"))
            elif pfad.startswith("/bild/"):
                name = urllib.parse.unquote(pfad.split("/", 2)[2])
                ziel = (HIER / "bild" / name).resolve()
                if ziel.parent != (HIER / "bild").resolve():
                    self._json({"fehler": "unzulaessiger Pfad"}, 400)
                else:
                    self._datei(ziel)
            elif pfad == "/api/wochen":
                self._json(w.liste())
            elif pfad.startswith("/api/woche/"):
                self._json(w.woche(urllib.parse.unquote(pfad.split("/")[3])))
            elif pfad.startswith("/api/auftrag/"):
                kennung = urllib.parse.unquote(pfad.split("/")[3])
                self._json(w.auftraege.get(kennung, {"stand": "unbekannt"}))
            elif pfad == "/api/konten":
                self._sende(w.konten().encode("utf-8"), "text/html; charset=utf-8")
            elif pfad.startswith("/ausgabe/"):
                name = urllib.parse.unquote(pfad.split("/", 2)[2])
                ziel = (w.ausgabe / name).resolve()
                if ziel.parent != w.ausgabe.resolve():
                    self._json({"fehler": "unzulaessiger Pfad"}, 400)
                else:
                    self._datei(ziel)
            else:
                self._json({"fehler": "unbekannte Adresse"}, 404)
        except FileNotFoundError as fehler:
            self._json({"fehler": str(fehler)}, 404)
        except Exception as fehler:
            self._json({"fehler": str(fehler), "spur": traceback.format_exc()}, 500)

    def do_POST(self) -> None:                  # noqa: N802
        pfad = urllib.parse.urlparse(self.path).path
        w, teile = self.werkstatt, pfad.strip("/").split("/")
        try:
            koerper = self._koerper()
            if len(teile) == 4 and teile[:2] == ["api", "woche"]:
                name, was = urllib.parse.unquote(teile[2]), teile[3]
                if was == "speichern":
                    self._json(w.speichern(name, koerper["yaml"]))
                elif was == "zelle":
                    self._json(w.zelle(name, koerper["mitarbeiter"],
                                       koerper["tag"], koerper.get("wert", "")))
                elif was == "plan":
                    self._json({"auftrag": w.starte(name, koerper)})
                elif was == "notiz":
                    self._json(w.notiz(name, koerper.get("text", "")))
                elif was == "uebernehmen":
                    self._json(w.uebernehmen(name))
                else:
                    self._json({"fehler": "unbekannte Aktion"}, 404)
            else:
                self._json({"fehler": "unbekannte Adresse"}, 404)
        except (ValueError, FileNotFoundError) as fehler:
            self._json({"fehler": str(fehler)}, 400)
        except Exception as fehler:
            self._json({"fehler": str(fehler), "spur": traceback.format_exc()}, 500)


def starte(werkstatt: Werkstatt, *, host: str = "127.0.0.1", port: int = 8777,
           browser: bool = True) -> None:
    _Handler.werkstatt = werkstatt
    server = http.server.ThreadingHTTPServer((host, port), _Handler)
    adresse = f"http://{host}:{port}/"
    print(f"Schichtplan laeuft auf {adresse}")
    print("Beenden mit Strg+C.")
    if browser:
        threading.Timer(0.5, lambda: webbrowser.open(adresse)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer beendet.")
    finally:
        server.server_close()
