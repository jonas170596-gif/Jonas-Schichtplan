"""Tests ohne externe Abhaengigkeiten: python3 -m pytest tests  (oder unittest)."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from schichtplan.backtest import plan_aus_historie, vorgabe_aus_historie
from schichtplan.bewertung import Bewerter, pruefen
from schichtplan.generator import erzeuge, grundgeruest
from schichtplan.historie import lade_historie
from schichtplan.konfig import lade_stammdaten, lade_wochenvorgabe
from schichtplan.modelle import TAGE, zu_index, zu_text
from schichtplan import export

WURZEL = pathlib.Path(__file__).resolve().parents[1]


class TestZeit(unittest.TestCase):
    def test_hin_und_rueck(self):
        for s in ("06:00", "13:30", "20:00"):
            self.assertEqual(zu_index(s) % 1, 0)
        self.assertEqual(zu_index("13:30"), 27)
        self.assertEqual(zu_text(27), "13:30")
        self.assertEqual(zu_text(28), "14")

    def test_halbe_stunden_pflicht(self):
        with self.assertRaises(ValueError):
            zu_index("06:15")


class TestHistorie(unittest.TestCase):
    def setUp(self):
        self.wochen = lade_historie(WURZEL / "daten/historie")

    def test_14_finale_wochen(self):
        self.assertEqual(len(self.wochen), 14)

    def test_jede_zelle_belegt(self):
        for w in self.wochen:
            for mid, reihe in w.plan.items():
                self.assertEqual(set(reihe), set(TAGE), f"{w.woche}/{mid}")

    def test_entwuerfe_werden_ausgeblendet(self):
        alle = lade_historie(WURZEL / "daten/historie", nur_final=False)
        self.assertEqual(len(alle), 16)


class TestKonfig(unittest.TestCase):
    def setUp(self):
        self.stamm = lade_stammdaten(WURZEL / "konfig")

    def test_stammschichten_sind_erlaubt(self):
        for m in self.stamm.mitarbeiter.values():
            for sid in m.stamm_schichten:
                self.assertIn(sid, m.erlaubte_schichten, m.id)

    def test_samstagsschichten_enden_zur_ladenschlusszeit(self):
        schluss = self.stamm.bedarf.oeffnung["sa"][1]
        for s in self.stamm.schichten.values():
            if "sa" in s.tage:
                self.assertLessEqual(s.bis, schluss, s.id)

    def test_bedarf_deckt_alle_offenen_tage(self):
        for t in self.stamm.bedarf.offene_tage:
            self.assertIn(t, self.stamm.bedarf.kopfzahl)
            self.assertIn(t, self.stamm.bedarf.oeffnung)


class TestGenerator(unittest.TestCase):
    def setUp(self):
        self.stamm = lade_stammdaten(WURZEL / "konfig")
        self.vorgabe = lade_wochenvorgabe(WURZEL / "wochen/2025-KW42.yaml")

    def test_harte_vorgaben_bleiben_stehen(self):
        erg = erzeuge(self.stamm, self.vorgabe, iterationen=800, neustarts=1, seed=7)
        for mid, tage in self.vorgabe.abwesend.items():
            for t, art in tage.items():
                self.assertEqual(erg.plan.zellen[mid][t].art, art)

    def test_neue_feste_freie_tage_greifen(self):
        erwartet = {"rohwer_c": ["mi"], "marino_a": ["mo"],
                    "reich_s": ["mo", "mi"], "kurz_u": ["di"],
                    "kurz_c": ["di", "fr", "sa"], "kurka_j": []}
        for mid, tage in erwartet.items():
            self.assertEqual(self.stamm.mitarbeiter[mid].feste_freie_tage, tage, mid)

    def test_feste_freie_tage_bleiben_frei(self):
        erg = erzeuge(self.stamm, self.vorgabe, iterationen=800, neustarts=1, seed=7)
        for mid, m in self.stamm.mitarbeiter.items():
            for t in m.feste_freie_tage:
                self.assertFalse(erg.plan.zellen[mid][t].arbeitet, f"{mid}/{t}")

    def test_nur_erlaubte_schichten_am_erlaubten_tag(self):
        erg = erzeuge(self.stamm, self.vorgabe, iterationen=2000, neustarts=1, seed=3)
        for mid, reihe in erg.plan.zellen.items():
            m = self.stamm.mitarbeiter[mid]
            for t, z in reihe.items():
                if z.arbeitet:
                    self.assertIn(z.schicht.id, m.erlaubte_schichten)
                    self.assertIn(t, z.schicht.tage)

    def test_nicht_eingeplante_bleiben_leer(self):
        erg = erzeuge(self.stamm, self.vorgabe, iterationen=500, neustarts=1, seed=1)
        for t in erg.plan.offene_tage:
            self.assertEqual(erg.plan.zellen["kurz_t"][t].art, "nicht_im_plan")

    def test_suche_verbessert_den_greedy_start(self):
        erg = erzeuge(self.stamm, self.vorgabe, iterationen=6000, neustarts=2, seed=5)
        self.assertLess(erg.bewertung.punkte, erg.startpunkte)

    def test_geschlossener_tag_wird_nicht_belegt(self):
        self.vorgabe.geschlossen = ["sa"]
        erg = erzeuge(self.stamm, self.vorgabe, iterationen=500, neustarts=1, seed=1)
        self.assertNotIn("sa", erg.plan.offene_tage)
        for reihe in erg.plan.zellen.values():
            self.assertFalse(reihe["sa"].arbeitet)


class TestBewertung(unittest.TestCase):
    def setUp(self):
        self.stamm = lade_stammdaten(WURZEL / "konfig")
        self.vorgabe = lade_wochenvorgabe(WURZEL / "wochen/2025-KW42.yaml")

    def test_leerer_plan_wird_bestraft(self):
        leer = grundgeruest(self.stamm, self.vorgabe)
        self.assertGreater(pruefen(leer, self.stamm, self.vorgabe).punkte, 1000)

    def test_urlaub_kuerzt_das_stundensoll(self):
        b = Bewerter(self.stamm, self.vorgabe)
        soll_h, soll_t = b._ziel("marino_a")       # ganze Woche Urlaub
        self.assertEqual(soll_t, 0)
        self.assertEqual(soll_h, 0.0)
        soll_h, _ = b._ziel("kurka_j")
        self.assertAlmostEqual(soll_h, 40.0)

    def _setze(self, plan, mid, tag, sid):
        plan.zellen[mid][tag].art = "schicht"
        plan.zellen[mid][tag].schicht = self.stamm.schichten[sid]

    def test_kurzer_wechsel_wird_erkannt(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        self._setze(plan, "kurka_j", "mo", "11-20")
        self._setze(plan, "kurka_j", "di", "6-14")
        regeln = {b.regel for b in pruefen(plan, self.stamm, self.vorgabe).befunde}
        self.assertIn("wechsel", regeln)

    def test_zweiter_wechsel_kostet_deutlich_mehr(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        for tag, sid in (("mo", "11-20"), ("di", "6-14"),
                         ("mi", "11-20"), ("do", "6-14")):
            self._setze(plan, "kurka_j", tag, sid)
        befunde = {b.regel: b.punkte
                   for b in pruefen(plan, self.stamm, self.vorgabe).befunde}
        self.assertIn("wechsel_ueber_limit", befunde)
        self.assertGreater(befunde["wechsel_ueber_limit"], befunde["wechsel"])

    def test_frueh_anker_fehlt(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        self._setze(plan, "kohl_b", "mo", "6-13:30")     # frueh, aber kein Anker
        texte = [b.text for b in pruefen(plan, self.stamm, self.vorgabe).befunde
                 if b.regel == "gruppenbesetzung"]
        self.assertTrue(any("Montag" in x for x in texte), texte)

    def test_frueh_anker_erfuellt(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        self._setze(plan, "rohwer_c", "mo", "6-14")
        montag = [b for b in pruefen(plan, self.stamm, self.vorgabe).befunde
                  if b.regel == "gruppenbesetzung" and "Montag" in b.text]
        self.assertEqual(montag, [])

    def test_kohl_und_reich_nicht_zusammen_spaet(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        self._setze(plan, "kohl_b", "do", "12-20")
        self._setze(plan, "reich_s", "do", "14-20")
        regeln = {b.regel for b in pruefen(plan, self.stamm, self.vorgabe).befunde}
        self.assertIn("unvertraeglich", regeln)

    def test_kohl_und_reich_zusammen_frueh_ist_erlaubt(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        self._setze(plan, "kohl_b", "do", "6-13:30")
        self._setze(plan, "reich_s", "do", "6-14")
        regeln = {b.regel for b in pruefen(plan, self.stamm, self.vorgabe).befunde}
        self.assertNotIn("unvertraeglich", regeln)

    def test_termin_verlangt_passendes_schichtende(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        self._setze(plan, "kurka_j", "di", "6-14")
        regeln = {b.regel for b in pruefen(plan, self.stamm, self.vorgabe).befunde}
        self.assertIn("termin", regeln)
        self._setze(plan, "kurka_j", "di", "6-13:30")
        regeln = {b.regel for b in pruefen(plan, self.stamm, self.vorgabe).befunde}
        self.assertNotIn("termin", regeln)

    def test_getrennte_freie_tage_werden_bemaengelt(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        for tag in ("mo", "mi", "fr", "sa"):          # frei: di und do -> zwei Bloecke
            self._setze(plan, "kohl_b", tag, "12-20" if tag != "sa" else "10-18")
        regeln = {b.regel for b in pruefen(plan, self.stamm, self.vorgabe).befunde}
        self.assertIn("freie_tage_zusammenhaengend", regeln)

    def test_azubistunden_zaehlen_nicht_gegen_das_budget(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        b = Bewerter(self.stamm, self.vorgabe)
        vorher = b.gesamtstunden(plan)
        self._setze(plan, "menzler_a", "mo", "8-16")
        self.assertEqual(b.gesamtstunden(plan), vorher)
        self._setze(plan, "kurka_j", "mo", "6-14")
        self.assertEqual(b.gesamtstunden(plan), vorher + 8)

    def test_budget_sinkt_bei_urlaub(self):
        b = Bewerter(self.stamm, self.vorgabe)          # Marino ganze Woche Urlaub
        self.assertAlmostEqual(b.gesamtbudget(),
                               self.stamm.bedarf.wochenstunden_gesamt - 40)

    def test_reserve_wird_je_stunde_bestraft(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        leer = pruefen(plan, self.stamm, self.vorgabe).punkte
        self._setze(plan, "kurz_u", "mo", "14-20")
        regeln = {b.regel for b in pruefen(plan, self.stamm, self.vorgabe).befunde}
        self.assertIn("sparsam_einsetzen", regeln)


class TestBacktest(unittest.TestCase):
    def test_vorgabe_uebernimmt_abwesenheiten(self):
        stamm = lade_stammdaten(WURZEL / "konfig")
        w = next(w for w in lade_historie(WURZEL / "daten/historie")
                 if w.woche == "2025-KW41")
        v = vorgabe_aus_historie(w, stamm)
        self.assertEqual(v.abwesend["reich_s"]["mo"], "urlaub")
        self.assertEqual(v.abwesend["menzler_a"]["do"], "schule")

    def test_feiertag_schliesst_den_tag(self):
        stamm = lade_stammdaten(WURZEL / "konfig")
        w = next(w for w in lade_historie(WURZEL / "daten/historie")
                 if w.woche == "2025-KW40")
        self.assertEqual(vorgabe_aus_historie(w, stamm).geschlossen, ["sa"])

    def test_original_laesst_sich_bewerten(self):
        stamm = lade_stammdaten(WURZEL / "konfig")
        for w in lade_historie(WURZEL / "daten/historie"):
            plan = plan_aus_historie(w, stamm)
            v = vorgabe_aus_historie(w, stamm)
            self.assertGreaterEqual(Bewerter(stamm, v).bewerte(plan).punkte, 0)


class TestExport(unittest.TestCase):
    def setUp(self):
        self.stamm = lade_stammdaten(WURZEL / "konfig")
        self.vorgabe = lade_wochenvorgabe(WURZEL / "wochen/2025-KW42.yaml")
        self.plan = erzeuge(self.stamm, self.vorgabe, iterationen=1500,
                            neustarts=1, seed=11).plan

    def test_html_enthaelt_alle_mitarbeiter(self):
        h = export.als_html(self.plan, self.stamm)
        for m in self.stamm.mitarbeiter.values():
            self.assertIn(m.name, h)

    def test_e2n_csv_eine_zeile_je_schicht(self):
        text = export.als_e2n_csv(self.plan, self.stamm)
        zeilen = [z for z in text.strip().splitlines()[1:] if z]
        erwartet = sum(1 for r in self.plan.zellen.values()
                       for t in self.plan.offene_tage if r[t].arbeitet)
        self.assertEqual(len(zeilen), erwartet)
        self.assertIn("13.10.2025", text)

    def test_json_ist_wieder_einlesbar(self):
        import json
        doc = json.loads(export.als_json(self.plan, self.stamm))
        self.assertEqual(doc["woche"], "2025-KW42")
        self.assertEqual(set(doc["plan"]), set(self.plan.zellen))

    def test_abwesenheits_csv_listet_urlaub(self):
        text = export.als_abwesenheits_csv(self.plan, self.stamm)
        self.assertIn("urlaub", text)
        self.assertIn("A. Marino", text)


if __name__ == "__main__":
    unittest.main()
