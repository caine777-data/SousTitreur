"""Tests du découpage (sans réseau ni interface).

Lancer depuis le dossier du projet :  python -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sous_titres as st                                          # noqa: E402


def phrases(*textes, debit=0.07):
    """Fabrique des phrases Aristote avec mots horodatés (débit en s/caractère)."""
    sortie, t = [], 0.0
    for texte in textes:
        mots = []
        for w in texte.split():
            d = debit * len(w) + 0.1
            mots.append({"text": " " + w, "start": t, "end": t + d})
            t += d + 0.05
        sortie.append({"text": texte, "start": mots[0]["start"],
                       "end": mots[-1]["end"], "words": mots})
        t += 0.6
    return sortie


LONG = ("Prenez un exemple, le vol d'identité. Un matin, j'ouvre mon logiciel de "
        "messagerie et je constate l'arrivée d'un courriel du Crédit Agricole. "
        "Jusqu'ici, rien d'anormal, c'est ma banque. Dans un premier temps, le logo "
        "attire toute mon attention, puis je me précipite sur la lecture du message.")


class TestDecoupage(unittest.TestCase):
    def setUp(self):
        self.p = st.Parametres()

    def decouper(self, *textes):
        return st.decouper(st.mots_depuis_aristote(phrases(*textes)), self.p)

    def test_normes_respectees(self):
        sts = self.decouper(LONG)
        self.assertGreater(len(sts), 4)
        for s in sts:
            lignes = s.texte.split("\n")
            self.assertLessEqual(len(lignes), 2, s.texte)
            for l in lignes:
                self.assertLessEqual(len(l), 42, l)
            self.assertLessEqual(s.fin - s.debut, self.p.duree_max + 0.01)

    def test_texte_conserve(self):
        sts = self.decouper(LONG)
        recompose = " ".join(s.texte.replace("\n", " ") for s in sts)
        self.assertEqual(recompose.split(), LONG.split())

    def test_pas_de_chevauchement(self):
        sts = self.decouper(LONG, LONG)
        for a, b in zip(sts, sts[1:]):
            self.assertLessEqual(a.fin, b.debut - self.p.ecart_min + 1e-6)

    def test_pas_de_fin_sur_mot_faible(self):
        for s in self.decouper(LONG):
            for l in s.texte.split("\n"):
                dernier = l.split()[-1].lower()
                self.assertNotIn(dernier, {"le", "la", "les", "de", "du", "un", "une", "et"}, l)

    def test_nom_propre_non_coupe(self):
        sts = self.decouper(LONG)
        for s in sts:
            self.assertFalse(s.texte.rstrip().endswith("Crédit"), s.texte)

    def test_elisions_recollees(self):
        brut = [{"text": "le vol d'identité", "start": 0, "end": 2, "words": [
            {"text": " le", "start": 0, "end": .3}, {"text": " vol", "start": .3, "end": .7},
            {"text": " d", "start": .7, "end": .8}, {"text": "'identité", "start": .8, "end": 1.6},
            {"text": " ?", "start": 1.6, "end": 1.7}]}]
        mots = st.mots_depuis_aristote(brut)
        self.assertEqual([m.texte for m in mots], ["le", "vol", "d'identité ?"])

    def test_hallucination_filtree(self):
        brut = phrases("Bonjour à tous.", "Sous-titrage ST' 501")
        self.assertEqual(" ".join(m.texte for m in st.mots_depuis_aristote(brut)),
                         "Bonjour à tous.")

    def test_phrase_sans_mots(self):
        mots = st.mots_depuis_aristote([{"text": "Une phrase sans horodatage", "start": 2, "end": 4}])
        self.assertEqual(len(mots), 4)
        self.assertAlmostEqual(mots[0].debut, 2)
        self.assertAlmostEqual(mots[-1].fin, 4)

    def test_aller_retour_vtt_srt(self):
        sts = self.decouper(LONG)
        for fn in (st.vers_vtt, st.vers_srt):
            relu = st.lire_vtt_srt(fn(sts))
            self.assertEqual([s.texte for s in relu], [s.texte for s in sts])
            self.assertAlmostEqual(relu[-1].fin, sts[-1].fin, places=2)

    def test_verifier(self):
        s = st.SousTitre(0, 0.5, "x" * 50 + "\nb\nc")
        codes = {a.code for a in st.verifier(s, self.p)}
        self.assertEqual(codes, {"lignes", "cpl", "court", "cps"})


if __name__ == "__main__":
    unittest.main()
