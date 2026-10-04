"""Erzeugt das Programmsymbol als PNG-Satz und als .ico.

Ohne Fremdpakete: die Formen sind Rechtecke mit runden Ecken, die hier direkt
mit Kantenglaettung in einen Puffer gezeichnet und als PNG geschrieben werden.
Ein Browser oder eine Bildbibliothek waere dafuer zu viel verlangt - das
Werkzeug soll sich ueberall nachbauen lassen, wo Python laeuft.

    python werkzeug/symbol_bauen.py

schreibt schichtplan/web/bild/symbol-<n>.png und symbol.ico.
"""
from __future__ import annotations

import pathlib
import struct
import zlib

ZIEL = pathlib.Path(__file__).resolve().parent.parent / "schichtplan/web/bild"
GROESSEN = (16, 24, 32, 48, 64, 128, 256)
KANTE = 4                      # Supersampling je Achse

ROT_OBEN = (158, 43, 43)
ROT_UNTEN = (122, 29, 29)
PAPIER = (251, 246, 241)
KOPF = (232, 213, 198)
LEER = (201, 179, 162)
BELEGT = (158, 43, 43)
RING = (243, 228, 216)


class Flaeche:
    """Ein Bildpuffer mit RGBA, auf dem sich runde Rechtecke stapeln lassen."""

    def __init__(self, breite: int, hoehe: int):
        self.b, self.h = breite, hoehe
        self.punkte = [[(0, 0, 0, 0)] * breite for _ in range(hoehe)]

    def rechteck(self, x, y, b, h, radius, farbe, farbe_unten=None):
        for zy in range(max(0, int(y)), min(self.h, int(y + h) + 1)):
            for zx in range(max(0, int(x)), min(self.b, int(x + b) + 1)):
                if not (deckung := self._deckung(zx, zy, x, y, b, h, radius)):
                    continue
                if farbe_unten:
                    anteil = (zy - y) / h if h else 0
                    anteil = min(1.0, max(0.0, anteil))
                    ton = tuple(round(a + (u - a) * anteil)
                                for a, u in zip(farbe, farbe_unten))
                else:
                    ton = farbe
                self._mische(zx, zy, ton, deckung)

    def _deckung(self, zx, zy, x, y, b, h, radius) -> float:
        """Wie viel des Pixels liegt in der Form? Grob abgetastet statt exakt."""
        treffer = 0
        for i in range(KANTE):
            py = zy + (i + 0.5) / KANTE
            for j in range(KANTE):
                px = zx + (j + 0.5) / KANTE
                if x <= px <= x + b and y <= py <= y + h and \
                        self._innen(px, py, x, y, b, h, radius):
                    treffer += 1
        return treffer / (KANTE * KANTE)

    @staticmethod
    def _innen(px, py, x, y, b, h, r) -> bool:
        if r <= 0:
            return True
        for ex, ey in ((x + r, y + r), (x + b - r, y + r),
                       (x + r, y + h - r), (x + b - r, y + h - r)):
            drin_x = (px < x + r) if ex == x + r else (px > x + b - r)
            drin_y = (py < y + r) if ey == y + r else (py > y + h - r)
            if drin_x and drin_y:
                return (px - ex) ** 2 + (py - ey) ** 2 <= r * r
        return True

    def _mische(self, zx, zy, farbe, deckung):
        alt_r, alt_g, alt_b, alt_a = self.punkte[zy][zx]
        a = deckung
        neu_a = a + alt_a / 255 * (1 - a)
        if neu_a <= 0:
            return
        teil = [(f * a + alt / 255 * alt_a / 255 * (1 - a)) / neu_a
                for f, alt in zip(farbe, (alt_r, alt_g, alt_b))]
        self.punkte[zy][zx] = (round(teil[0]), round(teil[1]), round(teil[2]),
                               round(neu_a * 255))

    def als_png(self) -> bytes:
        roh = bytearray()
        for zeile in self.punkte:
            roh.append(0)                      # Filter 0: keine Vorhersage
            for r, g, b, a in zeile:
                roh += bytes((r, g, b, a))

        def block(kennung: bytes, inhalt: bytes) -> bytes:
            return (struct.pack(">I", len(inhalt)) + kennung + inhalt
                    + struct.pack(">I", zlib.crc32(kennung + inhalt) & 0xFFFFFFFF))

        kopf = struct.pack(">IIBBBBB", self.b, self.h, 8, 6, 0, 0, 0)
        return (b"\x89PNG\r\n\x1a\n" + block(b"IHDR", kopf)
                + block(b"IDAT", zlib.compress(bytes(roh), 9))
                + block(b"IEND", b""))


def zeichne(n: int) -> bytes:
    """Das Symbol in der Kantenlaenge n.

    Klein wird vereinfacht: unter 32 Pixel verschwinden die Aufhaengungen und
    die Spalten werden zu zwei breiten Balken - sonst ist in der Taskleiste
    nur noch Matsch zu sehen.
    """
    f = Flaeche(n, n)
    e = n / 512                                  # Entwurfsmass auf Zielmass
    f.rechteck(0, 0, n, n, 112 * e, ROT_OBEN, ROT_UNTEN)

    klein = n < 32
    if not klein:
        for x in (146, 332):
            f.rechteck(x * e, 54 * e, 34 * e, 74 * e, 17 * e, RING)

    blatt_y, blatt_h = (106, 330) if not klein else (128, 286)
    f.rechteck(78 * e, blatt_y * e, 356 * e, blatt_h * e, 40 * e, PAPIER)
    f.rechteck(78 * e, blatt_y * e, 356 * e, 74 * e, 40 * e, KOPF)
    f.rechteck(78 * e, (blatt_y + 44) * e, 356 * e, 30 * e, 0, KOPF)

    if klein:
        # Vier dicke Kaestchen statt fuenfzehn kleinen - bei 16 Pixeln ist
        # jedes Kaestchen sonst keine drei Pixel breit und alles verschmiert.
        for y, muster in ((248, (True, False)), (338, (False, True))):
            for i, belegt in enumerate(muster):
                f.rechteck((124 + i * 156) * e, y * e, 134 * e, 62 * e, 22 * e,
                           BELEGT if belegt else LEER)
        return f.als_png()

    spalten = [118, 178, 238, 298, 358]
    reihen = {214: (0, 0, 1, 0, 0), 276: (0, 1, 0, 1, 0), 338: (1, 0, 1, 0, 0)}
    for y, muster in reihen.items():
        for x, belegt in zip(spalten, muster):
            f.rechteck(x * e, y * e, 42 * e, 26 * e, 8 * e,
                       BELEGT if belegt else LEER)
    return f.als_png()


def als_ico(bilder: dict[int, bytes]) -> bytes:
    """ICO mit eingebetteten PNGs - so koennen alle Groessen in eine Datei."""
    anzahl = len(bilder)
    kopf = struct.pack("<HHH", 0, 1, anzahl)
    versatz = 6 + 16 * anzahl
    verzeichnis, rumpf = b"", b""
    for n in sorted(bilder):
        png = bilder[n]
        verzeichnis += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32,
                                   len(png), versatz)
        rumpf += png
        versatz += len(png)
    return kopf + verzeichnis + rumpf


def main() -> None:
    ZIEL.mkdir(parents=True, exist_ok=True)
    bilder = {}
    for n in GROESSEN:
        bilder[n] = zeichne(n)
        (ZIEL / f"symbol-{n}.png").write_bytes(bilder[n])
        print(f"  symbol-{n}.png")
    (ZIEL / "symbol.ico").write_bytes(als_ico(bilder))
    print("  symbol.ico")


if __name__ == "__main__":
    main()
