"""Tests ohne externe Abhaengigkeiten: python3 -m pytest tests  (oder unittest)."""
import datetime
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from schichtplan.backtest import plan_aus_historie, vorgabe_aus_historie
from schichtplan.bewertung import Bewerter, pruefen
from schichtplan.feiertage import Kalender, feiertage_bw, ostersonntag
from schichtplan.generator import erzeuge, grundgeruest
from schichtplan.historie import kalenderabgleich, lade_historie
from schichtplan.konfig import (lade_schulplaene, lade_stammdaten,
                                lade_wochenvorgabe)
from schichtplan.modelle import TAGE, TAG_LANG, zu_index, zu_text
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

    def test_finale_wochen(self):
        self.assertEqual(len(self.wochen), 14)
        self.assertIn("2026-KW40", [w.woche for w in self.wochen])

    def test_datum_ist_der_echte_montag(self):
        for w in lade_historie(WURZEL / "daten/historie", nur_final=False):
            jahr, kw = w.woche.replace("-v1", "").split("-KW")
            self.assertEqual(jahr, "2026", w.woche)
            montag = datetime.date.fromisocalendar(int(jahr), int(kw), 1)
            self.assertEqual(w.datum_von, montag.isoformat(), w.woche)

    def test_feiertagsspalten_passen_zum_kalender(self):
        self.assertEqual(kalenderabgleich(self.wochen), [])

    def test_jede_zelle_belegt(self):
        for w in self.wochen:
            for mid, reihe in w.plan.items():
                self.assertEqual(set(reihe), set(TAGE), f"{w.woche}/{mid}")

    def test_entwuerfe_werden_ausgeblendet(self):
        alle = lade_historie(WURZEL / "daten/historie", nur_final=False)
        self.assertEqual(len(alle), 16)


class TestWochendatum(unittest.TestCase):
    """Ein falsch datierter Wochenplan verschiebt alle Feiertagsregeln."""

    def test_falsches_datum_wird_abgelehnt(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False,
                                         encoding="utf-8") as f:
            f.write("woche: 2026-KW40\ndatum_von: 2026-09-27\n")   # Sonntag
            pfad = f.name
        with self.assertRaises(ValueError) as fehler:
            lade_wochenvorgabe(pfad)
        self.assertIn("2026-09-28", str(fehler.exception))
        pathlib.Path(pfad).unlink()

    def test_richtiges_datum_geht_durch(self):
        v = lade_wochenvorgabe(WURZEL / "wochen/2026-KW40.yaml")
        self.assertEqual(v.datum_von, "2026-09-28")


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
        self.vorgabe = lade_wochenvorgabe(WURZEL / "wochen/2026-KW42.yaml")

    def test_harte_vorgaben_bleiben_stehen(self):
        erg = erzeuge(self.stamm, self.vorgabe, iterationen=800, neustarts=1, seed=7)
        for mid, tage in self.vorgabe.abwesend.items():
            for t, art in tage.items():
                self.assertEqual(erg.plan.zellen[mid][t].art, art)

    def test_neue_feste_freie_tage_greifen(self):
        erwartet = {"rohwer_c": ["mi"], "marino_a": ["mo"],
                    "reich_s": ["mo", "mi"], "kurz_u": ["di"],
                    "kurz_c": ["di"], "kurka_j": []}
        for mid, tage in erwartet.items():
            self.assertEqual(self.stamm.mitarbeiter[mid].feste_freie_tage, tage, mid)
        self.assertEqual(self.stamm.mitarbeiter["kurz_c"].bevorzugte_freie_tage,
                         ["fr", "sa"])
        self.assertEqual(self.stamm.mitarbeiter["sannzenbacher_n"].bevorzugte_freie_tage,
                         ["mi", "do"])

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
        self.vorgabe = lade_wochenvorgabe(WURZEL / "wochen/2026-KW42.yaml")

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

    def _faehigkeitsluecken(self, plan, tag):
        return [b.text for b in pruefen(plan, self.stamm, self.vorgabe).befunde
                if b.regel == "faehigkeit" and TAG_LANG[tag] in b.text]

    def test_nur_wurst_am_abend_meldet_fehlendes_fleisch(self):
        """Kohl und Reich koennen beide nur w - stehen sie allein spaet da,
        fehlt Fleisch. Genau daraus folgt 'die beiden nicht zusammen'."""
        plan = grundgeruest(self.stamm, self.vorgabe)
        self._setze(plan, "kohl_b", "do", "12-20")
        self._setze(plan, "reich_s", "do", "14-20")
        self.assertTrue(any("Fleisch" in x for x in self._faehigkeitsluecken(plan, "do")))

    def test_mit_fleischkraft_daneben_ist_es_in_ordnung(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        self._setze(plan, "kohl_b", "do", "12-20")
        self._setze(plan, "reich_s", "do", "14-20")
        self._setze(plan, "nachtrieb_i", "do", "6-14")       # f ab 6
        self._setze(plan, "sannzenbacher_n", "do", "12-20")  # f bis 20
        self.assertFalse(any("Fleisch" in x for x in self._faehigkeitsluecken(plan, "do")))

    def test_ofen_muss_morgens_da_sein(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        self._setze(plan, "nachtrieb_i", "do", "6-14")       # fw, kein o
        self.assertTrue(any("Ofen" in x for x in self._faehigkeitsluecken(plan, "do")))
        self._setze(plan, "kurka_j", "do", "6-14")           # fwo
        self.assertFalse(any("Ofen" in x for x in self._faehigkeitsluecken(plan, "do")))

    def test_menzler_darf_spaet_arbeiten(self):
        """Keine feste Obergrenze mehr - Spaet ist moeglich, wenn noetig."""
        self.assertIsNone(self.stamm.mitarbeiter["menzler_a"].max_spaet_pro_woche)
        plan = grundgeruest(self.stamm, self.vorgabe)
        for tag in ("mo", "di", "mi"):
            self._setze(plan, "menzler_a", tag, "11-20")
        regeln = {b.regel for b in pruefen(plan, self.stamm, self.vorgabe).befunde}
        self.assertNotIn("zu_viel_spaet", regeln)

    def test_wechselregel_gilt_auch_fuer_den_springer(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        self._setze(plan, "menzler_a", "mo", "11-20")
        self._setze(plan, "menzler_a", "di", "6-14")
        texte = [b.text for b in pruefen(plan, self.stamm, self.vorgabe).befunde
                 if b.regel == "wechsel"]
        self.assertTrue(any("A. Menzler" in x for x in texte), texte)

    def test_zweiter_wechsel_kostet_den_springer_auch_mehr(self):
        # Wechsel zaehlen nur zwischen aufeinanderfolgenden Tagen, deshalb
        # Mo-Do durchgehend belegen (der Schultag am Do wird ueberschrieben).
        plan = grundgeruest(self.stamm, self.vorgabe)
        for tag, sid in (("mo", "11-20"), ("di", "6-14"),
                         ("mi", "11-20"), ("do", "6-14")):
            self._setze(plan, "menzler_a", tag, sid)
        befunde = {b.regel: b.punkte
                   for b in pruefen(plan, self.stamm, self.vorgabe).befunde}
        self.assertIn("wechsel_ueber_limit", befunde)
        self.assertGreater(befunde["wechsel_ueber_limit"], befunde["wechsel"])

    def test_kurka_meidet_spaetschichten(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        self._setze(plan, "kurka_j", "mo", "11-20")
        regeln = {b.regel for b in pruefen(plan, self.stamm, self.vorgabe).befunde}
        self.assertIn("vermiedene_schicht", regeln)

    def test_bevorzugter_freier_tag_wird_bemaengelt(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        self._setze(plan, "kurz_c", "fr", "8-14")
        texte = [b.text for b in pruefen(plan, self.stamm, self.vorgabe).befunde
                 if b.regel == "bevorzugter_freier_tag"]
        self.assertTrue(any("C. Kurz" in x and "Freitag" in x for x in texte), texte)

    def test_rohwer_fr_sa_im_wechsel(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        self._setze(plan, "rohwer_c", "fr", "11-20")     # spaet
        self._setze(plan, "rohwer_c", "sa", "11-18")     # ebenfalls spaet
        regeln = {b.regel for b in pruefen(plan, self.stamm, self.vorgabe).befunde}
        self.assertIn("schicht_verteilung", regeln)
        self._setze(plan, "rohwer_c", "sa", "6-14")      # jetzt frueh
        regeln = {b.regel for b in pruefen(plan, self.stamm, self.vorgabe).befunde}
        self.assertNotIn("schicht_verteilung", regeln)

    def test_rohwer_will_mo_bis_do_frueh(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        self._setze(plan, "rohwer_c", "do", "11-20")
        regeln = {b.regel for b in pruefen(plan, self.stamm, self.vorgabe).befunde}
        self.assertIn("schichtwunsch", regeln)
        self._setze(plan, "rohwer_c", "do", "6-14")
        regeln = {b.regel for b in pruefen(plan, self.stamm, self.vorgabe).befunde}
        self.assertNotIn("schichtwunsch", regeln)

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


class TestGeschlosseneTage(unittest.TestCase):
    """Ein geschlossener Tag mitten in der Woche darf Abstaende nicht verkuerzen.

    Die Vorgabe wird hier kuenstlich gebaut (Freitag zu), damit der Test nicht
    davon abhaengt, wo im Kalender gerade ein Feiertag liegt."""

    def setUp(self):
        self.stamm = lade_stammdaten(WURZEL / "konfig")
        self.vorgabe = lade_wochenvorgabe(WURZEL / "wochen/2026-KW42.yaml")
        self.vorgabe.geschlossen = ["fr"]
        self.vorgabe.abwesend = {}
        self.vorgabe.termine = []
        self.plan = grundgeruest(self.stamm, self.vorgabe)

    def _setze(self, mid, tag, sid):
        self.plan.zellen[mid][tag].art = "schicht"
        self.plan.zellen[mid][tag].schicht = self.stamm.schichten[sid]

    def test_freitag_ist_geschlossen(self):
        self.assertNotIn("fr", self.plan.offene_tage)

    def test_spaet_do_frueh_sa_ist_kein_kurzer_wechsel(self):
        self._setze("nachtrieb_i", "do", "14-20")
        self._setze("nachtrieb_i", "sa", "6-14")
        texte = [b.text for b in pruefen(self.plan, self.stamm, self.vorgabe).befunde
                 if b.regel in ("wechsel", "ruhezeit_verletzung")]
        self.assertFalse(any("I. Nachtrieb" in x for x in texte), texte)

    def test_spaet_mi_frueh_do_bleibt_ein_kurzer_wechsel(self):
        self._setze("nachtrieb_i", "mi", "14-20")
        self._setze("nachtrieb_i", "do", "6-14")
        texte = [b.text for b in pruefen(self.plan, self.stamm, self.vorgabe).befunde
                 if b.regel == "wechsel"]
        self.assertTrue(any("I. Nachtrieb" in x for x in texte), texte)

    def test_geschlossener_tag_unterbricht_die_serie(self):
        for tag in ("mo", "di", "mi", "do", "sa"):
            self._setze("kurka_j", tag, "6-14")
        texte = [b.text for b in pruefen(self.plan, self.stamm, self.vorgabe).befunde
                 if b.regel == "tage_in_folge"]
        self.assertFalse(any("J. Kurka" in x for x in texte), texte)

    def test_freie_tage_um_einen_feiertag_gelten_als_zusammenhaengend(self):
        for tag in ("mo", "di", "mi"):
            self._setze("kohl_b", tag, "12-20")
        # frei sind Do und Sa, dazwischen nur der geschlossene Freitag
        texte = [b.text for b in pruefen(self.plan, self.stamm, self.vorgabe).befunde
                 if b.regel == "freie_tage_zusammenhaengend"]
        self.assertFalse(any("B. Kohl" in x for x in texte), texte)


class TestFeiertage(unittest.TestCase):
    def setUp(self):
        self.stamm = lade_stammdaten(WURZEL / "konfig")
        self.vorgabe = lade_wochenvorgabe(WURZEL / "wochen/2026-KW40.yaml")

    def test_ostern_stimmt(self):
        self.assertEqual(ostersonntag(2025), datetime.date(2025, 4, 20))
        self.assertEqual(ostersonntag(2026), datetime.date(2026, 4, 5))
        self.assertEqual(ostersonntag(2027), datetime.date(2027, 3, 28))

    def test_bw_feiertage(self):
        ft = feiertage_bw(2026)
        self.assertEqual(ft[datetime.date(2026, 4, 3)], "Karfreitag")
        self.assertEqual(ft[datetime.date(2026, 6, 4)], "Fronleichnam")
        self.assertEqual(ft[datetime.date(2026, 10, 3)], "Tag der Deutschen Einheit")
        self.assertIn(datetime.date(2026, 1, 6), ft)        # nur in BW und BY
        self.assertNotIn(datetime.date(2026, 4, 5), ft)     # Ostersonntag, ohnehin zu

    def test_03_10_wandert_durch_die_wochentage(self):
        """Der Ausloeser fuer die Jahresverwechslung: 2025 Freitag, 2026 Samstag."""
        self.assertEqual(datetime.date(2025, 10, 3).strftime("%A"), "Friday")
        self.assertEqual(datetime.date(2026, 10, 3).strftime("%A"), "Saturday")

    def test_samstag_vor_feiertagsmontag_zaehlt_als_vortag(self):
        k = Kalender()
        # Pfingstmontag 2026 ist der 25.05., der Samstag davor der 23.05.
        self.assertEqual(k.vor_feiertag(datetime.date(2026, 5, 23)), "Pfingstmontag")
        self.assertEqual(k.nach_feiertag(datetime.date(2026, 5, 26)), "Pfingstmontag")

    def test_weihnachtswoche_wird_erkannt(self):
        k = Kalender()
        self.assertIsNotNone(k.weihnachtswoche(datetime.date(2026, 12, 21)))
        self.assertIsNone(k.weihnachtswoche(datetime.date(2026, 10, 12)))

    def test_umfeld_hebt_die_mindestwerte(self):
        b = Bewerter(self.stamm, self.vorgabe)   # Feiertag ist Samstag 03.10.2026
        self.assertEqual(b.mindestwert("fr", "schluss_min", 2)[0], 4)   # vor Feiertag
        self.assertEqual(b.mindestwert("mo", "schluss_min", 2)[0], 2)   # unberuehrt
        self.assertNotIn("sa", b.tage)                                  # Feiertag

    def test_generierter_plan_haelt_die_feiertagsvorgaben(self):
        erg = erzeuge(self.stamm, self.vorgabe, iterationen=30000, seed=4)
        harte = [b.text for b in erg.bewertung.befunde
                 if b.regel in ("schluss_besetzung", "frueh_besetzung")]
        self.assertEqual(harte, [])


class TestAusgleich(unittest.TestCase):
    def setUp(self):
        self.stamm = lade_stammdaten(WURZEL / "konfig")
        self.vorgabe = lade_wochenvorgabe(WURZEL / "wochen/2026-KW42.yaml")
        self.historie = lade_historie(WURZEL / "daten/historie")

    def test_fenster_umfasst_vier_wochen(self):
        b = Bewerter(self.stamm, self.vorgabe, self.historie)
        plan = grundgeruest(self.stamm, self.vorgabe)
        _, _, wochen = b.frueh_spaet_bilanz(plan, "reich_s")
        self.assertEqual(wochen, self.stamm.regeln.ausgleich_fenster_wochen)

    def test_bilanz_zaehlt_die_geplante_woche_mit(self):
        b = Bewerter(self.stamm, self.vorgabe, self.historie)
        plan = grundgeruest(self.stamm, self.vorgabe)
        vorher = b.frueh_spaet_bilanz(plan, "reich_s")
        plan.zellen["reich_s"]["di"].art = "schicht"
        plan.zellen["reich_s"]["di"].schicht = self.stamm.schichten["14-20"]
        nachher = b.frueh_spaet_bilanz(plan, "reich_s")
        self.assertEqual(nachher[1], vorher[1] + 1)

    def test_kurka_nimmt_nicht_teil(self):
        self.assertFalse(self.stamm.mitarbeiter["kurka_j"].frueh_spaet_ausgleich)
        self.assertFalse(self.stamm.mitarbeiter["kurz_u"].frueh_spaet_ausgleich)

    def test_einseitige_bilanz_wird_bestraft(self):
        """Lauter Spaetschichten muessen die Bilanz messbar verschieben."""
        b = Bewerter(self.stamm, self.vorgabe, self.historie)
        leer = grundgeruest(self.stamm, self.vorgabe)
        vorher = b.frueh_spaet_bilanz(leer, "reich_s")
        voll = grundgeruest(self.stamm, self.vorgabe)
        for tag in ("di", "do", "fr", "sa"):
            voll.zellen["reich_s"][tag].art = "schicht"
            voll.zellen["reich_s"][tag].schicht = self.stamm.schichten[
                "14-20" if tag != "sa" else "12-18"]
        nachher = b.frueh_spaet_bilanz(voll, "reich_s")
        self.assertEqual(nachher[1], vorher[1] + 4)
        self.assertEqual(nachher[0], vorher[0])          # keine Fruehschicht dazu

    def test_ausgleich_straft_erst_jenseits_der_toleranz(self):
        b = Bewerter(self.stamm, self.vorgabe, self.historie)
        plan = grundgeruest(self.stamm, self.vorgabe)
        for tag in ("di", "do", "fr", "sa"):
            plan.zellen["reich_s"][tag].art = "schicht"
            plan.zellen["reich_s"][tag].schicht = self.stamm.schichten[
                "14-20" if tag != "sa" else "12-18"]
        frueh, spaet, _ = b.frueh_spaet_bilanz(plan, "reich_s")
        befunde = [x for x in pruefen(plan, self.stamm, self.vorgabe,
                                      self.historie).befunde
                   if x.regel == "frueh_spaet_ausgleich" and "S. Reich" in x.text]
        if abs(frueh - spaet) > self.stamm.regeln.ausgleich_toleranz:
            self.assertTrue(befunde, f"{frueh} frueh / {spaet} spaet ohne Befund")
        else:
            self.assertFalse(befunde)


class TestTerminWechsel(unittest.TestCase):
    def setUp(self):
        self.stamm = lade_stammdaten(WURZEL / "konfig")
        self.vorgabe = lade_wochenvorgabe(WURZEL / "wochen/2026-KW42.yaml")
        self.historie = lade_historie(WURZEL / "daten/historie")

    def test_termin_ist_als_abwechselnd_konfiguriert(self):
        self.assertTrue(self.vorgabe.termine[0].abwechselnd)

    def test_letzter_halter_wird_aus_der_historie_erkannt(self):
        b = Bewerter(self.stamm, self.vorgabe, self.historie)
        # KW41: Kurka Di 6-13:30 - er war zuletzt dran
        self.assertEqual(b._letzter_terminhalter(self.vorgabe.termine[0]), "kurka_j")

    def test_wiederholung_wird_bemaengelt(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        plan.zellen["kurka_j"]["di"].art = "schicht"
        plan.zellen["kurka_j"]["di"].schicht = self.stamm.schichten["6-13:30"]
        regeln = {b.regel for b in pruefen(plan, self.stamm, self.vorgabe,
                                           self.historie).befunde}
        self.assertIn("termin_wechsel", regeln)

    def test_wechsel_auf_rohwer_ist_in_ordnung(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        plan.zellen["rohwer_c"]["di"].art = "schicht"
        plan.zellen["rohwer_c"]["di"].schicht = self.stamm.schichten["6-13:30"]
        befunde = pruefen(plan, self.stamm, self.vorgabe, self.historie).befunde
        regeln = {b.regel for b in befunde}
        self.assertNotIn("termin_wechsel", regeln)
        self.assertNotIn("termin", regeln)


class TestBacktest(unittest.TestCase):
    def test_vorgabe_uebernimmt_abwesenheiten(self):
        stamm = lade_stammdaten(WURZEL / "konfig")
        w = next(w for w in lade_historie(WURZEL / "daten/historie")
                 if w.woche == "2026-KW41")
        v = vorgabe_aus_historie(w, stamm)
        self.assertEqual(v.abwesend["reich_s"]["mo"], "urlaub")
        self.assertEqual(v.abwesend["menzler_a"]["do"], "schule")

    def test_feiertag_schliesst_den_tag(self):
        stamm = lade_stammdaten(WURZEL / "konfig")
        w = next(w for w in lade_historie(WURZEL / "daten/historie")
                 if w.woche == "2026-KW40")
        # 03.10.2026 faellt auf einen Samstag
        self.assertEqual(vorgabe_aus_historie(w, stamm).geschlossen, ["sa"])

    def test_original_laesst_sich_bewerten(self):
        stamm = lade_stammdaten(WURZEL / "konfig")
        for w in lade_historie(WURZEL / "daten/historie"):
            plan = plan_aus_historie(w, stamm)
            v = vorgabe_aus_historie(w, stamm)
            self.assertGreaterEqual(Bewerter(stamm, v).bewerte(plan).punkte, 0)


class TestHandplan(unittest.TestCase):
    """Weihnachtswoche: der Planer rechnet nicht, er prueft und exportiert."""

    def setUp(self):
        self.stamm = lade_stammdaten(WURZEL / "konfig")
        self.vorgabe = lade_wochenvorgabe(WURZEL / "wochen/2026-KW52.yaml")

    def test_modus_ist_manuell(self):
        self.assertEqual(self.vorgabe.modus, "manuell")

    def test_solver_aendert_nichts(self):
        vorher = grundgeruest(self.stamm, self.vorgabe)
        erg = erzeuge(self.stamm, self.vorgabe, iterationen=5000, seed=3)
        for mid, reihe in vorher.zellen.items():
            for tag, z in reihe.items():
                g = erg.plan.zellen[mid][tag]
                self.assertEqual(z.art, g.art, f"{mid}/{tag}")
                if z.arbeitet:
                    self.assertEqual(z.schicht.label, g.schicht.label, f"{mid}/{tag}")

    def test_alle_zellen_sind_fixiert(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        for mid, reihe in plan.zellen.items():
            for tag, z in reihe.items():
                self.assertTrue(z.fixiert, f"{mid}/{tag}")

    def test_zeit_ausserhalb_des_katalogs_wird_uebernommen(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        z = plan.zellen["kurka_j"]["do"]        # 5-14 steht nicht im Katalog
        self.assertTrue(z.arbeitet)
        self.assertEqual(z.schicht.label, "5-14")
        self.assertNotIn("5-14", self.stamm.schichten)

    def test_unlesbare_zeit_wird_abgelehnt(self):
        self.vorgabe.fest["kurka_j"]["mo"] = "6 bis um"
        with self.assertRaises(ValueError) as fehler:
            grundgeruest(self.stamm, self.vorgabe)
        self.assertIn("kurka_j", str(fehler.exception))

    def test_ausgeschaltete_regeln_melden_nichts(self):
        regeln = {b.regel for b in pruefen(self.plan_erzeugen(), self.stamm,
                                           self.vorgabe).befunde}
        for aus in self.vorgabe.regeln_aus:
            self.assertNotIn(aus, regeln)

    def plan_erzeugen(self):
        return grundgeruest(self.stamm, self.vorgabe)

    def test_handplan_ist_regelkonform(self):
        fehler = [b.text for b in pruefen(self.plan_erzeugen(), self.stamm,
                                          self.vorgabe).befunde
                  if b.schwere == "fehler"]
        self.assertEqual(fehler, [])


class TestSchulplan(unittest.TestCase):
    """Berufsschultage aus dem Jahresplan H2FV 2026/27, Menzler ist Gruppe B."""

    def setUp(self):
        self.plaene = lade_schulplaene(WURZEL / "konfig")
        self.sp = self.plaene["menzler_a"]

    def test_menzler_ist_gruppe_b(self):
        self.assertEqual(self.sp.gruppe, "B")

    def test_theorie_donnerstag_in_jeder_schulwoche(self):
        for woche, tage in self.sp.tage.items():
            self.assertIn("do", tage, woche)

    def test_btw_woche_hat_zusaetzlich_mittwoch(self):
        self.assertEqual(self.sp.fuer("2026-KW38"), ["mi", "do"])
        self.assertEqual(self.sp.fuer("2026-KW42"), ["mi", "do"])

    def test_woche_ohne_btw_hat_nur_donnerstag(self):
        self.assertEqual(self.sp.fuer("2026-KW39"), ["do"])
        # KW04/2027: nur BTW-A hat Dienstag, Gruppe B also nur Theorie
        self.assertEqual(self.sp.fuer("2027-KW04"), ["do"])

    def test_sueffa_montag_betrifft_beide_gruppen(self):
        self.assertEqual(self.sp.fuer("2026-KW46"), ["mo", "do"])

    def test_btw_b_ausnahmsweise_am_dienstag(self):
        self.assertEqual(self.sp.fuer("2027-KW05"), ["di", "do"])

    def test_ferien_sind_schulfrei(self):
        for woche in ("2026-KW44", "2026-KW52", "2026-KW53", "2027-KW01", "2027-KW06"):
            self.assertEqual(self.sp.fuer(woche), [], woche)

    def test_jenseits_der_gueltigkeit_unbekannt(self):
        self.assertTrue(self.sp.ausserhalb("2027-KW20"))
        self.assertIsNone(self.sp.fuer("2027-KW20"))
        self.assertFalse(self.sp.ausserhalb("2026-KW42"))

    def test_nur_bekannte_wochentage(self):
        for woche, tage in self.sp.tage.items():
            for tag in tage:
                self.assertIn(tag, TAGE, f"{woche}/{tag}")

    def test_wochenvorgabe_enthaelt_die_schultage(self):
        v = lade_wochenvorgabe(WURZEL / "wochen/2026-KW42.yaml")
        self.assertEqual(v.abwesend["menzler_a"], {"mi": "schule", "do": "schule"})

    def test_mehr_als_fuenf_praesenztage_ist_ein_fehler(self):
        stamm = lade_stammdaten(WURZEL / "konfig")
        v = lade_wochenvorgabe(WURZEL / "wochen/2026-KW42.yaml")   # Mi + Do Schule
        plan = grundgeruest(stamm, v)
        for tag in ("mo", "di", "fr", "sa"):       # 4 Schichten + 2 Schultage = 6
            plan.zellen["menzler_a"][tag].art = "schicht"
            plan.zellen["menzler_a"][tag].schicht = stamm.schichten["8-16"]
        befunde = [b for b in pruefen(plan, stamm, v).befunde
                   if b.regel == "praesenztage"]
        self.assertTrue(befunde, "sechs Praesenztage muessen auffallen")
        self.assertEqual(befunde[0].schwere, "fehler")

    def test_genau_fuenf_praesenztage_sind_in_ordnung(self):
        stamm = lade_stammdaten(WURZEL / "konfig")
        v = lade_wochenvorgabe(WURZEL / "wochen/2026-KW42.yaml")
        plan = grundgeruest(stamm, v)
        for tag in ("mo", "fr", "sa"):             # 3 Schichten + 2 Schultage = 5
            plan.zellen["menzler_a"][tag].art = "schicht"
            plan.zellen["menzler_a"][tag].schicht = stamm.schichten["8-16"]
        regeln = {b.regel for b in pruefen(plan, stamm, v).befunde}
        self.assertNotIn("praesenztage", regeln)

    def test_zwei_schultage_lassen_drei_schichten(self):
        stamm = lade_stammdaten(WURZEL / "konfig")
        v = lade_wochenvorgabe(WURZEL / "wochen/2026-KW42.yaml")
        stunden, tage = Bewerter(stamm, v)._ziel("menzler_a")
        self.assertEqual(tage, 3)          # 5 Praesenztage minus 2 Schultage
        self.assertEqual(stunden, 24.0)    # 40 h minus 2 x 8 h Schule


class TestWochenBedarf(unittest.TestCase):
    def setUp(self):
        self.stamm = lade_stammdaten(WURZEL / "konfig")
        self.vorgabe = lade_wochenvorgabe(WURZEL / "wochen/2026-KW52.yaml")
        self.normal = lade_wochenvorgabe(WURZEL / "wochen/2026-KW42.yaml")

    def test_heiligabend_schliesst_frueher(self):
        b = Bewerter(self.stamm, self.vorgabe)       # 24.12.2026 ist ein Donnerstag
        self.assertEqual(b.bedarf.oeffnung["do"], (zu_index("05:00"), zu_index("14:00")))
        self.assertEqual(b.bedarf.oeffnung["mo"], self.stamm.bedarf.oeffnung["mo"])

    def test_kopfzahl_wird_uebersteuert(self):
        b = Bewerter(self.stamm, self.vorgabe)
        self.assertEqual(b.bedarf.kopfzahl["mi"], 10)

    def test_stammdaten_bleiben_unveraendert(self):
        Bewerter(self.stamm, self.vorgabe)
        self.assertEqual(self.stamm.bedarf.kopfzahl["mi"], 5)
        self.assertEqual(self.stamm.bedarf.oeffnung["do"][1], zu_index("20:00"))

    def test_ohne_uebersteuerung_identisch(self):
        b = Bewerter(self.stamm, self.normal)
        self.assertIs(b.bedarf, self.stamm.bedarf)


class TestExport(unittest.TestCase):
    def setUp(self):
        self.stamm = lade_stammdaten(WURZEL / "konfig")
        self.vorgabe = lade_wochenvorgabe(WURZEL / "wochen/2026-KW42.yaml")
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
        montag = datetime.date.fromisoformat(self.plan.datum_von)
        self.assertRegex(text, rf"{montag:%d\.%m\.%Y}|{montag.year}")

    def test_json_ist_wieder_einlesbar(self):
        import json
        doc = json.loads(export.als_json(self.plan, self.stamm))
        self.assertEqual(doc["woche"], "2026-KW42")
        self.assertEqual(set(doc["plan"]), set(self.plan.zellen))

    def test_abwesenheits_csv_listet_urlaub(self):
        text = export.als_abwesenheits_csv(self.plan, self.stamm)
        self.assertIn("urlaub", text)
        self.assertIn("A. Marino", text)


if __name__ == "__main__":
    unittest.main()
