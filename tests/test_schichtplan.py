"""Tests ohne externe Abhaengigkeiten: python3 -m pytest tests  (oder unittest)."""
import datetime
import pathlib
import sys
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from schichtplan.backtest import plan_aus_historie, vorgabe_aus_historie
from schichtplan.bewertung import Bewerter, pruefen
from schichtplan.feiertage import Kalender, feiertage_bw, ostersonntag
from schichtplan.generator import erzeuge, grundgeruest
from schichtplan.historie import kalenderabgleich, lade_historie
from schichtplan.konfig import (Wochenvorgabe, lade_schulplaene,
                                lade_stammdaten, lade_wochenvorgabe)
from schichtplan.modelle import TAGE, TAG_LANG, Zelle, zu_index, zu_text
from schichtplan import export

WURZEL = pathlib.Path(__file__).resolve().parents[1]


def woche(name: str = "2026-KW42", **felder) -> Wochenvorgabe:
    """Eine leere Wochenvorgabe fuer den Test.

    Nicht `wochen/2026-KW42.yaml` lesen: das ist eine echte Arbeitsdatei, die
    sich mit jeder Handkorrektur aendert. Ein Test, der darauf baut, faellt
    irgendwann um, ohne dass an der geprueften Regel etwas kaputt ist - genau
    das ist in dieser Entwicklung mehrfach passiert. Wer eine Abwesenheit oder
    eine feste Schicht braucht, traegt sie hier ausdruecklich ein.

        v = woche()
        v.abwesend["kurka_j"] = {"sa": "urlaub"}
    """
    jahr, kw = name.split("-KW")
    montag = datetime.date.fromisocalendar(int(jahr), int(kw), 1)
    vorgabe = Wochenvorgabe(
        woche=name,
        datum_von=montag.isoformat(),
        datum_bis=(montag + datetime.timedelta(days=5)).isoformat(),
        filiale="Winterbach",
    )
    for feld, wert in felder.items():
        setattr(vorgabe, feld, wert)
    return vorgabe


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
        self.vorgabe = woche()

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
        # Di, Fr und Sa sind bei C. Kurz fest frei und werden nur nach
        # Absprache geoeffnet - Mo/Mi/Do ist ihre Struktur.
        self.assertEqual(self.stamm.mitarbeiter["kurz_c"].bevorzugte_freie_tage, [])
        self.assertEqual(self.stamm.mitarbeiter["kurz_c"].nur_schichten,
                         {"sa": ["6-14"]})
        self.assertEqual(self.stamm.mitarbeiter["sannzenbacher_n"].bevorzugte_freie_tage,
                         ["mi", "do"])

    def test_feste_freie_tage_bleiben_frei(self):
        erg = erzeuge(self.stamm, self.vorgabe, iterationen=800, neustarts=1, seed=7)
        for mid, m in self.stamm.mitarbeiter.items():
            for t in m.feste_freie_tage:
                if t in self.vorgabe.arbeitet.get(mid, []):
                    continue          # in dieser Woche ausdruecklich aufgehoben
                self.assertFalse(erg.plan.zellen[mid][t].arbeitet, f"{mid}/{t}")

    def test_arbeitet_hebt_den_festen_freien_tag_auf(self):
        """'Carina arbeiten' am Dienstag - ihr fester freier Tag faellt weg."""
        self.vorgabe.arbeitet = {"kurz_c": ["di"]}
        self.assertIn("di", self.stamm.mitarbeiter["kurz_c"].feste_freie_tage)
        plan = grundgeruest(self.stamm, self.vorgabe)
        self.assertFalse(plan.zellen["kurz_c"]["di"].fixiert)
        erg = erzeuge(self.stamm, self.vorgabe, iterationen=4000, seed=2)
        self.assertTrue(erg.plan.zellen["kurz_c"]["di"].arbeitet)

    def test_kann_arbeiten_gibt_den_tag_frei_ohne_pflicht(self):
        """'Ich kann diesen Dienstag' aus dem Wandkalender: der Tag steht zur
        Verfuegung, aber niemand muss dort eingeteilt werden."""
        self.vorgabe.kann_arbeiten = {"kurz_c": ["di"]}
        plan = grundgeruest(self.stamm, self.vorgabe)
        self.assertFalse(plan.zellen["kurz_c"]["di"].fixiert)
        regeln = {b.regel for b in pruefen(plan, self.stamm, self.vorgabe).befunde}
        self.assertNotIn("soll_arbeiten", regeln)

    def test_kann_arbeiten_oeffnet_den_tag_fuer_den_planer(self):
        """Ohne Eintrag ist Dienstag auf 'frei' festgenagelt, mit
        'kann_arbeiten' darf der Planer ueber den Tag entscheiden."""
        zu = grundgeruest(self.stamm, self.vorgabe).zellen["kurz_c"]["di"]
        self.assertTrue(zu.fixiert)
        self.assertFalse(zu.arbeitet)
        self.vorgabe.kann_arbeiten = {"kurz_c": ["di"]}
        offen = grundgeruest(self.stamm, self.vorgabe).zellen["kurz_c"]["di"]
        self.assertFalse(offen.fixiert)

    def test_eine_person_allein_im_laden_ist_ein_fehler(self):
        """Allein im Laden geht nie - dann ist keine Pause moeglich."""
        plan = grundgeruest(self.stamm, self.vorgabe)
        for mid, reihe in plan.zellen.items():
            for tag in reihe:
                reihe[tag] = Zelle("frei")
        plan.zellen["kurka_j"]["mo"] = Zelle("schicht",
                                             self.stamm.schichten["6-14"])
        befunde = {b.regel: b for b in pruefen(plan, self.stamm,
                                               self.vorgabe).befunde}
        self.assertIn("allein", befunde)
        self.assertEqual(befunde["allein"].schwere, "fehler")

    def test_zu_zweit_im_laden_ist_kein_alleinfehler(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        for mid, reihe in plan.zellen.items():
            for tag in reihe:
                reihe[tag] = Zelle("frei")
        for mid in ("kurka_j", "rohwer_c"):
            plan.zellen[mid]["mo"] = Zelle("schicht",
                                           self.stamm.schichten["6-14"])
        regeln = {b.regel for b in pruefen(plan, self.stamm,
                                           self.vorgabe).befunde}
        self.assertNotIn("allein", regeln)

    def test_doppelter_schluessel_wird_gemeldet(self):
        """Zwei gleiche Schluessel in einer Ebene: YAML wuerde den ersten
        stillschweigend verwerfen, der Lader meldet es stattdessen."""
        import tempfile
        from schichtplan.konfig import lade_wochenvorgabe
        text = ("woche: 2026-KW42\n"
                "datum_von: 2026-10-12\n"
                "datum_bis: 2026-10-17\n"
                "fest:\n"
                "  kurz_u: {mi: 12-20}\n"
                "  kurz_u: {di: frei}\n")
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(text)
            pfad = f.name
        with self.assertRaises(ValueError) as fehler:
            lade_wochenvorgabe(pfad)
        self.assertIn("kurz_u", str(fehler.exception))

    def test_nur_schichten_am_tag_engt_die_auswahl_ein(self):
        """C. Kurz darf unter der Woche 8-14 und 8-16, samstags aber nur
        6-14 - die Tagesliste sticht die allgemeine Erlaubnis."""
        from schichtplan.generator import _optionen
        sa = [s.id for s in _optionen(self.stamm, "kurz_c", "sa") if s]
        self.assertEqual(sa, ["6-14"])
        mo = [s.id for s in _optionen(self.stamm, "kurz_c", "mo") if s]
        self.assertNotIn("6-14", mo)
        self.assertIn("8-14", mo)

    def test_ohne_spaetschicht_kein_frueh_spaet_ausgleich(self):
        """C. Kurz hat nur Schichten auf der Fruehseite - fuer sie ist der
        Ausgleich unerfuellbar und wird deshalb nicht bewertet."""
        bewerter = Bewerter(self.stamm, self.vorgabe)
        self.assertFalse(bewerter._beide_seiten("kurz_c"))
        self.assertTrue(bewerter._beide_seiten("kohl_b"))
        erg = erzeuge(self.stamm, self.vorgabe, iterationen=4000, seed=3)
        treffer = [b for b in erg.bewertung.befunde
                   if b.regel == "frueh_spaet_ausgleich" and "C. Kurz" in b.text]
        self.assertEqual(treffer, [])

    def test_mittelschicht_zaehlt_als_frueh(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        for reihe in plan.zellen.values():
            for tag in reihe:
                reihe[tag] = Zelle("frei")
        plan.zellen["kohl_b"]["mo"] = Zelle("schicht",
                                            self.stamm.schichten["8-15:30"])
        bewerter = Bewerter(self.stamm, self.vorgabe)
        frueh, spaet, _, _ = bewerter.schichtbilanz(plan, "kohl_b")
        self.assertEqual((frueh, spaet), (1, 0))

    def test_samstagprioritaet_daempft_den_rueckstand(self):
        """Rohwer behaelt ihren Mittwoch - ihr Samstagsrueckstand soll
        sichtbar bleiben, den Plan aber nicht mehr treiben."""
        self.assertEqual(self.stamm.mitarbeiter["rohwer_c"].samstagprioritaet, 0.3)
        self.assertEqual(self.stamm.mitarbeiter["marino_a"].samstagprioritaet, 1.0)

    def _samstag(self, *schichten):
        """Plan, in dem samstags genau diese Schichten besetzt sind."""
        plan = grundgeruest(self.stamm, self.vorgabe)
        for reihe in plan.zellen.values():
            for tag in reihe:
                reihe[tag] = Zelle("frei")
        for mid, sid in zip(("rohwer_c", "marino_a", "sannzenbacher_n", "reich_s",
                             "nachtrieb_i", "kohl_b", "kurz_u"), schichten):
            plan.zellen[mid]["sa"] = Zelle("schicht", self.stamm.schichten[sid])
        return plan

    def _samstagsbefunde(self, plan) -> dict:
        """Nur die Befunde, die den Samstag betreffen - die uebrigen Tage sind
        in diesen Plaenen absichtlich leer."""
        return {b.regel: b for b in pruefen(plan, self.stamm, self.vorgabe).befunde
                if "Samstag" in b.text}

    def test_samstag_mit_sechs_braucht_zwei_starts_bis_neun(self):
        """Sechs statt sieben ist erlaubt - dann aber zwei Starts bis 9."""
        knapp = self._samstag("6-14", "6-14", "6-14", "10-18", "11-18", "12-18")
        befunde = self._samstagsbefunde(knapp)
        self.assertIn("notfall_frueher_start", befunde)
        self.assertEqual(befunde["notfall_frueher_start"].schwere, "fehler")
        # Der erlassene Kopf taucht nicht mehr als Kopfzahlfehler auf.
        self.assertNotIn("kopfzahl", befunde)

        gut = self._samstag("6-14", "6-14", "6-14", "9-18", "9-18", "12-18")
        befunde = self._samstagsbefunde(gut)
        self.assertNotIn("notfall_frueher_start", befunde)
        self.assertNotIn("kopfzahl", befunde)

    def test_samstag_mit_fuenf_bleibt_ein_kopfzahlfehler(self):
        """Erlassen wird genau ein Kopf, nicht beliebig viele."""
        plan = self._samstag("6-14", "6-14", "6-14", "9-18", "9-18")
        self.assertIn("kopfzahl", self._samstagsbefunde(plan))

    def test_duennes_fenster_meldet_keine_schieflage(self):
        """Aus drei Schichten laesst sich keine Frueh/Spaet-Schieflage
        ablesen - sonst steht in der ersten Woche jeder schief da."""
        plan = grundgeruest(self.stamm, self.vorgabe)
        for reihe in plan.zellen.values():
            for tag in reihe:
                reihe[tag] = Zelle("frei")
        for tag in ("mo", "di", "mi"):
            plan.zellen["nachtrieb_i"][tag] = Zelle(
                "schicht", self.stamm.schichten["14-20"])
        treffer = [b for b in pruefen(plan, self.stamm, self.vorgabe).befunde
                   if b.regel == "frueh_spaet_ausgleich"
                   and "Nachtrieb" in b.text]
        self.assertEqual(treffer, [])

    def test_nicht_eingeteilter_pflichttag_ist_ein_fehler(self):
        self.vorgabe.arbeitet = {"kurz_c": ["di"]}
        plan = grundgeruest(self.stamm, self.vorgabe)       # Di bleibt leer
        regeln = {b.regel for b in pruefen(plan, self.stamm, self.vorgabe).befunde}
        self.assertIn("soll_arbeiten", regeln)

    def test_nur_erlaubte_schichten_am_erlaubten_tag(self):
        erg = erzeuge(self.stamm, self.vorgabe, iterationen=2000, neustarts=1, seed=3)
        for mid, reihe in erg.plan.zellen.items():
            m = self.stamm.mitarbeiter[mid]
            for t, z in reihe.items():
                if z.arbeitet:
                    # zusatzschichten gelten nur an den dort genannten Tagen -
                    # C. Kurz darf 6-14 ausschliesslich samstags.
                    erlaubt = list(m.erlaubte_schichten) + \
                        list(m.zusatzschichten.get(t, []))
                    self.assertIn(z.schicht.id, erlaubt)
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
        self.vorgabe = woche()

    def test_leerer_plan_wird_bestraft(self):
        leer = grundgeruest(self.stamm, self.vorgabe)
        self.assertGreater(pruefen(leer, self.stamm, self.vorgabe).punkte, 1000)

    def test_urlaub_kuerzt_das_stundensoll(self):
        v = woche()
        v.abwesend["marino_a"] = {t: "urlaub" for t in TAGE}
        b = Bewerter(self.stamm, v)
        soll_h, soll_t = b._ziel("marino_a")
        self.assertEqual(soll_t, 0)
        self.assertEqual(soll_h, 0.0)
        soll_h, _ = b._ziel("kurka_j")
        self.assertAlmostEqual(soll_h, 40.0)

    def test_ein_freier_tag_allein_senkt_das_soll_nicht(self):
        """Sechs offene Tage minus einer sind fuenf - das Soll bleibt haltbar."""
        v = woche()
        self.assertEqual(Bewerter(self.stamm, v)._ziel("kurka_j"), (40.0, 5))
        v.fest["kurka_j"] = {"fr": "frei"}
        self.assertEqual(Bewerter(self.stamm, v)._ziel("kurka_j"), (40.0, 5))

    def test_freier_tag_plus_urlaub_senkt_das_soll(self):
        """So liegt KW42: Freitag zugesagt frei, Samstag Urlaub."""
        v = woche()
        v.fest["kurka_j"] = {"fr": "frei"}
        v.abwesend["kurka_j"] = {"sa": "urlaub"}
        self.assertEqual(Bewerter(self.stamm, v)._ziel("kurka_j"), (32.0, 4))

    def test_fester_freier_tag_erzeugt_keinen_fehltag(self):
        v = woche()
        v.fest["kurka_j"] = {"fr": "frei"}
        plan = grundgeruest(self.stamm, v)
        for tag in ("mo", "di", "mi", "do", "sa"):
            plan.zellen["kurka_j"][tag].art = "schicht"
            plan.zellen["kurka_j"][tag].schicht = self.stamm.schichten["6-14"]
        texte = [b.text for b in pruefen(plan, self.stamm, v).befunde
                 if b.regel in ("arbeitstage", "fehltage_konto")]
        self.assertFalse(any("Kurka" in x for x in texte), texte)

    def test_arbeitet_macht_den_tag_wieder_einsetzbar(self):
        v = woche()
        b = Bewerter(self.stamm, v)
        self.assertFalse(b._einsetzbar("kurz_c", "di"))    # fester freier Tag
        v.arbeitet["kurz_c"] = ["di"]
        self.assertTrue(Bewerter(self.stamm, v)._einsetzbar("kurz_c", "di"))

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
        offen = [b.text for b in pruefen(plan, self.stamm, self.vorgabe).befunde
                 if b.regel == "gruppenbesetzung" and "Montag" in b.text]
        self.assertFalse(any("Frueh-Anker" in x for x in offen), offen)

    def test_kurka_ist_montags_gesetzt(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        self._setze(plan, "rohwer_c", "mo", "6-14")      # Anker ja, aber nicht Kurka
        offen = [b.text for b in pruefen(plan, self.stamm, self.vorgabe).befunde
                 if b.regel == "gruppenbesetzung"]
        self.assertTrue(any("Montags-Anker" in x for x in offen), offen)
        self._setze(plan, "kurka_j", "mo", "6-14")
        offen = [b.text for b in pruefen(plan, self.stamm, self.vorgabe).befunde
                 if b.regel == "gruppenbesetzung"]
        self.assertFalse(any("Montags-Anker" in x for x in offen), offen)

    def _anker(self, plan):
        """Befunde zum Montagsanker, getrennt nach Punkten und blossem Hinweis."""
        befunde = [b for b in pruefen(plan, self.stamm, self.vorgabe).befunde
                   if b.regel == "gruppenbesetzung" and "Montags-Anker" in b.text]
        return ([b.text for b in befunde if b.punkte > 0],
                [b.text for b in befunde if b.punkte == 0])

    def test_kurka_montags_im_urlaub_blockiert_nicht(self):
        """Eine Gruppenregel darf nicht an Abwesenden scheitern - gemeldet
        wird der Ausfall trotzdem, nur ohne Punkte."""
        self.vorgabe.abwesend["kurka_j"] = {t: "urlaub" for t in TAGE}
        plan = grundgeruest(self.stamm, self.vorgabe)
        self._setze(plan, "rohwer_c", "mo", "6-14")
        punkte, hinweis = self._anker(plan)
        self.assertEqual(punkte, [])
        self.assertTrue(any("J. Kurka" in x for x in hinweis), hinweis)

    def test_zugesagter_freier_montag_blockiert_auch_nicht(self):
        """So liegt KW45: der Wandkalender gibt Kurka den Montag frei."""
        self.vorgabe.fest.setdefault("kurka_j", {})["mo"] = "frei"
        plan = grundgeruest(self.stamm, self.vorgabe)
        self._setze(plan, "rohwer_c", "mo", "6-14")
        punkte, hinweis = self._anker(plan)
        self.assertEqual(punkte, [])
        self.assertTrue(hinweis)

    def test_anwesender_kurka_muss_montags_frueh_da_sein(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        self._setze(plan, "rohwer_c", "mo", "6-14")
        punkte, _ = self._anker(plan)
        self.assertTrue(punkte, "ohne Kurka am Montag muss die Regel greifen")

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
        # Menzler haette Mo/Di am liebsten frei - weich, anders als die
        # festen freien Tage von C. Kurz.
        plan = grundgeruest(self.stamm, self.vorgabe)
        self._setze(plan, "menzler_a", "mo", "8-16")
        texte = [b.text for b in pruefen(plan, self.stamm, self.vorgabe).befunde
                 if b.regel == "bevorzugter_freier_tag"]
        self.assertTrue(any("A. Menzler" in x and "Montag" in x for x in texte),
                        texte)

    def test_rohwer_fr_und_sa_auf_derselben_seite(self):
        """Freitag und Samstag gehoeren zusammen - beide frueh oder beide spaet."""
        plan = grundgeruest(self.stamm, self.vorgabe)
        self._setze(plan, "rohwer_c", "fr", "11-20")     # spaet
        self._setze(plan, "rohwer_c", "sa", "6-14")      # frueh -> auseinander
        regeln = {b.regel for b in pruefen(plan, self.stamm, self.vorgabe).befunde}
        self.assertIn("wochenwechsel_uneinheitlich", regeln)
        self._setze(plan, "rohwer_c", "sa", "11-18")     # Samstagsspaetschicht
        regeln = {b.regel for b in pruefen(plan, self.stamm, self.vorgabe).befunde}
        self.assertNotIn("wochenwechsel_uneinheitlich", regeln)

    def test_rohwer_wechselt_die_seite_von_woche_zu_woche(self):
        """In KW41 lag Fr/Sa frueh, also ist jetzt spaet an der Reihe."""
        vorwochen = lade_historie(WURZEL / "daten/historie")
        b = Bewerter(self.stamm, self.vorgabe, vorwochen)
        self.assertEqual(b._letzte_seite.get(("rohwer_c", 0)), "frueh")

        plan = grundgeruest(self.stamm, self.vorgabe)
        self._setze(plan, "rohwer_c", "fr", "6-14")
        self._setze(plan, "rohwer_c", "sa", "6-14")
        regeln = {x.regel for x in
                  pruefen(plan, self.stamm, self.vorgabe, vorwochen).befunde}
        self.assertIn("wochenwechsel", regeln)

        self._setze(plan, "rohwer_c", "fr", "11-20")
        self._setze(plan, "rohwer_c", "sa", "11-18")
        regeln = {x.regel for x in
                  pruefen(plan, self.stamm, self.vorgabe, vorwochen).befunde}
        self.assertNotIn("wochenwechsel", regeln)
        self.assertNotIn("wochenwechsel_uneinheitlich", regeln)

    def test_rohwer_will_mo_bis_do_frueh(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        self._setze(plan, "rohwer_c", "do", "11-20")
        regeln = {b.regel for b in pruefen(plan, self.stamm, self.vorgabe).befunde}
        self.assertIn("schichtwunsch", regeln)
        self._setze(plan, "rohwer_c", "do", "6-14")
        regeln = {b.regel for b in pruefen(plan, self.stamm, self.vorgabe).befunde}
        self.assertNotIn("schichtwunsch", regeln)

    def test_termin_verlangt_passendes_schichtende(self):
        from schichtplan.konfig import Termin
        self.vorgabe.termine = [Termin(name="Teamleitersitzung", tag="di",
                                       ab=zu_index("13:30"),
                                       kandidaten=["kurka_j"], anzahl=1)]
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

    def test_die_kennzahl_rechnet_brutto_und_mit_azubi(self):
        """So steht es auf dem Auswertungsblatt der Filiale: Arbeitszeit in
        Stunden gegen Wochenumsatz, ohne Pausenabzug, Azubi mitgezaehlt."""
        plan = grundgeruest(self.stamm, self.vorgabe)
        b = Bewerter(self.stamm, self.vorgabe)
        vorher = b.gesamtstunden(plan)
        self._setze(plan, "menzler_a", "mo", "8-16")          # 8 h
        self.assertEqual(b.gesamtstunden(plan), vorher + 8.0)
        self._setze(plan, "kurka_j", "mo", "6-14")            # nochmal 8 h
        self.assertEqual(b.gesamtstunden(plan), vorher + 16.0)

    def test_die_summenspalte_bleibt_netto(self):
        """Die Kennzahl ist brutto, die bezahlte Zeit je Mitarbeiter nicht."""
        v = woche()
        plan = grundgeruest(self.stamm, v)
        b = Bewerter(self.stamm, v)
        self._setze(plan, "kurka_j", "mo", "6-14")
        self.assertEqual(plan.netto_stunden("kurka_j", b.bedarf.pause_h), 7.5)
        self.assertEqual(b.gesamtstunden(plan), 8.0)
        self.assertEqual(b.nettostunden(plan), 7.5)

    def test_budget_haengt_nicht_an_abwesenheiten(self):
        """Urlaub senkt den Umsatzbedarf nicht, also auch nicht das Budget."""
        v = woche()
        b = self.stamm.bedarf
        voll = Bewerter(self.stamm, v).gesamtbudget()
        self.assertAlmostEqual(voll, b.umsatz_erwartet / b.umsatz_je_stunde)
        v.abwesend["marino_a"] = {t: "urlaub" for t in TAGE}
        self.assertAlmostEqual(Bewerter(self.stamm, v).gesamtbudget(), voll)

    def test_erreichbare_stunden_sinken_bei_abwesenheit(self):
        """Urlaub kostet Stunden - aber hoechstens die des Abwesenden.

        Marino bringt 40 h Anwesenheit auf 5 Schichten mit, netto 37.5 h.
        Weniger als das darf die Woche verlieren, weil andere in ihre
        freigewordenen Plaetze nachruecken koennen."""
        v = woche()
        voll = Bewerter(self.stamm, v).erreichbare_stunden()
        v.abwesend["marino_a"] = {t: "urlaub" for t in TAGE}
        ohne = Bewerter(self.stamm, v).erreichbare_stunden()
        self.assertLess(ohne, voll)
        self.assertGreaterEqual(ohne, voll - 37.5)

    def test_erreichbare_stunden_deckelt_an_der_kopfzahl(self):
        """Mehr als die Zielkopfzahl je Tag passt nicht in den Laden.

        Sonst mahnt das Budget Stunden an, fuer die es keine Plaetze gibt -
        in einer kurzen Woche mit Feiertag ist das der Regelfall."""
        v = woche()
        b = Bewerter(self.stamm, v)
        plaetze = sum(b.bedarf.kopfzahl[t] for t in b.tage)
        laengste = max(s.dauer_h for s in self.stamm.schichten.values())
        self.assertLessEqual(b.erreichbare_stunden(),
                             plaetze * (laengste - b.bedarf.pause_h))

    def test_reserve_kostet_je_stunde(self):
        """Der Gegendruck wirkt ohne Meldung - Reservestunden, die der Laden
        braucht, sind kein Befund."""
        plan = grundgeruest(self.stamm, self.vorgabe)
        self._setze(plan, "kurz_u", "mo", "14-20")
        mit = Bewerter(self.stamm, self.vorgabe).bewerte(plan).punkte
        vorher = list(self.vorgabe.regeln_aus)
        self.vorgabe.regeln_aus = vorher + ["sparsam_einsetzen"]
        ohne = Bewerter(self.stamm, self.vorgabe).bewerte(plan).punkte
        self.vorgabe.regeln_aus = vorher
        self.assertGreater(mit, ohne)
        regeln = {x.regel for x in pruefen(plan, self.stamm, self.vorgabe).befunde}
        self.assertNotIn("sparsam_einsetzen", regeln)

    def test_reserve_ueber_der_luecke_wird_gemeldet(self):
        """Jeder Reservetag mehr, als die Luecke hergibt, kostet jemandem
        mit Vertrag einen Tag."""
        b = Bewerter(self.stamm, self.vorgabe)
        bedarf = b.reservebedarf()
        plan = grundgeruest(self.stamm, self.vorgabe)
        moeglich = [t for t in b.tage if b._einsetzbar("kurz_u", t)]
        for tag in moeglich[:bedarf + 1]:
            self._setze(plan, "kurz_u", tag, "14-20" if tag != "sa" else "12-18")
        texte = [x.text for x in pruefen(plan, self.stamm, self.vorgabe).befunde
                 if x.regel == "reserve_ueber_bedarf"]
        self.assertTrue(any("U. Kurz" in x for x in texte), texte)


class TestGeschlosseneTage(unittest.TestCase):
    """Ein geschlossener Tag mitten in der Woche darf Abstaende nicht verkuerzen.

    Die Vorgabe wird hier kuenstlich gebaut (Freitag zu), damit der Test nicht
    davon abhaengt, wo im Kalender gerade ein Feiertag liegt."""

    def setUp(self):
        self.stamm = lade_stammdaten(WURZEL / "konfig")
        self.vorgabe = woche()
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
    # Liest absichtlich die echte KW40: geprueft wird, dass die Feiertagswoche
    # in der Datei richtig abgebildet ist, nicht nur die Feiertagsrechnung.
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
        self.vorgabe = woche()
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
        self.vorgabe = woche()
        self.historie = lade_historie(WURZEL / "daten/historie")

    def test_vorlage_nennt_nur_kurka(self):
        """Die Wochenvorlage schlaegt nur noch Kurka als Kandidat vor."""
        from schichtplan.cli import VORLAGE
        self.assertIn("kandidaten: [kurka_j]", VORLAGE)
        self.assertNotIn("kandidaten: [kurka_j, rohwer_c]", VORLAGE)

    def _mit_wechsel(self):
        """Termin mit zwei Kandidaten - so laesst sich der Wechsel pruefen,
        auch wenn in der Beispielwoche nur Kurka zugelassen ist."""
        from schichtplan.konfig import Termin
        tm = Termin(name="Teamleitersitzung", tag="di", ab=zu_index("13:30"),
                    kandidaten=["kurka_j", "rohwer_c"], anzahl=1, abwechselnd=True)
        self.vorgabe.termine = [tm]
        return tm

    def test_letzter_halter_wird_aus_der_historie_erkannt(self):
        tm = self._mit_wechsel()
        b = Bewerter(self.stamm, self.vorgabe, self.historie)
        # KW41: Kurka Di 6-13:30 - er war zuletzt dran
        self.assertEqual(b._letzter_terminhalter(tm), "kurka_j")

    def test_wiederholung_wird_bemaengelt(self):
        self._mit_wechsel()
        plan = grundgeruest(self.stamm, self.vorgabe)
        plan.zellen["kurka_j"]["di"].art = "schicht"
        plan.zellen["kurka_j"]["di"].schicht = self.stamm.schichten["6-13:30"]
        regeln = {b.regel for b in pruefen(plan, self.stamm, self.vorgabe,
                                           self.historie).befunde}
        self.assertIn("termin_wechsel", regeln)

    def test_wechsel_auf_rohwer_ist_in_ordnung(self):
        self._mit_wechsel()
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
    """Weihnachtswoche: der Planer rechnet nicht, er prueft und exportiert.

    Liest absichtlich die echte KW52 - geprueft wird genau dieser Handplan."""

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
        """Bis auf einen bekannten Punkt: Sannzenbacher hat am Montag Spaet und
        am Dienstag Frueh. Die Regel dagegen kam erst spaeter dazu, der
        Weihnachtsplan ist noch von Hand aus der alten Logik."""
        fehler = [b.text for b in pruefen(self.plan_erzeugen(), self.stamm,
                                          self.vorgabe).befunde
                  if b.schwere == "fehler" and b.regel != "spaet_vor_frueh"]
        self.assertEqual(fehler, [])

    def test_bekannter_konflikt_im_weihnachtsplan(self):
        texte = [b.text for b in pruefen(self.plan_erzeugen(), self.stamm,
                                         self.vorgabe).befunde
                 if b.regel == "spaet_vor_frueh"]
        self.assertTrue(any("Sannzenbacher" in x for x in texte), texte)


class TestVornamen(unittest.TestCase):
    """Der Kalender nennt Vornamen; aufgeloest wird ueber die Stammdaten."""

    def setUp(self):
        self.stamm = lade_stammdaten(WURZEL / "konfig")

    def test_jeder_hat_einen_eindeutigen_vornamen(self):
        vornamen = [m.vorname for m in self.stamm.mitarbeiter.values() if m.vorname]
        self.assertEqual(len(vornamen), len(self.stamm.mitarbeiter))
        self.assertEqual(len(set(v.casefold() for v in vornamen)), len(vornamen))

    def test_die_beiden_a_namen_stimmen(self):
        self.assertEqual(self.stamm.mitarbeiter["marino_a"].vorname, "Anna")
        self.assertEqual(self.stamm.mitarbeiter["menzler_a"].vorname, "Alex")

    def test_kalender_loest_vornamen_auf(self):
        from schichtplan.konfig import lade_kalender
        k = lade_kalender(WURZEL / "daten/kalender.yaml", self.stamm.mitarbeiter)
        self.assertTrue(k.eintraege)
        for e in k.eintraege:
            self.assertIn(e.ma, self.stamm.mitarbeiter, e.art)

    def test_alex_hat_urlaub_in_den_herbstferien(self):
        """Gegenprobe zur Namensverwechslung: Alex ist der Azubi, und sein
        Oktoberurlaub faellt genau in die schulfreie KW44."""
        import datetime
        from schichtplan.konfig import lade_kalender, lade_schulplaene
        k = lade_kalender(WURZEL / "daten/kalender.yaml", self.stamm.mitarbeiter)
        urlaub = [e for e in k.eintraege
                  if e.ma == "menzler_a" and e.art == "urlaub"]
        self.assertTrue(urlaub)
        self.assertEqual(urlaub[0].von, datetime.date(2026, 10, 26))
        sp = lade_schulplaene(WURZEL / "konfig")["menzler_a"]
        self.assertEqual(sp.fuer("2026-KW44"), [])      # Herbstferien

    def test_unbekannter_vorname_wird_abgelehnt(self):
        import tempfile
        from schichtplan.konfig import lade_kalender
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False,
                                         encoding="utf-8") as f:
            f.write("eintraege:\n  - {vorname: Rumpelstilzchen, "
                    "tag: 2026-10-05, art: frei}\n")
            pfad = f.name
        with self.assertRaises(ValueError) as fehler:
            lade_kalender(pfad, self.stamm.mitarbeiter)
        self.assertIn("Rumpelstilzchen", str(fehler.exception))
        pathlib.Path(pfad).unlink()


class TestPausen(unittest.TestCase):
    """Von jeder Schicht geht eine halbe Stunde Pause ab (ArbZG 4)."""

    def setUp(self):
        self.stamm = lade_stammdaten(WURZEL / "konfig")
        self.vorgabe = woche()
        self.pause = self.stamm.bedarf.pause_h

    def test_pause_ist_konfiguriert(self):
        self.assertEqual(self.stamm.bedarf.pause_minuten, 30)
        self.assertEqual(self.pause, 0.5)

    def test_netto_je_schicht(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        plan.zellen["kurka_j"]["mo"].art = "schicht"
        plan.zellen["kurka_j"]["mo"].schicht = self.stamm.schichten["6-14"]
        self.assertEqual(plan.stunden("kurka_j"), 8.0)
        self.assertEqual(plan.netto_stunden("kurka_j", self.pause), 7.5)

    def test_fuenf_schichten_fuenf_pausen(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        for tag in ("mo", "di", "mi", "do", "fr"):
            plan.zellen["kurka_j"][tag].art = "schicht"
            plan.zellen["kurka_j"][tag].schicht = self.stamm.schichten["6-14"]
        self.assertEqual(plan.stunden("kurka_j"), 40.0)
        self.assertEqual(plan.netto_stunden("kurka_j", self.pause), 37.5)

    def test_freie_tage_kosten_keine_pause(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        self.assertEqual(plan.netto_stunden("kurka_j", self.pause), 0.0)

    def test_kennzahl_brutto_bezahlte_zeit_netto(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        for tag in ("mo", "di"):
            plan.zellen["rohwer_c"][tag].art = "schicht"
            plan.zellen["rohwer_c"][tag].schicht = self.stamm.schichten["6-14"]
        b = Bewerter(self.stamm, self.vorgabe)
        self.assertEqual(b.gesamtstunden(plan), 16.0)     # Kennzahl, brutto
        self.assertEqual(b.nettostunden(plan), 15.0)      # bezahlte Zeit


class TestSparsamPlanen(unittest.TestCase):
    """Die 255 h sind eine Obergrenze, kein Ziel: wer dieselbe Besetzung mit
    weniger Stunden hinbekommt, hebt den Umsatz je Verkaeuferstunde."""

    def setUp(self):
        self.stamm = lade_stammdaten(WURZEL / "konfig")
        self.vorgabe = woche()

    def test_unter_budget_kostet_nichts(self):
        g = self.stamm.regeln.gewichte
        self.assertNotIn("gesamtstunden_unter", g)
        self.assertGreater(g["gesamtstunden_ueber"], 0)

    def test_unter_budget_wird_gemeldet_ohne_punkte(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        befunde = [b for b in pruefen(plan, self.stamm, self.vorgabe).befunde
                   if b.regel == "gesamtstunden_unter"]
        self.assertTrue(befunde)
        self.assertEqual([b.punkte for b in befunde], [0.0])

    def test_ueber_budget_kostet(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        for mid in self.stamm.mitarbeiter:
            m = self.stamm.mitarbeiter[mid]
            if not (m.im_plan and "11-20" in m.erlaubte_schichten):
                continue
            for tag in ("mo", "di", "mi", "do", "fr"):
                plan.zellen[mid][tag].art = "schicht"
                plan.zellen[mid][tag].schicht = self.stamm.schichten["11-20"]
        regeln = {b.regel for b in pruefen(plan, self.stamm, self.vorgabe).befunde}
        self.assertIn("gesamtstunden_ueber", regeln)

    def test_vertrag_ist_der_boden(self):
        """Ohne diesen Boden plant der Planer alle auf die Mindestbesetzung
        herunter - das Budget haelt seit der Umstellung nichts mehr dagegen."""
        g = self.stamm.regeln.gewichte
        self.assertGreaterEqual(g["wochenstunden_unter"], g["besetzung_ueber"])

    def test_splitterschichten_werden_bemaengelt(self):
        """Fuer drei Stunden faehrt niemand in den Laden."""
        plan = grundgeruest(self.stamm, self.vorgabe)
        plan.zellen["kurka_j"]["mo"].art = "schicht"
        plan.zellen["kurka_j"]["mo"].schicht = self.stamm.schichten["6-11"]
        texte = [b.text for b in pruefen(plan, self.stamm, self.vorgabe).befunde
                 if b.regel == "kurzschicht"]
        self.assertTrue(any("Kurka" in x for x in texte), texte)

    def test_die_untergrenze_haengt_am_vertragstag(self):
        """5 h sind fuer eine 40-Stunden-Kraft zu wenig, fuer C. Kurz nicht."""
        plan = grundgeruest(self.stamm, self.vorgabe)
        plan.zellen["kurz_c"]["mi"].art = "schicht"
        plan.zellen["kurz_c"]["mi"].schicht = self.stamm.schichten["8-13"]   # 5 h
        texte = [b.text for b in pruefen(plan, self.stamm, self.vorgabe).befunde
                 if b.regel == "kurzschicht"]
        self.assertEqual([x for x in texte if "C. Kurz" in x], [])


class TestAushilfeUndRestwoche(unittest.TestCase):
    """Zwei Faelle aus dem Betrieb: jemand kommt aus einer anderen Filiale
    dazu, und jemand faellt mitten in der Woche aus."""

    def setUp(self):
        self.stamm = lade_stammdaten(WURZEL / "konfig")
        self.vorgabe = woche("2026-KW44")

    LEIHKRAFT = {"id": "aushilfe_1", "name": "M. Weber (Schorndorf)",
                 "faehigkeiten": ["f", "w"], "soll_stunden": 32, "soll_tage": 4,
                 "tage": ["mo", "di", "mi", "do", "fr", "sa"]}

    def test_aushilfe_wird_aus_der_wochenvorgabe_gelesen(self):
        from schichtplan.konfig import _aushilfen
        gelesen = _aushilfen([self.LEIHKRAFT])
        self.assertEqual(gelesen[0]["id"], "aushilfe_1")

    def test_aushilfe_kommt_in_die_stammdaten(self):
        from schichtplan.konfig import mit_aushilfen
        self.vorgabe.aushilfe = [dict(self.LEIHKRAFT)]
        erweitert = mit_aushilfen(self.stamm, self.vorgabe)
        self.assertNotIn("aushilfe_1", self.stamm.mitarbeiter)   # Original unberuehrt
        a = erweitert.mitarbeiter["aushilfe_1"]
        self.assertEqual(a.soll_tage, 4)
        self.assertIn("f", a.faehigkeiten)
        self.assertFalse(a.samstag_konto)      # naechste Woche ist sie wieder weg

    def test_aushilfe_ist_eine_reserve(self):
        """Sie senkt die Luecke nicht, sie fuellt sie - deshalb zeigen genau
        ihre Schichten, wofuer Ersatz gebraucht wird."""
        from schichtplan.konfig import mit_aushilfen
        v = woche("2026-KW44")
        v.aushilfe = [dict(self.LEIHKRAFT)]
        erweitert = mit_aushilfen(self.stamm, v)
        a = erweitert.mitarbeiter["aushilfe_1"]
        self.assertTrue(a.moeglichst_wenig)
        self.assertTrue(a.nur_obergrenze)
        self.assertEqual(Bewerter(erweitert, v).reservebedarf(),
                         Bewerter(self.stamm, self.vorgabe).reservebedarf())

    def test_aushilfe_vergroessert_das_machbare(self):
        from schichtplan.konfig import mit_aushilfen
        ohne = Bewerter(self.stamm, self.vorgabe).erreichbare_stunden()
        v = woche("2026-KW44")
        v.aushilfe = [dict(self.LEIHKRAFT)]
        mit = Bewerter(mit_aushilfen(self.stamm, v), v).erreichbare_stunden()
        self.assertGreater(mit, ohne)

    def test_nur_verfuegbare_tage(self):
        from schichtplan.konfig import mit_aushilfen
        v = woche("2026-KW44")
        v.aushilfe = [{"id": "leih", "name": "Leihkraft", "faehigkeiten": ["w"],
                       "soll_stunden": 16, "soll_tage": 2, "tage": ["fr", "sa"]}]
        b = Bewerter(mit_aushilfen(self.stamm, v), v)
        self.assertFalse(b._einsetzbar("leih", "mo"))
        self.assertTrue(b._einsetzbar("leih", "fr"))

    def test_fehlende_angaben_fallen_auf(self):
        from schichtplan.konfig import _aushilfen
        with self.assertRaises(ValueError):
            _aushilfen([{"name": "ohne Kuerzel"}])

    def test_restwoche_nagelt_die_vergangenen_tage_fest(self):
        from schichtplan.cli import _restwoche_fixieren
        import json, tempfile
        plan = erzeuge(self.stamm, self.vorgabe, iterationen=3000, seed=1).plan
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write(export.als_json(plan, self.stamm))   # liefert fertiges JSON
            pfad = f.name
        v = woche("2026-KW44")
        _restwoche_fixieren(v, self.stamm, pfad, "mi")
        self.assertIn("mo", v.fest.get("rohwer_c", {}))
        self.assertIn("di", v.fest.get("rohwer_c", {}))
        self.assertNotIn("mi", v.fest.get("rohwer_c", {}))
        self.assertNotIn("sa", v.fest.get("rohwer_c", {}))

    def test_unbekannter_tag_faellt_auf(self):
        from schichtplan.cli import _restwoche_fixieren
        with self.assertRaises(ValueError):
            _restwoche_fixieren(self.vorgabe, self.stamm, "egal.json", "sonntag")


class TestUmsatzbudget(unittest.TestCase):
    """Die Sollstunden kommen aus dem erwarteten Umsatz: 27.000 EUR bei
    105 EUR je Stunde sind die 255 h vom Auswertungsblatt."""

    def setUp(self):
        self.stamm = lade_stammdaten(WURZEL / "konfig")
        self.vorgabe = woche()

    def test_soll_kommt_aus_dem_umsatz(self):
        b = self.stamm.bedarf
        self.assertEqual(b.umsatz_je_stunde, 105)
        soll = Bewerter(self.stamm, self.vorgabe).gesamtbudget()
        self.assertAlmostEqual(soll, b.umsatz_erwartet / b.umsatz_je_stunde)
        self.assertAlmostEqual(soll, 257.14, places=1)

    def test_wochenvorgabe_kann_den_umsatz_uebersteuern(self):
        """Eine Vorweihnachtswoche traegt mehr Stunden als eine im Februar."""
        self.vorgabe.bedarf = {"umsatz_erwartet": 33600}
        self.assertAlmostEqual(Bewerter(self.stamm, self.vorgabe).gesamtbudget(), 320.0)

    def test_ohne_umsatz_greift_die_feste_stundenzahl(self):
        import dataclasses
        stamm = dataclasses.replace(
            self.stamm,
            bedarf=dataclasses.replace(self.stamm.bedarf, umsatz_erwartet=0))
        self.assertAlmostEqual(Bewerter(stamm, self.vorgabe).gesamtbudget(),
                               stamm.bedarf.wochenstunden_gesamt)


class TestKategorieprofil(unittest.TestCase):
    """Montag bis Donnerstag: zwei Frueh, eine Mittel, zwei Spaet."""

    def setUp(self):
        self.stamm = lade_stammdaten(WURZEL / "konfig")
        self.vorgabe = woche()

    def test_profil_ist_hinterlegt(self):
        for tag in ("mo", "di", "mi", "do"):
            self.assertEqual(self.stamm.bedarf.kategorieprofil[tag],
                             {"frueh": 2, "mittel": 1, "spaet": 2})
        self.assertNotIn("fr", self.stamm.bedarf.kategorieprofil)

    def _belege(self, plan, paare, tag="mo"):
        for mid, sid in paare:
            plan.zellen[mid][tag].art = "schicht"
            plan.zellen[mid][tag].schicht = self.stamm.schichten[sid]

    def test_dritte_fruehschicht_faellt_auf(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        self._belege(plan, [("kurka_j", "6-14"), ("rohwer_c", "6-14"),
                            ("marino_a", "6-14"), ("reich_s", "14-20"),
                            ("kohl_b", "12-20")])
        texte = [b.text for b in pruefen(plan, self.stamm, self.vorgabe).befunde
                 if b.regel == "kategorieprofil" and "Montag" in b.text]
        self.assertTrue(any("frueh" in x for x in texte), texte)

    def test_passendes_geruest_bleibt_unbeanstandet(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        self._belege(plan, [("kurka_j", "6-14"), ("rohwer_c", "6-14"),
                            ("kurz_c", "8-14"), ("reich_s", "14-20"),
                            ("kohl_b", "12-20")])
        texte = [b.text for b in pruefen(plan, self.stamm, self.vorgabe).befunde
                 if b.regel == "kategorieprofil" and "Montag" in b.text]
        self.assertEqual(texte, [])

    def test_azubi_als_zweite_mittelschicht_stoert_nicht(self):
        """Bei 'mittel' wird nur ein Fehlbestand bemaengelt, kein Ueberhang."""
        plan = grundgeruest(self.stamm, self.vorgabe)
        self._belege(plan, [("kurka_j", "6-14"), ("rohwer_c", "6-14"),
                            ("kurz_c", "8-14"), ("menzler_a", "8-16"),
                            ("reich_s", "14-20"), ("kohl_b", "12-20")])
        texte = [b.text for b in pruefen(plan, self.stamm, self.vorgabe).befunde
                 if b.regel == "kategorieprofil" and "Montag" in b.text]
        self.assertEqual(texte, [])

    def test_azubi_bevorzugt_die_mittelschicht(self):
        self.assertEqual(self.stamm.mitarbeiter["menzler_a"].bevorzugte_kategorie,
                         "mittel")
        plan = grundgeruest(self.stamm, self.vorgabe)
        self._belege(plan, [("menzler_a", "11-20")])
        regeln = {b.regel for b in pruefen(plan, self.stamm, self.vorgabe).befunde}
        self.assertIn("bevorzugte_kategorie", regeln)


class TestFreiOderFrueh(unittest.TestCase):
    """'frueh/frei' am Kalender: bevorzugt frei, sonst nur die Fruehschicht."""

    def setUp(self):
        self.stamm = lade_stammdaten(WURZEL / "konfig")
        self.vorgabe = woche()
        self.vorgabe.nur_schichten = {"kurz_u": {"sa": ["6-14"]}}
        self.vorgabe.wunsch_frei = {"kurz_u": ["sa"]}

    def test_nur_frei_oder_fruehschicht_stehen_zur_wahl(self):
        from schichtplan.generator import _optionen
        opts = _optionen(self.stamm, "kurz_u", "sa", self.vorgabe)
        self.assertIn(None, opts)                                  # frei
        self.assertEqual([s.id for s in opts if s], ["6-14"])
        # ohne die Einschraenkung haette sie deutlich mehr Auswahl
        self.assertGreater(len(_optionen(self.stamm, "kurz_u", "sa")), 2)

    def test_der_generator_haelt_sich_daran(self):
        erg = erzeuge(self.stamm, self.vorgabe, iterationen=6000, seed=5)
        z = erg.plan.zellen["kurz_u"]["sa"]
        if z.arbeitet:
            self.assertEqual(z.schicht.id, "6-14")

    def test_freier_tag_wird_bevorzugt(self):
        """Ohne Not soll sie den Tag frei bekommen."""
        erg = erzeuge(self.stamm, self.vorgabe, iterationen=30000, seed=1)
        self.assertFalse(erg.plan.zellen["kurz_u"]["sa"].arbeitet)

    def test_unerfuellbare_einschraenkung_faellt_auf(self):
        from schichtplan.generator import grundgeruest
        self.vorgabe.nur_schichten = {"kurz_u": {"sa": ["8-13"]}}   # nur Mi erlaubt
        with self.assertRaises(ValueError) as fehler:
            grundgeruest(self.stamm, self.vorgabe)
            erzeuge(self.stamm, self.vorgabe, iterationen=100, seed=1)
        self.assertIn("kurz_u", str(fehler.exception))


class TestKalenderVollstaendig(unittest.TestCase):
    def setUp(self):
        from schichtplan.konfig import lade_kalender
        self.stamm = lade_stammdaten(WURZEL / "konfig")
        self.k = lade_kalender(WURZEL / "daten/kalender.yaml", self.stamm.mitarbeiter)

    def test_keine_offenen_fragen_mehr(self):
        self.assertEqual(self.k.zu_klaeren, [])

    def test_alle_arten_sind_bekannt(self):
        from schichtplan.konfig import ARTEN_KALENDER
        for e in self.k.eintraege:
            self.assertIn(e.art, ARTEN_KALENDER)

    def test_frei_oder_frueh_kommt_viermal_vor(self):
        treffer = [e for e in self.k.eintraege if e.art == "frei_oder_frueh"]
        self.assertEqual(len(treffer), 4)
        for e in treffer:
            erlaubt = self.stamm.mitarbeiter[e.ma].erlaubte_schichten
            self.assertIn("6-14", erlaubt, e.ma)

    def test_jonas_urlaub_beginnt_am_17_oktober(self):
        import datetime
        urlaub = [e for e in self.k.eintraege
                  if e.ma == "kurka_j" and e.art == "urlaub"]
        self.assertEqual(len(urlaub), 1)
        self.assertEqual(urlaub[0].von, datetime.date(2026, 10, 17))


class TestUeberbesetzung(unittest.TestCase):
    """Eine Woche ohne Urlaub gibt mehr Personentage her, als der Laden
    braucht. Dann bekommt jemand einen zusaetzlichen freien Tag - und die
    Konten entscheiden, wen es trifft."""

    def setUp(self):
        self.stamm = lade_stammdaten(WURZEL / "konfig")
        self.vorgabe = woche()
        self.wochen = lade_historie(WURZEL / "daten/historie")

    def test_zielkopfzahl_ist_eine_obergrenze(self):
        self.assertEqual(self.stamm.bedarf.kopfzahl_toleranz_ueber, 0)

    def test_ein_kopf_zu_viel_kostet_mehr_als_ein_freier_tag(self):
        """Sonst stellt der Planer lieber jemanden ueberzaehlig in den Laden."""
        g = self.stamm.regeln.gewichte
        freier_tag = g["arbeitstage_unter"] + g["wochenstunden_unter"] * 8
        self.assertGreater(g["kopfzahl_ueber"] + g["besetzung_ueber"] * 16,
                           freier_tag * 0.9)

    def test_ueberzaehliger_kopf_wird_gemeldet(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        ziel = self.stamm.bedarf.kopfzahl["mo"]
        frei = [mid for mid, m in self.stamm.mitarbeiter.items()
                if m.im_plan and "mo" not in m.feste_freie_tage][:ziel + 1]
        for mid in frei:
            plan.zellen[mid]["mo"].art = "schicht"
            plan.zellen[mid]["mo"].schicht = self.stamm.schichten["6-14"]
        regeln = {b.regel for b in pruefen(plan, self.stamm, self.vorgabe).befunde}
        self.assertIn("kopfzahl_ueber", regeln)

    def test_ueberstunden_sind_nie_billiger_als_ein_ausfall(self):
        """Mehrarbeit muss jemand wirklich leisten."""
        g = self.stamm.regeln.gewichte
        self.assertGreaterEqual(g["wochenstunden"], g["wochenstunden_unter"])
        self.assertGreater(g["arbeitstage"], g["arbeitstage_unter"])

    def test_stundenkonto_misst_gegen_den_teamschnitt(self):
        """Wer genau im Schnitt liegt, zahlt nichts - egal wie gross das
        Minus der ganzen Mannschaft ist."""
        b = Bewerter(self.stamm, self.vorgabe, self.wochen)
        konto = b.stundenkonto()
        self.assertTrue(konto)
        self.assertNotIn("kurz_u", konto)      # Reserve verzerrt den Schnitt
        self.assertNotIn("menzler_a", konto)   # Azubi haengt an praesenztage

    def test_gleichmaessiges_minus_kostet_nichts(self):
        """Alle gleich weit zurueck heisst: gerecht verteilt."""
        v = self.vorgabe
        b = Bewerter(self.stamm, v, self.wochen)
        gruppe = b._kontogruppe()
        # Der leere Plan legt jedem sein volles Wochensoll aufs Konto; die
        # Historie wird so gesetzt, dass danach alle gleich weit zurueckliegen.
        b._minusstunden = {mid: 60.0 - b._ziel(mid)[0] for mid in gruppe}
        erg = b.bewerte(grundgeruest(self.stamm, v), detail=True)
        self.assertEqual([x.text for x in erg.befunde
                          if x.regel == "minusstunden_konto"], [])

    def test_einseitiges_minus_kostet(self):
        v = self.vorgabe
        b = Bewerter(self.stamm, v, self.wochen)
        gruppe = b._kontogruppe()
        b._minusstunden = {mid: 60.0 - b._ziel(mid)[0] for mid in gruppe}
        b._minusstunden["kohl_b"] += 60.0                 # einer haengt hinterher
        erg = b.bewerte(grundgeruest(self.stamm, v), detail=True)
        texte = [x.text for x in erg.befunde if x.regel == "minusstunden_konto"]
        self.assertTrue(any("B. Kohl" in x for x in texte), texte)

    def test_ueberhang_nennt_kandidaten(self):
        plan = erzeuge(self.stamm, self.vorgabe, self.wochen,
                       iterationen=2000, seed=1).plan
        texte = [b.text for b in
                 pruefen(plan, self.stamm, self.vorgabe, self.wochen).befunde
                 if b.regel == "ueberhang"]
        self.assertEqual(len(texte), 1, texte)
        self.assertIn("Personentage", texte[0])
        self.assertIn("Stundenkonto", texte[0])

    def test_stammdaten_passen_zusammen(self):
        """Niemandes Wochensoll darf ueber dem liegen, was seine gewohnten
        Schichten hergeben - sonst laeuft sein Stundenkonto dauerhaft ins
        Minus, ohne dass der Planer etwas falsch macht."""
        plan = grundgeruest(self.stamm, self.vorgabe)
        texte = [b.text for b in pruefen(plan, self.stamm, self.vorgabe).befunde
                 if b.regel == "stammdaten"]
        self.assertEqual(texte, [])

    def test_unerreichbares_wochensoll_wird_gemeldet(self):
        import dataclasses
        m = self.stamm.mitarbeiter["kurz_c"]           # 3 Tage, laengste 6 h
        self.stamm.mitarbeiter["kurz_c"] = dataclasses.replace(m, soll_stunden=30)
        plan = grundgeruest(self.stamm, self.vorgabe)
        texte = [b.text for b in pruefen(plan, self.stamm, self.vorgabe).befunde
                 if b.regel == "stammdaten"]
        self.assertTrue(any("C. Kurz" in x for x in texte), texte)


class TestArbeitszeitgrenzen(unittest.TestCase):
    def setUp(self):
        self.stamm = lade_stammdaten(WURZEL / "konfig")
        self.vorgabe = woche()

    def test_obergrenze_ist_gesetzt(self):
        self.assertEqual(self.stamm.regeln.max_wochenstunden, 48)

    def test_zu_lange_woche_ist_ein_fehler(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        for tag in TAGE:                       # 6 x 9 h = 54 h
            plan.zellen["sannzenbacher_n"][tag].art = "schicht"
            plan.zellen["sannzenbacher_n"][tag].schicht = \
                self.stamm.schichten["11-20" if tag != "sa" else "10-18"]
        befunde = [b for b in pruefen(plan, self.stamm, self.vorgabe).befunde
                   if b.regel == "max_stunden"]
        self.assertTrue(befunde, "54 h muessen auffallen")
        self.assertEqual(befunde[0].schwere, "fehler")

    def test_normale_woche_bleibt_unbeanstandet(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        for tag in ("mo", "di", "mi", "do", "fr"):
            plan.zellen["kurka_j"][tag].art = "schicht"
            plan.zellen["kurka_j"][tag].schicht = self.stamm.schichten["6-14"]
        regeln = {b.regel for b in pruefen(plan, self.stamm, self.vorgabe).befunde}
        self.assertNotIn("max_stunden", regeln)


class TestKonten(unittest.TestCase):
    """Freie Samstage und Fehltage ueber mehrere Wochen ausgleichen."""

    def setUp(self):
        self.stamm = lade_stammdaten(WURZEL / "konfig")
        self.vorgabe = woche()
        self.historie = lade_historie(WURZEL / "daten/historie")
        self.b = Bewerter(self.stamm, self.vorgabe, self.historie)

    def test_wer_samstags_fest_frei_hat_zaehlt_nicht_mit(self):
        konto = self.b.samstagskonto()
        self.assertNotIn("kurz_c", konto)      # Samstag bevorzugt frei
        self.assertIn("rohwer_c", konto)

    def test_rueckstand_wird_erkannt(self):
        moeglich, frei, soll = self.b.samstagskonto()["rohwer_c"]
        self.assertEqual(frei, 0)              # 12 Samstage, keiner frei
        self.assertGreater(soll, 1)

    def test_strukturell_unmoegliche_samstage(self):
        """Wer fuenf Tage soll und einen festen freien Tag hat, muss samstags
        ran - dafuer darf ihn der Planer nicht bestrafen."""
        for mid in ("marino_a", "reich_s"):
            self.assertTrue(self.b.samstag_zwingend(mid), mid)
        for mid in ("nachtrieb_i", "kohl_b", "sannzenbacher_n", "kurka_j"):
            self.assertFalse(self.b.samstag_zwingend(mid), mid)

    def test_rohwer_darf_einen_samstag_frei_haben(self):
        """Ausdruecklich zugelassen: dann faellt sie dafuer unter ihre fuenf
        Tage. Ohne diese Ausnahme kaeme sie strukturell nie an einen freien
        Samstag, und das Konto waere eine Dauerforderung ins Leere."""
        self.assertTrue(self.stamm.mitarbeiter["rohwer_c"].samstag_moeglich)
        self.assertFalse(self.b.samstag_zwingend("rohwer_c"))

    def test_zwingende_samstage_erzeugen_keine_strafe(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        for tag in ("di", "do", "fr", "sa"):
            plan.zellen["marino_a"][tag].art = "schicht"
            plan.zellen["marino_a"][tag].schicht = self.stamm.schichten[
                "6-14" if tag != "sa" else "10-18"]
        texte = [b.text for b in pruefen(plan, self.stamm, self.vorgabe,
                                         self.historie).befunde
                 if b.regel == "samstag_konto"]
        self.assertFalse(any("Marino" in x for x in texte), texte)

    def test_freier_samstag_verbessert_das_konto(self):
        plan = grundgeruest(self.stamm, self.vorgabe)
        ohne = self.b.samstagskonto(plan)["nachtrieb_i"]
        plan.zellen["nachtrieb_i"]["sa"].art = "schicht"
        plan.zellen["nachtrieb_i"]["sa"].schicht = self.stamm.schichten["6-14"]
        mit = self.b.samstagskonto(plan)["nachtrieb_i"]
        self.assertEqual(ohne[1], mit[1] + 1)          # ein freier Samstag mehr
        self.assertEqual(ohne[0], mit[0])              # gleich viele moeglich

    def test_einsatzprioritaet_gewichtet_fehltage(self):
        self.assertGreater(self.stamm.mitarbeiter["marino_a"].einsatzprioritaet,
                           self.stamm.mitarbeiter["rohwer_c"].einsatzprioritaet)

    def test_fehltage_bei_marino_wiegen_schwerer_als_bei_rohwer(self):
        """Gleicher Rueckstand, aber Marino soll ihre Tage eher bekommen.

        Gemessen wird gegen den Teamschnitt, deshalb muessen die beiden
        ueber dem Schnitt liegen - sonst kostet der Rueckstand nichts."""
        b = Bewerter(self.stamm, self.vorgabe, self.historie)
        b._fehltage = {mid: 0.0 for mid in self.stamm.mitarbeiter}
        b._fehltage["marino_a"] = b._fehltage["rohwer_c"] = 6.0
        befunde = b.bewerte(grundgeruest(self.stamm, self.vorgabe),
                            detail=True).befunde

        def punkte(mid):
            name = self.stamm.mitarbeiter[mid].name
            return sum(x.punkte for x in befunde
                       if x.regel == "fehltage_konto" and name in x.text)
        self.assertGreater(punkte("rohwer_c"), 0)
        self.assertGreater(punkte("marino_a"), punkte("rohwer_c"))

    def test_schultage_zaehlen_als_praesenz_im_fehltagekonto(self):
        """Ohne diese Ausnahme erschiene jede Schulwoche als Fehltag."""
        self.assertLessEqual(self.b._fehltage["menzler_a"], 1.0)


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
        """Hier absichtlich die echte Datei: geprueft wird, dass 'neu' die
        Schultage aus dem Jahresplan eingetragen hat."""
        v = lade_wochenvorgabe(WURZEL / "wochen/2026-KW42.yaml")
        self.assertEqual(v.abwesend["menzler_a"], {"mi": "schule", "do": "schule"})

    def test_mehr_als_fuenf_praesenztage_ist_ein_fehler(self):
        stamm = lade_stammdaten(WURZEL / "konfig")
        v = woche()
        v.abwesend["menzler_a"] = {"mi": "schule", "do": "schule"}
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
        v = woche()
        v.abwesend["menzler_a"] = {"mi": "schule", "do": "schule"}
        plan = grundgeruest(stamm, v)
        for tag in ("mo", "fr", "sa"):             # 3 Schichten + 2 Schultage = 5
            plan.zellen["menzler_a"][tag].art = "schicht"
            plan.zellen["menzler_a"][tag].schicht = stamm.schichten["8-16"]
        regeln = {b.regel for b in pruefen(plan, stamm, v).befunde}
        self.assertNotIn("praesenztage", regeln)

    def test_zwei_schultage_lassen_drei_schichten(self):
        stamm = lade_stammdaten(WURZEL / "konfig")
        v = woche()
        v.abwesend["menzler_a"] = {"mi": "schule", "do": "schule"}
        stunden, tage = Bewerter(stamm, v)._ziel("menzler_a")
        self.assertEqual(tage, 3)          # 5 Praesenztage minus 2 Schultage
        self.assertEqual(stunden, 24.0)    # 40 h minus 2 x 8 h Schule


class TestWochenBedarf(unittest.TestCase):
    # Liest absichtlich die echte KW52: geprueft wird deren Bedarfsuebersteuerung.
    def setUp(self):
        self.stamm = lade_stammdaten(WURZEL / "konfig")
        self.vorgabe = lade_wochenvorgabe(WURZEL / "wochen/2026-KW52.yaml")
        self.normal = woche()

    def test_heiligabend_schliesst_frueher(self):
        b = Bewerter(self.stamm, self.vorgabe)       # 24.12.2026 ist ein Donnerstag
        self.assertEqual(b.bedarf.oeffnung["do"], (zu_index("05:00"), zu_index("14:00")))
        self.assertEqual(b.bedarf.oeffnung["mo"], self.stamm.bedarf.oeffnung["mo"])

    def test_kopfzahl_wird_uebersteuert(self):
        b = Bewerter(self.stamm, self.vorgabe)
        self.assertEqual(b.bedarf.kopfzahl["mi"], 9)

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
        self.vorgabe = woche()
        # Eine Abwesenheit je Art, damit der Export etwas zu zeigen hat.
        self.vorgabe.abwesend["menzler_a"] = {"mi": "schule", "do": "schule"}
        self.vorgabe.abwesend["kurka_j"] = {"sa": "urlaub"}
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

    def test_abwesenheits_csv_listet_abwesenheiten(self):
        text = export.als_abwesenheits_csv(self.plan, self.stamm)
        self.assertIn("schule", text)
        self.assertIn("A. Menzler", text)


class TestPapierUndUebersicht(unittest.TestCase):
    """Was aus dem Werkzeug faellt: Papierplan, Teamleiteruebersicht, PDF."""

    def setUp(self):
        self.stamm = lade_stammdaten(WURZEL / "konfig")
        self.vorgabe = woche()
        self.plan = erzeuge(self.stamm, self.vorgabe, iterationen=1500,
                            neustarts=1, seed=11).plan
        self.bewerter = Bewerter(self.stamm, self.vorgabe)
        self.bew = pruefen(self.plan, self.stamm, self.vorgabe)

    def test_zusatzzeile_steht_im_papierplan(self):
        self.assertIn("Palmstrasse Aushilfe", self.stamm.bedarf.zusatzzeilen)
        h = export.als_html(self.plan, self.stamm, self.bew, bewerter=self.bewerter)
        self.assertIn("Palmstrasse Aushilfe", h)
        self.assertIn("zusatz-zeile", h)

    def test_zusatzzeile_ist_leer(self):
        """Sie wird von Hand ausgefuellt - der Planer schreibt nichts hinein."""
        h = export.als_html(self.plan, self.stamm, self.bew, bewerter=self.bewerter)
        zeile = h.split('class="zusatz-zeile"')[1].split("</tr>")[0]
        self.assertEqual(zeile.count('<td class="leer"></td>'), 6)   # sechs Tage
        self.assertIn('<td class="summe leer"></td>', zeile)         # und die Summe
        self.assertNotIn("6-14", zeile)

    def test_papier_ist_din_a4(self):
        h = export.als_html(self.plan, self.stamm, self.bew, bewerter=self.bewerter)
        self.assertIn("@page { size: A4 landscape", h)
        self.assertNotIn("AUSRICHTUNG", h)

    def test_papier_laesst_sich_hochkant_stellen(self):
        import dataclasses
        stamm = dataclasses.replace(
            self.stamm,
            bedarf=dataclasses.replace(self.stamm.bedarf, papier_hoch=True))
        h = export.als_html(self.plan, stamm, self.bew, bewerter=self.bewerter)
        self.assertIn("@page { size: A4 portrait", h)

    def test_uebersicht_ist_din_a4(self):
        from schichtplan import uebersicht
        h = uebersicht.als_html(self.plan, self.stamm, self.bew, self.bewerter)
        self.assertIn("@page { size: A4 portrait", h)

    def test_uebersicht_nennt_befunde_und_stunden(self):
        from schichtplan import uebersicht
        h = uebersicht.als_html(self.plan, self.stamm, self.bew, self.bewerter)
        self.assertIn("Teamleiteruebersicht", h)
        self.assertIn("Arbeitszeit", h)
        for mid, m in self.stamm.mitarbeiter.items():
            if m.im_plan and m.aktiv and self.plan.arbeitstage(mid):
                self.assertIn(m.name, h, mid)

    def test_uebersicht_zeigt_konten_wenn_historie_da_ist(self):
        from schichtplan import konten, uebersicht
        wochen = lade_historie(WURZEL / "daten/historie")
        zeilen = konten.sammle(self.stamm, wochen)
        h = uebersicht.als_html(self.plan, self.stamm, self.bew, self.bewerter,
                                zeilen)
        self.assertIn("Rollierende Konten", h)
        ohne = uebersicht.als_html(self.plan, self.stamm, self.bew, self.bewerter)
        self.assertNotIn("Rollierende Konten", ohne)

    def test_pdf_wird_erzeugt_wenn_ein_browser_da_ist(self):
        import tempfile
        from schichtplan import pdf
        if not pdf.browser():
            self.skipTest("kein Chromium im System")
        h = export.als_html(self.plan, self.stamm, self.bew, bewerter=self.bewerter)
        with tempfile.TemporaryDirectory() as tmp:
            ziel = pathlib.Path(tmp) / "plan.pdf"
            pdf.aus_html(h, ziel)
            self.assertTrue(ziel.exists())
            self.assertEqual(ziel.read_bytes()[:4], b"%PDF")


if __name__ == "__main__":
    unittest.main()


class TestWeboberflaeche(unittest.TestCase):
    """Die Oberflaeche arbeitet auf den echten Dateien - geprueft wird gegen
    eine Kopie im Temporaerordner, damit kein Wochenplan verbogen wird."""

    def setUp(self):
        import shutil
        import tempfile
        from schichtplan import weboberflaeche
        self.ordner = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.ordner, ignore_errors=True)
        wochen = self.ordner / "wochen"
        wochen.mkdir()
        shutil.copy(WURZEL / "wochen/2026-KW42.yaml", wochen)
        self.werkstatt = weboberflaeche.Werkstatt(
            str(WURZEL / "konfig"), str(wochen),
            str(self.ordner / "ausgabe"), str(WURZEL / "daten/historie"))

    def test_liste_und_woche(self):
        liste = self.werkstatt.liste()
        self.assertEqual([e["woche"] for e in liste], ["2026-KW42"])
        woche = self.werkstatt.woche("2026-KW42")
        self.assertNotIn("fehler", woche)
        self.assertIn("woche: 2026-KW42", woche["yaml"])
        namen = [m["name"] for m in woche["mitarbeiter"]]
        self.assertIn("C. Rohwer", namen)

    def test_wochenname_darf_nicht_ausbrechen(self):
        with self.assertRaises(ValueError):
            self.werkstatt.pfad("../konfig/regeln")

    def test_kaputtes_yaml_wird_zurueckgerollt(self):
        vorher = self.werkstatt.woche("2026-KW42")["yaml"]
        with self.assertRaises(ValueError):
            self.werkstatt.speichern("2026-KW42", "fest: [kaputt\n")
        self.assertEqual(self.werkstatt.woche("2026-KW42")["yaml"], vorher)

    def test_zelle_setzen_und_loeschen_erhaelt_kommentare(self):
        vorher = self.werkstatt.woche("2026-KW42")["yaml"]
        kommentare = [z for z in vorher.splitlines() if z.strip().startswith("#")]
        nachher = self.werkstatt.zelle(
            "2026-KW42", "rohwer_c", "mo", "6-14")["yaml"]
        self.assertIn("  rohwer_c: {mo: 6-14}", nachher)
        self.assertEqual([z for z in nachher.splitlines()
                          if z.strip().startswith("#")], kommentare)
        zurueck = self.werkstatt.zelle(
            "2026-KW42", "rohwer_c", "mo", "auto")["yaml"]
        # Nur die echte Zeile verschwindet - die auskommentierten Beispiele
        # mit demselben Namen bleiben stehen.
        self.assertEqual([z for z in zurueck.splitlines()
                          if z.startswith("  rohwer_c:")], [])
        self.assertEqual([z for z in zurueck.splitlines()
                          if z.strip().startswith("#")], kommentare)

    def test_zelle_landet_als_harte_vorgabe_im_plan(self):
        self.werkstatt.zelle("2026-KW42", "kurz_u", "mi", "14-20")
        vorgabe = lade_wochenvorgabe(self.werkstatt.pfad("2026-KW42"))
        self.assertEqual(vorgabe.fest["kurz_u"]["mi"], "14-20")

    def test_unbekannter_tag_wird_abgelehnt(self):
        with self.assertRaises(ValueError):
            self.werkstatt.zelle("2026-KW42", "kurz_u", "sonntag", "14-20")

    def test_rechnen_schreibt_die_ausgabedateien(self):
        kennung = self.werkstatt.starte(
            "2026-KW42", {"iterationen": 2000, "neustarts": 1, "seed": 3})
        for _ in range(600):
            auftrag = self.werkstatt.auftraege[kennung]
            if auftrag["stand"] != "laeuft":
                break
            time.sleep(0.1)
        self.assertEqual(auftrag["stand"], "fertig", auftrag.get("spur"))
        for name in ("2026-KW42.html", "2026-KW42.json",
                     "2026-KW42-teamleiter.html"):
            self.assertIn(name, auftrag["dateien"])
        self.assertTrue((self.ordner / "ausgabe/2026-KW42.json").exists())
        # Danach kennt die Woche ihren Plan und ihre Befunde.
        woche = self.werkstatt.woche("2026-KW42")
        self.assertIn("plan", woche)
        self.assertTrue(woche["befunde"])

    def test_uebernehmen_ohne_plan_meldet_sich(self):
        with self.assertRaises(FileNotFoundError):
            self.werkstatt.uebernehmen("2026-KW42")

    def test_urlaub_laesst_sich_aus_der_tafel_eintragen(self):
        """Urlaub, Wunschfrei und Co. gehen jetzt ueber dieselbe Zelle wie
        die Schicht - nicht mehr nur ueber den Rohtext."""
        antwort = self.werkstatt.zelle("2026-KW42", "rohwer_c", "mo", "urlaub")
        vorgabe = lade_wochenvorgabe(self.werkstatt.pfad("2026-KW42"))
        self.assertEqual(vorgabe.abwesend["rohwer_c"]["mo"], "urlaub")
        self.assertIn("urlaub", antwort["yaml"])

        self.werkstatt.zelle("2026-KW42", "rohwer_c", "mo", "wunsch_frei")
        vorgabe = lade_wochenvorgabe(self.werkstatt.pfad("2026-KW42"))
        # Beim Wechsel darf der alte Eintrag nicht stehen bleiben.
        self.assertNotIn("mo", vorgabe.abwesend.get("rohwer_c", {}))
        self.assertIn("mo", vorgabe.wunsch_frei["rohwer_c"])

        self.werkstatt.zelle("2026-KW42", "rohwer_c", "mo", "6-14")
        vorgabe = lade_wochenvorgabe(self.werkstatt.pfad("2026-KW42"))
        self.assertEqual(vorgabe.fest["rohwer_c"]["mo"], "6-14")
        self.assertNotIn("rohwer_c", vorgabe.wunsch_frei)

        self.werkstatt.zelle("2026-KW42", "rohwer_c", "mo", "auto")
        vorgabe = lade_wochenvorgabe(self.werkstatt.pfad("2026-KW42"))
        self.assertNotIn("mo", vorgabe.fest.get("rohwer_c", {}))

    def test_vorgabe_steht_in_der_antwort(self):
        """Damit die Tafel die Woche auch ohne gerechneten Plan zeigen kann."""
        self.werkstatt.zelle("2026-KW42", "marino_a", "do", "krank")
        woche = self.werkstatt.woche("2026-KW42")
        self.assertEqual(woche["vorgabe"]["marino_a"]["do"], "krank")
        self.assertEqual(woche["vorgabe"]["kurka_j"]["fr"], "frei")

    def test_handkorrektur_bleibt_im_plan_stehen(self):
        """Der eigentliche Punkt: die Zelle darf nicht auf den gerechneten
        Wert zurueckspringen."""
        kennung = self.werkstatt.starte(
            "2026-KW42", {"iterationen": 2000, "neustarts": 1, "seed": 3})
        for _ in range(600):
            if self.werkstatt.auftraege[kennung]["stand"] != "laeuft":
                break
            time.sleep(0.1)
        antwort = self.werkstatt.zelle("2026-KW42", "kurz_u", "mi", "14-20")
        self.assertEqual(antwort["plan"]["plan"]["kurz_u"]["mi"],
                         {"art": "schicht", "von": "14:00", "bis": "20:00",
                          "zusatz": []})
        # Und nach einem Neuladen immer noch.
        woche = self.werkstatt.woche("2026-KW42")
        self.assertEqual(woche["plan"]["plan"]["kurz_u"]["mi"]["von"], "14:00")
        # Die Bewertung ist mitgelaufen.
        self.assertIsInstance(antwort["punkte"], (int, float))

    def test_handkorrektur_schreibt_den_papierplan_neu(self):
        kennung = self.werkstatt.starte(
            "2026-KW42", {"iterationen": 2000, "neustarts": 1, "seed": 3})
        for _ in range(600):
            if self.werkstatt.auftraege[kennung]["stand"] != "laeuft":
                break
            time.sleep(0.1)
        self.werkstatt.zelle("2026-KW42", "kurz_u", "mi", "14-20")
        papier = (self.ordner / "ausgabe/2026-KW42.html").read_text(
            encoding="utf-8")
        self.assertIn("14-20", papier)

    def test_mitarbeiter_kennen_die_schichtart(self):
        """Die Oberflaeche faerbt die Zellen danach ein."""
        woche = self.werkstatt.woche("2026-KW42")
        rohwer = [m for m in woche["mitarbeiter"] if m["id"] == "rohwer_c"][0]
        arten = {s["kategorie"] for s in rohwer["schichten"]["mo"]}
        self.assertEqual(arten, {"frueh", "spaet"})
        self.assertIn("kopfzahl", woche["bedarf"])

    def test_bewertung_nennt_auch_die_gesamtpunkte(self):
        """Die Summe der angezeigten Befunde ist nicht der ganze Wert -
        vieles kostet Punkte, ohne einen Satz wert zu sein."""
        kennung = self.werkstatt.starte(
            "2026-KW42", {"iterationen": 2000, "neustarts": 1, "seed": 3})
        for _ in range(600):
            if self.werkstatt.auftraege[kennung]["stand"] != "laeuft":
                break
            time.sleep(0.1)
        woche = self.werkstatt.woche("2026-KW42")
        self.assertIsInstance(woche["punkte"], (int, float))
        sichtbar = sum(b["punkte"] for b in woche["befunde"])
        self.assertGreaterEqual(woche["punkte"], sichtbar)


class TestSymbol(unittest.TestCase):
    """Das Programmsymbol wird aus dem Werkzeug erzeugt - geprueft wird, dass
    die mitgelieferten Dateien noch dazu passen."""

    def test_ico_enthaelt_alle_groessen(self):
        import struct
        pfad = WURZEL / "schichtplan/web/bild/symbol.ico"
        roh = pfad.read_bytes()
        _, typ, anzahl = struct.unpack("<HHH", roh[:6])
        self.assertEqual(typ, 1)
        self.assertEqual(anzahl, 7)
        for i in range(anzahl):
            b, h, _, _, _, _, laenge, versatz = struct.unpack(
                "<BBBBHHII", roh[6 + 16 * i: 22 + 16 * i])
            self.assertEqual(roh[versatz:versatz + 8], b"\x89PNG\r\n\x1a\n")
            png_b, png_h = struct.unpack(">II", roh[versatz + 16: versatz + 24])
            self.assertEqual((png_b, png_h), (b or 256, h or 256))
            self.assertLessEqual(versatz + laenge, len(roh))

    def test_symbol_laesst_sich_neu_bauen(self):
        import importlib.util
        pfad = WURZEL / "werkzeug/symbol_bauen.py"
        spec = importlib.util.spec_from_file_location("symbol_bauen", pfad)
        modul = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modul)
        frisch = modul.zeichne(32)
        alt = (WURZEL / "schichtplan/web/bild/symbol-32.png").read_bytes()
        self.assertEqual(frisch, alt,
                         "symbol-32.png passt nicht mehr zum Werkzeug - "
                         "python werkzeug/symbol_bauen.py neu laufen lassen")


class TestE2nVorlage(unittest.TestCase):
    """Die Spaltennamen von e2n sind nicht bekannt - das Werkzeug soll sie
    aus einer echten Datei uebernehmen koennen."""

    def _kopf(self, zeile: str, name: str = "vorlage.csv") -> pathlib.Path:
        import tempfile
        ordner = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, ordner, ignore_errors=True)
        pfad = ordner / name
        pfad.write_text(zeile, encoding="utf-8")
        return pfad

    def test_deutsche_schichtvorlage(self):
        from schichtplan import e2n
        pfad = self._kopf("Pers.-Nr.;Nachname;Vorname;Datum;Beginn (Uhrzeit);"
                          "Ende (Uhrzeit);Pausendauer in Minuten;Abteilung\n")
        spalten, trenn, satz = e2n.lies_kopf(pfad)
        self.assertEqual(trenn, ";")
        gefunden, offen, welche = e2n.zuordnung(spalten)
        self.assertEqual(welche, "schichten")
        self.assertEqual(offen, [])
        self.assertEqual(gefunden["personalnummer"], "Pers.-Nr.")
        self.assertEqual(gefunden["beginn"], "Beginn (Uhrzeit)")
        self.assertEqual(gefunden["arbeitsbereich"], "Abteilung")

    def test_abwesenheitsvorlage_wird_erkannt(self):
        from schichtplan import e2n
        pfad = self._kopf("﻿Mitarbeiternummer,Mitarbeiter,Datum,"
                          "Abwesenheitsart,Kostenstelle\n")
        spalten, trenn, satz = e2n.lies_kopf(pfad)
        self.assertEqual((trenn, satz), (",", "utf-8-sig"))
        gefunden, offen, welche = e2n.zuordnung(spalten)
        self.assertEqual(welche, "abwesenheiten")
        self.assertEqual(gefunden["art"], "Abwesenheitsart")
        self.assertEqual(offen, ["Kostenstelle"])

    def test_leere_und_sinnlose_dateien_melden_sich(self):
        from schichtplan import e2n
        with self.assertRaises(ValueError):
            e2n.lies_kopf(self._kopf("\n"))
        with self.assertRaises(ValueError):
            e2n.lies_kopf(self._kopf("nur eine Spalte ohne Trenner\n"))

    def test_uebernahme_laesst_sich_wieder_laden(self):
        """Was das Werkzeug schreibt, muss der Lader auch lesen koennen."""
        import shutil
        import tempfile
        from schichtplan import e2n
        from schichtplan.konfig import lade_e2n
        pfad = self._kopf("Pers.-Nr.;Nachname;Vorname;Datum;Beginn;Ende;"
                          "Pause;Abteilung\n")
        neu, bericht = e2n.uebernehmen(pfad, lade_e2n(WURZEL / "konfig"))
        self.assertEqual(bericht["fehlend"], [])
        ordner = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, ordner, ignore_errors=True)
        shutil.copytree(WURZEL / "konfig", ordner / "konfig")
        (ordner / "konfig/e2n.yaml").write_text(
            e2n.als_yaml(neu, "Test"), encoding="utf-8")
        zurueck = lade_e2n(ordner / "konfig")
        self.assertEqual(zurueck.schicht_spalten, neu.schicht_spalten)
        self.assertEqual(zurueck.kopf("schichten")[0], "Pers.-Nr.")

    def test_export_folgt_der_vorlage(self):
        from schichtplan import e2n, export
        from schichtplan.konfig import lade_e2n
        pfad = self._kopf("Pers.-Nr.;Nachname;Vorname;Datum;Beginn;Ende;"
                          "Pause;Abteilung\n")
        format, _ = e2n.uebernehmen(pfad, lade_e2n(WURZEL / "konfig"))
        stamm = lade_stammdaten(WURZEL / "konfig")
        vorgabe = woche("2026-KW42")
        plan = grundgeruest(stamm, vorgabe)
        plan.zellen["rohwer_c"]["mo"] = Zelle("schicht", stamm.schichten["6-14"])
        text = export.als_e2n_csv(plan, stamm, arbeitsbereich="Theke",
                                  pause_min=30, format=format)
        zeilen = text.splitlines()
        self.assertEqual(zeilen[0].split(";")[0], "Pers.-Nr.")
        treffer = [z for z in zeilen if "Rohwer" in z]
        self.assertTrue(treffer)
        felder = treffer[0].split(";")
        self.assertEqual(felder[1], "Rohwer")
        self.assertEqual(felder[2], "Carmen")
        self.assertEqual(felder[4:7], ["06:00", "14:00", "30"])

    def test_fehlende_pflichtspalten_werden_gemeldet(self):
        from schichtplan import e2n
        from schichtplan.konfig import lade_e2n
        pfad = self._kopf("Mitarbeiter;Abteilung\n")
        _, bericht = e2n.uebernehmen(pfad, lade_e2n(WURZEL / "konfig"))
        self.assertEqual(set(bericht["fehlend"]), {"datum", "beginn", "ende"})
