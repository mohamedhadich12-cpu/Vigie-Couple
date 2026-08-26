# -*- coding: utf-8 -*-
"""Tests du cœur de calcul. Aucun test d'interface : detection.py sans Qt."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vigie_couple.coeur.detection import (  # noqa: E402
    IndicateursEssai, Reglages, ResumeResidu, analyser, carte_cusum, carte_ewma,
    discriminer, ecart_type_robuste, reference_robuste,
)

MU0, SIGMA0 = 0.0, 1.0


def _essai(indice: int, biais: float, **extra) -> IndicateursEssai:
    """Fabrique un essai minimal : seul le résumé du résidu est obligatoire."""
    resume = ResumeResidu(biais=biais, ecart_type=1.0, ecart_max=abs(biais) + 1.0)
    return IndicateursEssai(nom=f"essai_{indice:02d}",
                            date=f"2026-03-{indice % 28 + 1:02d} 09:00",
                            duree_s=600.0,
                            couple_max=900.0,
                            residus={"voie_opposee": resume}, **extra)


def _delai_detection(carte, decalage: float, n: int = 60, reps: int = 50) -> float:
    """Délai moyen de détection d'un décalage constant, cartes remises à zéro."""
    delais = []
    for graine in range(reps):
        x = np.random.default_rng(graine).normal(MU0 + decalage, SIGMA0, n)
        premiere = carte(x).premiere_alarme
        delais.append(premiere + 1 if premiere is not None else n)
    return float(np.mean(delais))


def _cusum(x):
    return carte_cusum(x, MU0, SIGMA0, k=0.5, h=5.0)


def _ewma(x):
    return carte_ewma(x, MU0, SIGMA0, lam=0.10, L=2.7)


# --------------------------------------------------------------------------
# Cartes de contrôle
# --------------------------------------------------------------------------
def test_cusum_detecte_un_decalage_de_un_sigma_en_moins_de_15_essais():
    assert _delai_detection(_cusum, 1.0) < 15.0


def _taux_fausse_alarme(carte, n: int = 200, reps: int = 200) -> float:
    """Part des séries saines de longueur n qui déclenchent au moins une alarme."""
    return float(np.mean([
        carte(np.random.default_rng(g).normal(MU0, SIGMA0, n)).premiere_alarme
        is not None for g in range(reps)]))


def _arl0(taux: float, n: int = 200) -> float:
    """ARL₀ déduite du taux de fausse alarme : taux = 1 − exp(−n / ARL₀)."""
    return -n / np.log(1.0 - taux)


def test_cusum_ne_declenche_pas_sur_200_essais_sains():
    """La majorité des séries saines de 200 essais passent sans alarme,
    ce qui correspond à l'ARL₀ visée d'environ 465 essais."""
    taux = _taux_fausse_alarme(_cusum)
    assert taux < 0.45
    assert _arl0(taux) > 300.0


def test_ewma_a_un_comportement_comparable_a_la_cusum():
    assert _delai_detection(_ewma, 1.0) < 15.0
    taux = _taux_fausse_alarme(_ewma)
    assert taux < 0.55
    assert _arl0(taux) > 250.0


def test_ewma_inclut_le_terme_transitoire():
    """Sans le terme transitoire, la limite serait constante dès i = 1."""
    resultat = _ewma(np.zeros(100))
    demi_debut = resultat.limite_sup[0] - MU0
    demi_fin = resultat.limite_sup[-1] - MU0
    asymptote = 2.7 * SIGMA0 * np.sqrt(0.10 / (2.0 - 0.10))
    assert demi_debut == pytest.approx(2.7 * SIGMA0 * 0.10, rel=1e-6)
    assert demi_debut < 0.45 * demi_fin
    assert demi_fin == pytest.approx(asymptote, rel=1e-3)


def test_ewma_detecte_plus_tot_grace_au_terme_transitoire():
    """Un décalage présent dès le premier essai est vu en début de série."""
    x = np.full(30, 3.0 * SIGMA0)
    assert _ewma(x).premiere_alarme is not None
    assert _ewma(x).premiere_alarme < 10


# --------------------------------------------------------------------------
# Estimation robuste
# --------------------------------------------------------------------------
def test_ecart_type_robuste_insensible_a_une_valeur_aberrante():
    x = np.random.default_rng(3).normal(0.0, 1.0, 30)
    pollue = x.copy()
    pollue[17] = 40.0  # essai 18 aberrant, comme dans le jeu de démonstration
    robuste_avant = ecart_type_robuste(x)
    robuste_apres = ecart_type_robuste(pollue)
    variation_robuste = abs(robuste_apres - robuste_avant) / robuste_avant
    variation_classique = abs(np.std(pollue) - np.std(x)) / np.std(x)
    assert variation_robuste < 0.25
    # L'estimateur classique, lui, est multiplié par plusieurs.
    assert variation_classique > 10.0 * variation_robuste


def test_reference_robuste_utilise_la_periode_de_reference():
    x = np.concatenate([np.zeros(10), np.full(20, 50.0)])
    mu0, sigma0 = reference_robuste(x, n_reference=10)
    assert mu0 == pytest.approx(0.0)
    assert sigma0 > 0.0  # jamais nul, sinon les seuils s'effondrent


# --------------------------------------------------------------------------
# Séquence de discrimination
# --------------------------------------------------------------------------
def test_discrimination_derive_de_voie():
    essais = [_essai(i, 0.0, zero_avant=0.1, zero_apres=0.1) for i in range(10)]
    essais += [_essai(i, 4.0, zero_avant=0.1, zero_apres=0.2,
                      biais_gauche_estime=4.2, biais_droit_estime=0.1)
               for i in range(10, 16)]
    resultat = discriminer(essais, Reglages(), mu0=0.0, sigma0=1.0, indice_alarme=10)
    assert resultat.cause == "voie"
    assert "voie gauche" in resultat.phrase


def test_discrimination_derive_de_zero():
    """Résidu gauche/droite dans la bande, mais le zéro relevé a bougé."""
    essais = [_essai(i, 0.0, zero_avant=0.1, zero_apres=0.1) for i in range(10)]
    essais += [_essai(i, 0.5, zero_avant=5.0, zero_apres=5.4)
               for i in range(10, 16)]
    resultat = discriminer(essais, Reglages(), mu0=0.0, sigma0=1.0, indice_alarme=10)
    assert resultat.cause == "zero"


def test_discrimination_derive_thermique():
    """Écart nul en médiane mais entièrement piloté par la température."""
    temperatures = [40.0 + 40.0 * (i % 2) for i in range(20)]
    essais = [_essai(i, 0.05 * (t - 60.0), zero_avant=0.1, zero_apres=0.1,
                     temperature=t, pente_couple=0.0)
              for i, t in enumerate(temperatures)]
    resultat = discriminer(essais, Reglages(), mu0=0.0, sigma0=1.0, indice_alarme=10)
    assert resultat.cause == "thermique"


def test_discrimination_derive_de_sensibilite():
    essais = [_essai(i, 0.0, zero_avant=0.1, zero_apres=0.1, pente_couple=0.0)
              for i in range(10)]
    essais += [_essai(i, 0.6, zero_avant=0.1, zero_apres=0.2, temperature=60.0,
                      pente_couple=0.02) for i in range(10, 16)]
    resultat = discriminer(essais, Reglages(), mu0=0.0, sigma0=1.0, indice_alarme=10)
    assert resultat.cause == "sensibilite"


# --------------------------------------------------------------------------
# Verdict d'ensemble
# --------------------------------------------------------------------------
def test_verdict_conforme_sur_campagne_saine():
    # Série déterministe centrée : la référence robuste est bien estimée et
    # aucune des deux cartes ne doit franchir son seuil.
    motif = [0.4, -0.5, 0.6, -0.3, 0.2, -0.6, 0.5, -0.4, 0.3, -0.2]
    valeurs = (motif * 3)
    essais = [_essai(i, float(v), zero_avant=0.1, zero_apres=0.1)
              for i, v in enumerate(valeurs)]
    analyse = analyser(essais, Reglages(ecart_max_admissible=100.0))
    assert analyse.verdict.statut == "conforme"
    assert analyse.verdict.phrase.startswith("Aucune dérive détectée")


def test_verdict_non_conforme_au_dela_de_l_ecart_admissible():
    essais = [_essai(i, 0.0, zero_avant=0.1, zero_apres=0.1) for i in range(12)]
    essais.append(_essai(12, 30.0, zero_avant=0.1, zero_apres=0.2))
    analyse = analyser(essais, Reglages(ecart_max_admissible=15.0))
    assert analyse.verdict.statut == "non_conforme"
    assert "Revalider" in analyse.verdict.phrase


def test_verdict_indetermine_sous_trois_essais():
    analyse = analyser([_essai(0, 0.0), _essai(1, 0.0)])
    assert analyse.verdict.statut == "indetermine"


# --------------------------------------------------------------------------
# Verdict d'une fenêtre, pour le surlignage des zones de dérive
# --------------------------------------------------------------------------
def test_statut_fenetre_conforme_dans_la_bande():
    from vigie_couple.coeur.detection import statut_fenetre
    reglages = Reglages(ecart_max_admissible=15.0)
    assert statut_fenetre(0.5, mu0=0.0, sigma=1.0, reglages=reglages) == "conforme"
    # Juste sous la bande d'accord : encore conforme.
    assert statut_fenetre(1.9, mu0=0.0, sigma=1.0, reglages=reglages) == "conforme"


def test_statut_fenetre_vigilance_hors_bande_d_accord():
    from vigie_couple.coeur.detection import statut_fenetre
    reglages = Reglages(ecart_max_admissible=15.0)
    assert statut_fenetre(2.5, mu0=0.0, sigma=1.0, reglages=reglages) == "vigilance"
    assert statut_fenetre(-2.5, mu0=0.0, sigma=1.0, reglages=reglages) == "vigilance"
    # La bande est centrée sur μ₀, pas sur zéro.
    assert statut_fenetre(5.0, mu0=5.0, sigma=1.0, reglages=reglages) == "conforme"


def test_statut_fenetre_non_conforme_au_dela_de_l_ecart_admissible():
    from vigie_couple.coeur.detection import statut_fenetre
    reglages = Reglages(ecart_max_admissible=15.0)
    assert statut_fenetre(20.0, mu0=0.0, sigma=1.0, reglages=reglages) == "non_conforme"
    # L'écart admissible prime sur la bande, même si σ₀ est large.
    assert statut_fenetre(20.0, mu0=0.0, sigma=50.0,
                          reglages=reglages) == "non_conforme"


def test_echelle_fenetre_combine_les_deux_dispersions():
    """Une fenêtre isolée se juge sur σ₀ ET la dispersion interne à l'essai.

    Comparée au seul σ₀, une fenêtre d'un essai parfaitement sain sortirait de
    la bande une fois sur deux : les deux sources de variabilité s'ajoutent.
    """
    valeurs = [0.4, -0.5, 0.6, -0.3, 0.2, -0.6, 0.5, -0.4, 0.3, -0.2]
    essais = [_essai(i, float(v), zero_avant=0.1, zero_apres=0.1)
              for i, v in enumerate(valeurs * 3)]
    analyse = analyser(essais, Reglages(ecart_max_admissible=100.0))
    # _essai() fixe l'écart-type des fenêtres à 1,0 N·m.
    assert analyse.sigma_fenetre == pytest.approx(1.0)
    assert analyse.echelle_fenetre == pytest.approx(
        np.hypot(analyse.sigma0, 1.0))
    assert analyse.echelle_fenetre > analyse.sigma0


# --------------------------------------------------------------------------
# Import : un import complète la liste, il ne la remplace pas
# --------------------------------------------------------------------------
def _importable(indice: int, empreinte: str, jour: int) -> IndicateursEssai:
    essai = _essai(indice, 0.0)
    essai.date = f"2026-03-{jour:02d} 09:00"
    essai.empreinte = empreinte
    essai.chemin = f"/essais/{empreinte}.mf4"
    return essai


def test_deux_imports_successifs_donnent_la_somme():
    from vigie_couple.coeur.lecture_mf4 import fusionner_essais
    liste = []
    premier = [_importable(i, f"e{i}", i + 1) for i in range(5)]
    second = [_importable(i, f"e{i}", i + 1) for i in range(5, 12)]

    ajoutes, doublons = fusionner_essais(liste, premier)
    assert (ajoutes, doublons, len(liste)) == (5, 0, 5)

    ajoutes, doublons = fusionner_essais(liste, second)
    assert (ajoutes, doublons) == (7, 0)
    assert len(liste) == 12          # la somme, pas le dernier import seul

    # Troisième import des mêmes fichiers : rien ne s'ajoute.
    ajoutes, doublons = fusionner_essais(liste, premier + second)
    assert (ajoutes, doublons, len(liste)) == (0, 12, 12)


def test_import_dedoublonne_sur_le_contenu_pas_sur_le_chemin():
    """Un même fichier rangé à deux endroits ne doit compter qu'une fois."""
    from vigie_couple.coeur.lecture_mf4 import fusionner_essais
    original = _importable(0, "meme-contenu", 1)
    copie = _importable(0, "meme-contenu", 1)
    copie.chemin = "/autre/dossier/copie.mf4"
    liste = [original]
    ajoutes, doublons = fusionner_essais(liste, [copie])
    assert (ajoutes, doublons, len(liste)) == (0, 1, 1)


def test_import_replace_les_essais_dans_l_ordre_chronologique():
    """Un essai ancien importé après coup reprend sa place dans la série."""
    from vigie_couple.coeur.lecture_mf4 import fusionner_essais
    liste = []
    fusionner_essais(liste, [_importable(2, "c", 20), _importable(3, "d", 25)])
    fusionner_essais(liste, [_importable(0, "a", 3), _importable(1, "b", 10)])
    assert [e.empreinte for e in liste] == ["a", "b", "c", "d"]


# --------------------------------------------------------------------------
# Rupture de suivi : segments et remise à zéro des cartes
# --------------------------------------------------------------------------
def _serie_datee(valeurs) -> list[IndicateursEssai]:
    essais = []
    for indice, valeur in enumerate(valeurs):
        essai = _essai(indice, float(valeur))
        essai.date = f"2026-03-{indice + 1:02d} 09:00"
        essais.append(essai)
    return essais


def test_rupture_remet_les_statistiques_cumulees_a_zero():
    from vigie_couple.coeur.detection import Rupture
    motif = [0.4, -0.5, 0.6, -0.3, 0.2, -0.6, 0.5, -0.4, 0.3, -0.2]
    # Quinze essais sains, puis quinze décalés de +3 N·m.
    essais = _serie_datee([v for v in (motif + motif[:5])]
                          + [v + 3.0 for v in (motif + motif[:5])])
    reglages = Reglages(ecart_max_admissible=100.0)

    sans = analyser(essais, reglages)
    assert sans.verdict.statut == "vigilance"      # le décalage est détecté
    assert sans.cusum.c_plus[-1] > 0.0             # la somme s'est accumulée

    # Une rupture au 16ᵉ essai déclare que le décalage est la nouvelle normale.
    avec = analyser(essais, reglages,
                    ruptures=[Rupture(date="2026-03-16 00:00", motif="Réétalonnage")])
    assert len(avec.segments) == 2
    assert [s.debut for s in avec.segments] == [0, 15]

    # Après la rupture, les cartes valent exactement ce qu'elles vaudraient si
    # la série commençait là : rien de l'accumulation antérieure ne subsiste.
    segment = avec.segments[1]
    frais = carte_cusum(avec.x[15:], segment.mu0, segment.sigma0,
                        reglages.k_cusum, reglages.h_cusum)
    assert avec.cusum.c_plus[15:] == pytest.approx(frais.c_plus)
    assert avec.cusum.c_moins[15:] == pytest.approx(frais.c_moins)
    assert avec.cusum.c_plus[15] < sans.cusum.c_plus[15]     # l'ardoise est nette
    assert avec.verdict.statut == "conforme"
    # Les essais antérieurs restent tous dans l'analyse.
    assert len(avec.essais) == len(essais)


def test_rupture_recente_annonce_une_reference_en_constitution():
    from vigie_couple.coeur.detection import Rupture
    essais = _serie_datee([0.2, -0.3, 0.4, -0.1, 0.3, -0.4, 0.1, -0.2] * 3)
    analyse = analyser(essais, Reglages(n_reference=10),
                       ruptures=[Rupture(date="2026-03-21 00:00", motif="Réétalonnage")])
    assert analyse.verdict.statut == "constitution"
    assert "sur 10" in analyse.verdict.phrase
    assert "Réétalonnage" in analyse.verdict.phrase


def test_sans_rupture_le_comportement_est_inchange():
    """La nouvelle notion de segment ne doit rien changer par défaut."""
    essais = _serie_datee([0.4, -0.5, 0.6, -0.3, 0.2, -0.6, 0.5, -0.4, 0.3, -0.2] * 3)
    analyse = analyser(essais, Reglages(ecart_max_admissible=100.0))
    assert len(analyse.segments) == 1
    assert analyse.segments[0].debut == 0
    assert analyse.verdict.statut == "conforme"


# --------------------------------------------------------------------------
# Échelle du couple estimé : essieu total contre estimation par roue
# --------------------------------------------------------------------------
def test_couple_estime_total_essieu_compare_la_somme_des_deux_voies():
    """Un couple d'essieu total fait face à la SOMME des deux voies."""
    from vigie_couple.coeur.lecture_mf4 import comparaison_couple_estime
    gauche, droit = np.array([420.0]), np.array([400.0])
    estime = np.array([800.0])          # couple total des deux roues
    mesure, part_roue = comparaison_couple_estime(
        gauche, droit, estime, total_essieu=True)
    assert mesure == pytest.approx([820.0])            # 420 + 400
    assert (mesure - estime) == pytest.approx([20.0])  # résidu à pleine échelle
    # Chaque voie se compare à sa part, soit la moitié du total estimé.
    assert part_roue == pytest.approx([400.0])
    assert (gauche - part_roue) == pytest.approx([20.0])
    assert (droit - part_roue) == pytest.approx([0.0])


def test_couple_estime_par_roue_compare_la_moyenne():
    """Une estimation par roue fait face à la MOYENNE des deux voies."""
    from vigie_couple.coeur.lecture_mf4 import comparaison_couple_estime
    gauche, droit = np.array([420.0]), np.array([400.0])
    estime = np.array([400.0])          # couple d'une seule roue
    mesure, part_roue = comparaison_couple_estime(
        gauche, droit, estime, total_essieu=False)
    assert mesure == pytest.approx([410.0])            # (420 + 400) / 2
    assert (mesure - estime) == pytest.approx([10.0])
    assert part_roue == pytest.approx([400.0])         # l'estimé lui-même


def test_couple_estime_les_deux_echelles_ne_se_confondent_pas():
    """Le même essieu jugé aux deux échelles : le résidu diffère d'un facteur 2.

    C'est tout l'enjeu du réglage couple_estime_total_essieu : se tromper
    d'échelle double ou divise par deux le résidu, alors que l'écart maximal
    admissible, lui, est un seuil absolu en N·m.
    """
    from vigie_couple.coeur.lecture_mf4 import comparaison_couple_estime
    gauche, droit = np.array([420.0]), np.array([400.0])
    total = np.array([800.0])
    juste, _ = comparaison_couple_estime(gauche, droit, total, True)
    faux, _ = comparaison_couple_estime(gauche, droit, total, False)
    # Au bon réglage, l'essieu mesure 20 N·m de plus que le calculateur n'estime.
    assert float((juste - total)[0]) == pytest.approx(20.0)
    # Au mauvais, on compare une roue à un essieu : le résidu n'a plus de sens
    # et dépasse de très loin l'écart maximal admissible.
    assert abs(float((faux - total)[0])) > 10.0 * Reglages().ecart_max_admissible


# --------------------------------------------------------------------------
# Écriture du mappage : un nom de voie ne doit jamais casser config.yaml
# --------------------------------------------------------------------------
@pytest.mark.parametrize("nom", [
    "CRoue_Trans_G",        # cas courant
    "Couple: roue G",       # « : » — de la syntaxe pour YAML
    "*CRoue_G",             # « * » — référence d'ancre YAML
    "{CAN}Torque_G",        # « { » — début de dictionnaire
    "@Trans_G",             # « @ » — caractère réservé
    'Couple "G"',           # guillemets dans le nom lui-même
    "Couple #1 G",          # « # » — début de commentaire
])
def test_le_mappage_reste_relisible_quel_que_soit_le_nom_de_voie(tmp_path, nom):
    """Écrire un nom de voie ne doit pas rendre config.yaml illisible.

    Un config.yaml corrompu empêche l'application de redémarrer : le mappage
    doit accepter n'importe quel nom de signal d'acquisition.
    """
    import yaml
    from vigie_couple.coeur.lecture_mf4 import CHEMIN_CONFIG, enregistrer_mappage

    copie = tmp_path / "config.yaml"
    copie.write_text(CHEMIN_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    enregistrer_mappage(copie, {"couple_gauche": nom, "vitesse_lacet": ""})

    relu = yaml.safe_load(copie.read_text(encoding="utf-8"))
    assert relu["signaux"]["couple_gauche"] == nom
    assert relu["signaux"]["vitesse_lacet"] == ""
    # Le reste du fichier est intact : le patch est ciblé sur les voies.
    assert relu["detection"]["source"] == "voie_opposee"


# --------------------------------------------------------------------------
# Archivage : les indicateurs suivent la source du résidu
# --------------------------------------------------------------------------
def test_l_archivage_suit_la_source_du_residu(tmp_path):
    """Changer de source doit mettre à jour l'essai archivé, pas l'ignorer."""
    from vigie_couple.coeur.stockage import Stockage

    essai = _essai(0, 1.0)
    essai.residus["couple_estime"] = ResumeResidu(biais=99.0, ecart_type=2.0,
                                                  ecart_max=99.0)
    stockage = Stockage(tmp_path / "vigie.db")
    capteur = stockage.capteur({"numero_serie": "SN-TEST"})

    stockage.enregistrer_essais(capteur, [essai], "voie_opposee")
    stockage.enregistrer_essais(capteur, [essai], "couple_estime")
    lignes = stockage.cx.execute("SELECT biais FROM essai").fetchall()

    assert len(lignes) == 1                      # toujours un seul essai
    assert lignes[0]["biais"] == pytest.approx(99.0)   # et la bonne source
    stockage.fermer()


def test_modifier_capteur_n_efface_pas_les_champs_absents(tmp_path):
    """Un écran qui n'affiche pas tous les champs ne doit pas vider les autres."""
    from vigie_couple.coeur.stockage import Stockage

    stockage = Stockage(tmp_path / "vigie.db")
    capteur = stockage.capteur({
        "reference": "PCM16", "numero_serie": "SN-1", "arbre": "Gauche",
        "vehicule": "Mule", "date_service": "2025-01-15",
        "commentaire": "collage refait en mars"})

    # La fiche de vie n'affiche que quatre champs sur six.
    assert stockage.modifier_capteur(capteur, {
        "reference": "PCM16 bis", "numero_serie": "SN-1",
        "arbre": "Gauche", "vehicule": "Mule"})

    infos = stockage.infos_capteur(capteur)
    assert infos["reference"] == "PCM16 bis"
    assert infos["date_service"] == "2025-01-15"          # préservés
    assert infos["commentaire"] == "collage refait en mars"
    assert len(stockage.capteurs()) == 1                  # pas de second capteur
    stockage.fermer()


def test_modifier_capteur_corrige_le_numero_de_serie_sans_detacher_l_historique(tmp_path):
    """Corriger la série renomme le capteur : les essais restent les siens."""
    from vigie_couple.coeur.stockage import Stockage

    stockage = Stockage(tmp_path / "vigie.db")
    capteur = stockage.capteur({"reference": "PCM16", "numero_serie": "SN-1"})
    stockage.enregistrer_essais(capteur, [_essai(0, 0.0)])

    assert stockage.modifier_capteur(capteur, {"numero_serie": "SN-2"})
    assert len(stockage.capteurs()) == 1
    assert stockage.infos_capteur(capteur)["numero_serie"] == "SN-2"
    restants = stockage.cx.execute(
        "SELECT COUNT(*) AS n FROM essai WHERE capteur_id = ?", (capteur,)).fetchone()
    assert restants["n"] == 1

    # En revanche, deux capteurs ne peuvent pas porter la même série.
    autre = stockage.capteur({"numero_serie": "SN-3"})
    assert stockage.modifier_capteur(autre, {"numero_serie": "SN-2"}) is False
    assert stockage.infos_capteur(autre)["numero_serie"] == "SN-3"
    stockage.fermer()


# --------------------------------------------------------------------------
# Arrêts exploitables : un arrêt en pente, rapport engagé, n'est pas un zéro
# --------------------------------------------------------------------------
def _scene_arret(n=100, rapport=None, pente=None, fse=None):
    """Un essai fictif entièrement à l'arrêt, avec ses voies d'état."""
    from vigie_couple.coeur.lecture_mf4 import PHASES
    phases = np.full(n, PHASES.index("arrêt"), dtype=int)
    voies = {} if pente is None else {"pente": np.full(n, float(pente))}
    etats = {}
    if rapport is not None:
        etats["rapport"] = np.full(n, rapport)
    if fse is not None:
        etats["frein_stationnement"] = np.full(n, fse)
    return etats, voies, phases


def test_arret_au_neutre_est_exploitable():
    from vigie_couple.coeur.lecture_mf4 import masque_arret_zero
    etats, voies, phases = _scene_arret(rapport=0.0, pente=0.0)
    masque = masque_arret_zero(etats, voies, phases,
                               {"rapport_neutre": "0", "pente_max_arret_pourcent": 2.0})
    assert masque.all()


def test_arret_rapport_engage_est_rejete():
    """Le cas visé : arrêt en pente, rapport engagé, l'arbre est en torsion."""
    from vigie_couple.coeur.lecture_mf4 import masque_arret_zero
    etats, voies, phases = _scene_arret(rapport=2.0, pente=8.0)
    masque = masque_arret_zero(etats, voies, phases,
                               {"rapport_neutre": "0", "pente_max_arret_pourcent": 2.0})
    assert not masque.any()


def test_arret_au_neutre_mais_en_pente_est_rejete_sans_frein():
    from vigie_couple.coeur.lecture_mf4 import masque_arret_zero
    etats, voies, phases = _scene_arret(rapport=0.0, pente=8.0)
    masque = masque_arret_zero(etats, voies, phases,
                               {"rapport_neutre": "0", "pente_max_arret_pourcent": 2.0})
    assert not masque.any()


def test_le_frein_de_stationnement_rattrape_un_arret_en_pente():
    """Frein serré : c'est lui qui retient le véhicule, pas la transmission."""
    from vigie_couple.coeur.lecture_mf4 import masque_arret_zero
    etats, voies, phases = _scene_arret(rapport=0.0, pente=8.0, fse=1.0)
    param = {"rapport_neutre": "0", "fse_serre": "1",
             "pente_max_arret_pourcent": 2.0}
    assert masque_arret_zero(etats, voies, phases, param).all()
    # Mais le neutre reste exigé, frein serré ou non.
    etats_engage, voies2, phases2 = _scene_arret(rapport=3.0, pente=8.0, fse=1.0)
    assert not masque_arret_zero(etats_engage, voies2, phases2, param).any()


def test_voies_d_etat_non_mappees_laissent_le_comportement_inchange():
    """Sans ces voies, tout arrêt reste exploitable : la démo ne change pas."""
    from vigie_couple.coeur.lecture_mf4 import masque_arret_zero
    etats, voies, phases = _scene_arret()
    assert masque_arret_zero(etats, voies, phases, {}).all()


def test_valeur_etat_accepte_le_texte_et_le_nombre():
    """Un rapport codé « N » ou codé « 0 » se désigne de la même façon."""
    from vigie_couple.coeur.lecture_mf4 import valeur_etat
    assert valeur_etat(np.array(["N", "1", "N"]), "N").tolist() == [True, False, True]
    assert valeur_etat(np.array([0.0, 2.0, 0.0]), "0").tolist() == [True, False, True]
    assert valeur_etat(np.array([0.0, 2.0]), "0,0").tolist() == [True, False]
    # Choix vide ou voie absente : critère sauté, jamais d'exclusion muette.
    assert valeur_etat(np.array([0.0]), "") is None
    assert valeur_etat(None, "0") is None
    assert valeur_etat(np.array([0.0]), "N") is None


def test_une_voie_d_etat_est_maintenue_jamais_interpolee():
    """Entre la 2ᵉ et la 3ᵉ, un rapport interpolé vaudrait « 2,4 », qui n'existe pas."""
    from vigie_couple.coeur.lecture_mf4 import _maintien
    ts = np.array([0.0, 1.0, 2.0])
    rapports = np.array([2.0, 3.0, 4.0])
    t = np.array([0.0, 0.5, 0.99, 1.0, 1.5, 2.0])
    obtenu = _maintien(t, ts, rapports)
    assert obtenu.tolist() == [2.0, 2.0, 2.0, 3.0, 3.0, 4.0]
    assert set(obtenu) <= {2.0, 3.0, 4.0}   # aucune valeur intermédiaire inventée


def test_le_mappage_ecrit_les_valeurs_d_etat_dans_la_bonne_section(tmp_path):
    """rapport_neutre est un réglage de traitement, pas un nom de voie."""
    import yaml
    from vigie_couple.coeur.lecture_mf4 import CHEMIN_CONFIG, enregistrer_mappage

    copie = tmp_path / "config.yaml"
    copie.write_text(CHEMIN_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    enregistrer_mappage(copie,
                        {"rapport": "BV_RapportEngage", "frein_stationnement": "FSE_Etat"},
                        {"rapport_neutre": "N", "fse_serre": "serré"})

    relu = yaml.safe_load(copie.read_text(encoding="utf-8"))
    assert relu["signaux"]["rapport"] == "BV_RapportEngage"
    assert relu["signaux"]["frein_stationnement"] == "FSE_Etat"
    assert relu["traitement"]["rapport_neutre"] == "N"
    assert relu["traitement"]["fse_serre"] == "serré"
    # Les valeurs d'état ne doivent pas atterrir parmi les noms de voies.
    assert "rapport_neutre" not in relu["signaux"]
    assert "fse_serre" not in relu["signaux"]
    assert relu["detection"]["source"] == "voie_opposee"
