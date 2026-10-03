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
from .modelle import TAGE, TAG_LANG

HIER = pathlib.Path(__file__).parent / "web"


def _fest_setzen(text: str, mid: str, tag: str, wert: str) -> str:
    """Einen Eintrag im Block 'fest:' setzen oder entfernen.

    Von Hand im Text statt ueber ein neu geschriebenes YAML: die
    Wochendateien sind voller Kommentare, und die sollen eine Korrektur aus
    der Oberflaeche heraus ueberleben.
    """
    zeilen = text.splitlines()
    anfang = next((i for i, z in enumerate(zeilen)
                   if z.rstrip().startswith("fest:")), None)
    if anfang is None:
        raise ValueError("Die Wochendatei hat keinen Block 'fest:'")
    ende = len(zeilen)
    for i in range(anfang + 1, len(zeilen)):
        if zeilen[i] and not zeilen[i][0].isspace() and not zeilen[i].startswith("#"):
            ende = i
            break
    # Leerzeilen am Blockende gehoeren nicht mehr dazu.
    while ende > anfang + 1 and not zeilen[ende - 1].strip():
        ende -= 1

    marke = f"  {mid}:"
    stelle = next((i for i in range(anfang + 1, ende)
                   if zeilen[i].startswith(marke)), None)
    eintrag, kommentar = {}, ""
    if stelle is not None:
        roh = zeilen[stelle][len(marke):]
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
        return "\n".join(zeilen) + "\n"

    geordnet = {t: eintrag[t] for t in TAGE if t in eintrag}
    geordnet.update({k: v for k, v in eintrag.items() if k not in TAGE})
    inhalt = ", ".join(f"{k}: {v}" for k, v in geordnet.items())
    zeile = f"{marke} {{{inhalt}}}{kommentar}"
    if stelle is None:
        # Hinter den letzten echten Eintrag, sonst gleich unter 'fest:'.
        nach = anfang
        for i in range(anfang + 1, ende):
            if zeilen[i].startswith("  ") and not zeilen[i].lstrip().startswith("#"):
                nach = i
        zeilen.insert(nach + 1, zeile)
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
        antwort["kopf"] = {"von": vorgabe.datum_von, "bis": vorgabe.datum_bis,
                           "filiale": vorgabe.filiale, "modus": vorgabe.modus,
                           "pause_h": stamm.bedarf.pause_h,
                           "budget": round(bewerter.gesamtbudget())}
        antwort["mitarbeiter"] = [
            {"id": mid, "name": m.name,
             "schichten": {t: [s.id for s in _optionen(stamm, mid, t, vorgabe) if s]
                           for t in TAGE}}
            for mid, m in stamm.mitarbeiter.items() if m.im_plan]
        plan = self.ausgabe / f"{name}.json"
        if plan.exists():
            antwort["plan"] = json.loads(plan.read_text(encoding="utf-8"))
            antwort["befunde"] = self._befunde(name)
        return antwort

    def _befunde(self, name: str) -> list[dict] | None:
        """Befunde zum gespeicherten Plan.

        Der Lauf aus der Oberflaeche legt sie als Datei ab; stammt der Plan
        aus der Kommandozeile, werden sie hier nachgerechnet - sonst stuende
        ein fremder Plan ohne Bewertung da.
        """
        datei = self.ausgabe / f"{name}-befunde.json"
        if datei.exists():
            return json.loads(datei.read_text(encoding="utf-8"))
        from .cli import _plan_aus_json
        from .bewertung import pruefen
        quelle = self.ausgabe / f"{name}.json"
        if not quelle.exists():
            return None
        vorgabe = lade_wochenvorgabe(self.pfad(name))
        stamm = mit_aushilfen(self.stammdaten(), vorgabe)
        bew = pruefen(_plan_aus_json(quelle, stamm), stamm, vorgabe,
                      self.vorwochen(bis=name))
        return [{"regel": b.regel, "punkte": round(b.punkte), "text": b.text,
                 "schwere": b.schwere} for b in bew.befunde if b.text]

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
        """Eine Zelle unter 'fest' eintragen oder den Eintrag loeschen.

        Das ist die Handkorrektur aus dem Plan heraus: was hier landet, steht
        anschliessend als harte Vorgabe in der Wochendatei und bleibt beim
        naechsten Rechnen stehen.
        """
        if tag not in TAGE:
            raise ValueError(f"unbekannter Tag: {tag}")
        pfad = self.pfad(name)
        neu = _fest_setzen(pfad.read_text(encoding="utf-8"), mid, tag, wert)
        return self.speichern(name, neu) | {"yaml": neu}

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
                json.dumps(befunde, ensure_ascii=False, indent=2), encoding="utf-8")
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
                 ".pdf": "application/pdf"}
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
