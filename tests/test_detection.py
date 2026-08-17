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
