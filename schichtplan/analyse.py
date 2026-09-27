"""Mustererkennung auf den Altplaenen.

Zwei Aufgaben:
  * `bericht()`  - lesbare Statistik, um Regeln zu pruefen
  * `konfig_vorschlag()` - erzeugt schichten/mitarbeiter/bedarf-YAML aus der
    Historie. Je mehr Altplaene in daten/historie liegen, desto besser die
    Vorschlaege. Die Dateien sind danach von Hand nachschaerfbar.
"""
from __future__ import annotations

import collections
import statistics

from .historie import HistWoche, lade_historie, schicht_aus_hist
from .modelle import TAGE, TAG_LANG, zu_text, zu_zeit

NAMEN = {
    "kurka_j": "J. Kurka", "rohwer_c": "C. Rohwer", "marino_a": "A. Marino",
    "kurz_c": "C. Kurz", "sannzenbacher_n": "N. Sannzenbacher", "reich_s": "S. Reich",
    "nachtrieb_i": "I. Nachtrieb", "kurz_u": "U. Kurz", "kohl_b": "B. Kohl",
    "menzler_a": "A. Menzler", "kurz_t": "T. Kurz",
}


def _offene_wochentage(wochen: list[HistWoche], tag: str) -> list[HistWoche]:
    return [w for w in wochen if tag in w.offene_tage()]


def schichtkatalog(wochen: list[HistWoche], mindest_haeufigkeit: int = 2) -> dict:
    """Alle vorkommenden Zeitfenster mit Haeufigkeit, absteigend."""
    zaehler = collections.Counter()
    for w in wochen:
        for tage in w.plan.values():
            for z in tage.values():
                if z.verwertbar:
                    zaehler[(z.von, z.bis)] += 1
    return {
        f"{zu_text(v)}-{zu_text(b)}": {"von": zu_zeit(v), "bis": zu_zeit(b), "anzahl": n}
        for (v, b), n in zaehler.most_common() if n >= mindest_haeufigkeit
    }


def mitarbeiter_profil(wochen: list[HistWoche], ma: str) -> dict:
    schichten = collections.Counter()
    arten = collections.Counter()
    frei_je_tag = collections.Counter()
    tage_offen_je_tag = collections.Counter()
    stunden, tage, arbeitswochen = [], [], 0

    for w in wochen:
        offen = w.offene_tage()
        reihe = w.plan.get(ma)
        if reihe is None:
            continue
        h = d = 0.0
        for t in offen:
            z = reihe[t]
            arten[z.art] += 1
            tage_offen_je_tag[t] += 1
            if z.art == "frei":
                frei_je_tag[t] += 1
            if z.verwertbar:
                schichten[z.label] += 1
                h += z.stunden
                d += 1
        if d:
            arbeitswochen += 1
            stunden.append(h)
            tage.append(d)

    gesamt = sum(schichten.values())
    return {
        "name": NAMEN.get(ma, ma),
        "arbeitswochen": arbeitswochen,
        "arten": dict(arten),
        "schichten": schichten,
        "stamm_schichten": {k: round(v / gesamt, 3) for k, v in schichten.most_common()
                            if gesamt and v / gesamt >= 0.10},
        "median_stunden": round(statistics.median(stunden), 1) if stunden else 0.0,
        "median_tage": int(statistics.median(tage)) if tage else 0,
        # Ein Tag gilt als "fest frei", wenn er in (fast) jeder offenen Woche frei war.
        "feste_freie_tage": [t for t in TAGE
                             if tage_offen_je_tag[t] >= 5
                             and frei_je_tag[t] / tage_offen_je_tag[t] >= 0.85],
        "frei_quote": {t: round(frei_je_tag[t] / tage_offen_je_tag[t], 2)
                       for t in TAGE if tage_offen_je_tag[t]},
        "nie_eingeplant": gesamt == 0,
    }


def bedarfsprofil(wochen: list[HistWoche]) -> dict:
    """Kopfzahl, Frueh-/Schlussbesetzung und Mindestbesetzungskurve je Tag."""
    aus = {}
    for tag in TAGE:
        rel = _offene_wochentage(wochen, tag)
        if not rel:
            continue
        koepfe, frueh, schluss = [], [], []
        kurve = collections.defaultdict(list)
        ladenschluss = max(
            (z.bis for w in rel for r in w.plan.values() if (z := r[tag]).verwertbar),
            default=0)
        ladenoeffnung = min(
            (z.von for w in rel for r in w.plan.values() if (z := r[tag]).verwertbar),
            default=0)
        for w in rel:
            zellen = [r[tag] for r in w.plan.values() if r[tag].verwertbar]
            koepfe.append(len(zellen))
            frueh.append(sum(1 for z in zellen if z.von <= 14))          # <= 07:00
            schluss.append(sum(1 for z in zellen if z.bis >= ladenschluss))
            besetzt = collections.Counter()
            for z in zellen:
                for s in range(z.von, z.bis):
                    besetzt[s] += 1
            for s in range(ladenoeffnung, ladenschluss):
                kurve[s].append(besetzt[s])
        aus[tag] = {
            "oeffnung": (zu_zeit(ladenoeffnung), zu_zeit(ladenschluss)),
            "kopfzahl": int(statistics.median(koepfe)),
            "kopfzahl_spanne": (min(koepfe), max(koepfe)),
            "frueh_min": min(frueh),
            "schluss_min": min(schluss),
            "min_kurve": {s: min(v) for s, v in sorted(kurve.items())},
        }
    return aus


def _fenster(min_kurve: dict[int, int]) -> list[dict]:
    """Benachbarte Slots mit gleichem Minimum zu Zeitfenstern zusammenfassen."""
    out: list[dict] = []
    for slot, m in sorted(min_kurve.items()):
        if out and out[-1]["_bis"] == slot and out[-1]["min"] == m:
            out[-1]["_bis"] = slot + 1
        else:
            out.append({"_von": slot, "_bis": slot + 1, "min": m})
    return [{"von": zu_zeit(f["_von"]), "bis": zu_zeit(f["_bis"]), "min": f["min"]}
            for f in out if f["min"] > 0]


def konfig_vorschlag(wochen: list[HistWoche]) -> dict[str, dict]:
    kat = schichtkatalog(wochen)
    schichten = {}
    for sid, info in kat.items():
        von = info["von"]
        kategorie = "frueh" if von <= "07:00" else ("spaet" if von >= "11:00" else "mittel")
        schichten[sid] = {"von": info["von"], "bis": info["bis"], "kategorie": kategorie}

    alle_ma = {ma for w in wochen for ma in w.plan}
    mitarbeiter = {}
    for ma in sorted(alle_ma):
        p = mitarbeiter_profil(wochen, ma)
        if p["nie_eingeplant"]:
            mitarbeiter[ma] = {"name": p["name"], "im_plan": False,
                               "notiz": "in der Historie nie eingeplant"}
            continue
        erlaubt = [s for s in p["schichten"] if s in schichten]
        mitarbeiter[ma] = {
            "name": p["name"],
            "soll_stunden": p["median_stunden"],
            "soll_tage": p["median_tage"],
            "feste_freie_tage": p["feste_freie_tage"],
            "erlaubte_schichten": erlaubt,
            "stamm_schichten": {k: v for k, v in p["stamm_schichten"].items() if k in schichten},
        }

    bp = bedarfsprofil(wochen)
    bedarf = {
        "offene_tage": [t for t in TAGE if t in bp],
        "frueh_bis": "07:00",
        "oeffnung": {t: {"von": bp[t]["oeffnung"][0], "bis": bp[t]["oeffnung"][1]} for t in bp},
        "kopfzahl": {t: bp[t]["kopfzahl"] for t in bp},
        "frueh_min": {t: bp[t]["frueh_min"] for t in bp},
        "schluss_min": {t: bp[t]["schluss_min"] for t in bp},
        "besetzung_min": {t: _fenster(bp[t]["min_kurve"]) for t in bp},
    }
    return {"schichten": {"schichten": schichten},
            "mitarbeiter": {"mitarbeiter": mitarbeiter},
            "bedarf": bedarf}


def bericht(wochen: list[HistWoche] | None = None) -> str:
    wochen = wochen if wochen is not None else lade_historie()
    z = []
    z.append(f"Ausgewertete Wochen (final): {len(wochen)}")
    if wochen:
        z.append(f"Zeitraum: {wochen[0].datum_von} bis {wochen[-1].datum_von}")
    z.append("")
    z.append("== Schichtkatalog ==")
    for sid, info in schichtkatalog(wochen, 1).items():
        z.append(f"  {sid:<12} {info['anzahl']:>4}x")
    z.append("")
    z.append("== Bedarf je Tag ==")
    bp = bedarfsprofil(wochen)
    for t in TAGE:
        if t not in bp:
            continue
        b = bp[t]
        z.append(f"  {TAG_LANG[t]:<11} {b['oeffnung'][0]}-{b['oeffnung'][1]}  "
                 f"Koepfe {b['kopfzahl']} (Spanne {b['kopfzahl_spanne'][0]}-{b['kopfzahl_spanne'][1]})  "
                 f"Frueh>={b['frueh_min']}  Schluss>={b['schluss_min']}")
    z.append("")
    z.append("== Mitarbeiter ==")
    for ma in sorted({m for w in wochen for m in w.plan}):
        p = mitarbeiter_profil(wochen, ma)
        if p["nie_eingeplant"]:
            z.append(f"  {p['name']:<18} nie eingeplant ({p['arten']})")
            continue
        stamm = ", ".join(f"{k} {v:.0%}" for k, v in p["stamm_schichten"].items())
        z.append(f"  {p['name']:<18} {p['median_stunden']:>5.1f} h / {p['median_tage']} Tage   "
                 f"fest frei: {p['feste_freie_tage'] or '-'}")
        z.append(f"  {'':<18} Stammschichten: {stamm}")
        z.append(f"  {'':<18} Frei-Quote: " +
                 " ".join(f"{t}:{p['frei_quote'].get(t, 0):.0%}" for t in TAGE))
    return "\n".join(z)
