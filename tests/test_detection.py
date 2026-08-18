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
