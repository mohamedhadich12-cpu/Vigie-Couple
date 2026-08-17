# -*- coding: utf-8 -*-
"""Cœur de calcul de Vigie Couple : résidu, cartes de contrôle, discrimination.

Ce module ne dépend d'aucune bibliothèque graphique : il est testable seul
(voir tests/test_detection.py). Les identifiants restent en ASCII pour rester
portables, les commentaires sont en français.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Mise à l'échelle du MAD pour retrouver un écart-type gaussien.
FACTEUR_MAD = 1.4826

# Sources de résidu, par ordre de fiabilité décroissante.
SOURCES = {
    "voie_opposee": "Voie opposée (gauche − droite)",
    "zero": "Zéro à couple nul",
    "couple_estime": "Couple estimé (calculateur)",
}


@dataclass
class Reglages:
    """Paramètres de réglage exposés dans le panneau latéral de l'écran 2."""

    lambda_ewma: float = 0.10
    limite_L: float = 2.7
    k_cusum: float = 0.5
    h_cusum: float = 5.0
    n_reference: int = 10
    source: str = "voie_opposee"
    ecart_max_admissible: float = 15.0  # N·m, soit 1 % de l'étendue 1 500 N·m
    zero_vigilance: float = 3.0         # N·m, seuil de vigilance sur le zéro
    zero_majeur: float = 10.0           # N·m, dérive de zéro majeure
    pente_vigilance: float = 0.005      # N·m de résidu par N·m de couple (0,5 %)
    correlation_vigilance: float = 0.70


@dataclass
class ResumeResidu:
    """Indicateurs du résidu d'un essai, pour une source donnée."""

    biais: float = 0.0
    ecart_type: float = 0.0
    ecart_max: float = 0.0
    n_points: int = 0


@dataclass
class IndicateursEssai:
    """Tout ce qu'un essai apporte à la surveillance : une ligne par essai."""

    nom: str = ""
    date: str = ""            # ISO court : « 2026-03-14 09:12 »
    duree_s: float = 0.0
    couple_max: float = 0.0
    distance_km: float = 0.0
    residus: dict[str, ResumeResidu] = field(default_factory=dict)
    # Éléments utilisés par la séquence de discrimination.
    biais_gauche_estime: float | None = None  # voie gauche face au couple estimé
    biais_droit_estime: float | None = None   # voie droite face au couple estimé
    zero_avant: float | None = None
    zero_apres: float | None = None
    temperature: float | None = None
    pente_couple: float | None = None         # sensibilité du résidu au couple
    chemin: str = ""

    def resume(self, source: str) -> ResumeResidu:
        """Résumé du résidu pour la source demandée, avec repli sur la voie opposée."""
        return (self.residus.get(source)
                or self.residus.get("voie_opposee")
                or ResumeResidu())


@dataclass
class ResultatCusum:
    c_plus: np.ndarray
    c_moins: np.ndarray
    H: float
    K: float
    alarmes: np.ndarray
    premiere_alarme: int | None


@dataclass
class ResultatEwma:
    z: np.ndarray
    limite_sup: np.ndarray
    limite_inf: np.ndarray
    alarmes: np.ndarray
    premiere_alarme: int | None


@dataclass
class Discrimination:
    cause: str      # identifiant technique
    phrase: str     # une phrase, affichée sous le verdict


@dataclass
class Verdict:
    statut: str     # indetermine | conforme | vigilance | non_conforme
    libelle: str
    icone: str
    phrase: str
    indice_essai: int | None = None


@dataclass
class Analyse:
    """Résultat complet, consommé tel quel par l'écran Surveillance."""

    essais: list[IndicateursEssai]
    source: str
    x: np.ndarray
    mu0: float
    sigma0: float
    cusum: ResultatCusum
    ewma: ResultatEwma
    verdict: Verdict
    discrimination: Discrimination
    reglages: Reglages
    sigma_fenetre: float = 0.0   # dispersion des fenêtres à l'intérieur d'un essai

    @property
    def echelle_fenetre(self) -> float:
        """Écart-type attendu d'une fenêtre isolée face à la référence μ₀.

        Deux sources de dispersion s'additionnent : celle d'un essai à l'autre
        (σ₀) et celle des fenêtres à l'intérieur d'un essai.
        """
        return float(np.hypot(self.sigma0, self.sigma_fenetre))


# --- Estimation robuste de la référence ---
def ecart_type_robuste(x) -> float:
    """Écart-type estimé par le MAD mis à l'échelle : insensible aux aberrants."""
    v = _propre(x)
    if v.size == 0:
        return 0.0
    return float(FACTEUR_MAD * np.median(np.abs(v - np.median(v))))


def reference_robuste(x, n_reference: int = 10) -> tuple[float, float]:
    """Estime (μ₀, σ₀) sur la période de référence par médiane et MAD.

    Un estimateur classique serait tiré par un essai aberrant et fausserait
    tous les seuils des cartes de contrôle.
    """
    v = _propre(x)
    if v.size == 0:
        return 0.0, 0.0
    base = v[:max(3, n_reference)] if v.size > 3 else v
    mu0 = float(np.median(base))
    sigma0 = ecart_type_robuste(base)
    if sigma0 <= 0.0:  # série constante ou quasi constante
        sigma0 = float(np.std(base)) or 1e-9
    return mu0, sigma0


def _propre(x) -> np.ndarray:
    v = np.asarray(x, dtype=float).ravel()
    return v[np.isfinite(v)]


def _nb(valeur: float, decimales: int = 1) -> str:
    """Nombre signé à la française, pour les phrases affichées à l'opérateur."""
    return f"{valeur:+.{decimales}f}".replace(".", ",")


# --- Cartes de contrôle à mémoire ---
def carte_cusum(x, mu0: float, sigma0: float, k: float = 0.5,
                h: float = 5.0) -> ResultatCusum:
    """Somme cumulée tabulaire. k = 0,5 et h = 5 donnent une ARL₀ ≈ 465 essais."""
    v = np.asarray(x, dtype=float).ravel()
    K = k * sigma0
    H = h * sigma0
    c_plus = np.zeros(v.size)
    c_moins = np.zeros(v.size)
    haut = bas = 0.0
    for i, xi in enumerate(v):
        if not np.isfinite(xi):
            xi = mu0
        haut = max(0.0, xi - (mu0 + K) + haut)
        bas = max(0.0, (mu0 - K) - xi + bas)
        c_plus[i] = haut
        c_moins[i] = bas
    alarmes = (c_plus > H) | (c_moins > H)
    return ResultatCusum(c_plus, c_moins, H, K, alarmes, _premiere(alarmes))


def carte_ewma(x, mu0: float, sigma0: float, lam: float = 0.10,
               L: float = 2.7) -> ResultatEwma:
    """Moyenne mobile exponentielle, limites avec terme transitoire.

    Le terme (1 − (1 − λ)^(2i)) est indispensable : sans lui les limites sont
    trop larges en début de série et la détection précoce est manquée
    précisément là où elle compte.
    """
    v = np.asarray(x, dtype=float).ravel()
    z = np.zeros(v.size)
    precedent = mu0
    for i, xi in enumerate(v):
        if not np.isfinite(xi):
            xi = precedent
        precedent = lam * xi + (1.0 - lam) * precedent
        z[i] = precedent
    rang = np.arange(1, v.size + 1)
    facteur = np.sqrt((lam / (2.0 - lam)) * (1.0 - (1.0 - lam) ** (2 * rang)))
    demi = L * sigma0 * facteur
    limite_sup = mu0 + demi
    limite_inf = mu0 - demi
    alarmes = (z > limite_sup) | (z < limite_inf)
    return ResultatEwma(z, limite_sup, limite_inf, alarmes, _premiere(alarmes))


def _premiere(alarmes: np.ndarray) -> int | None:
    indices = np.flatnonzero(alarmes)
    return int(indices[0]) if indices.size else None


# --- Discrimination : du plus indépendant du modèle au plus dépendant ---
def discriminer(essais: list[IndicateursEssai], reglages: Reglages,
                mu0: float, sigma0: float,
                indice_alarme: int | None = None) -> Discrimination:
    """Rend la première conclusion atteinte par la séquence de tests."""
    if len(essais) < 3:
        return Discrimination("indetermine", "Série trop courte pour conclure.")

    depart = indice_alarme if indice_alarme is not None else max(0, len(essais) - 5)
    recents = essais[depart:] or essais[-1:]
    reference = essais[:reglages.n_reference]

    # 1. Écart gauche / droite : ne dépend d'aucun modèle.
    ecart = (_mediane([e.resume("voie_opposee").biais for e in recents]) or 0.0) - mu0
    if abs(ecart) > 2.0 * max(sigma0, 1e-9):
        voie = _voie_suspecte(recents, ecart)
        return Discrimination(
            "voie",
            f"Écart gauche/droite de {_nb(ecart)} N·m : dérive de la {voie}.")

    # 2. Dérive du zéro relevé à couple nul.
    derive = _derive_zero(recents, reference)
    if derive is not None and abs(derive) > reglages.zero_vigilance:
        return Discrimination(
            "zero",
            f"Zéro déplacé de {_nb(derive)} N·m : dérive de zéro confirmée.")

    # 3. Dépendance à la température.
    r_temp = _correlation([e.temperature for e in essais],
                          [e.resume(reglages.source).biais for e in essais])
    if r_temp is not None and abs(r_temp) >= reglages.correlation_vigilance:
        return Discrimination(
            "thermique",
            f"Écart corrélé à la température (r = {_nb(r_temp, 2)}) : "
            "dérive thermique.")

    # 4. Dépendance au niveau de couple.
    pente = _mediane([e.pente_couple for e in recents])
    if pente is not None and abs(pente) > reglages.pente_vigilance:
        return Discrimination(
            "sensibilite",
            f"Écart proportionnel au couple ({_nb(pente * 100)} %) : "
            "dérive de sensibilité plutôt que de zéro.")
    r_couple = _correlation([e.couple_max for e in essais],
                            [e.resume(reglages.source).biais for e in essais])
    if r_couple is not None and abs(r_couple) >= reglages.correlation_vigilance:
        return Discrimination(
            "sensibilite",
            f"Écart croissant avec le couple (r = {_nb(r_couple, 2)}) : "
            "dérive de sensibilité plutôt que de zéro.")

    # 5. Aucun des précédents.
    return Discrimination(
        "inexplique",
        "Écart non expliqué : programmer un étalonnage de vérification.")


def _voie_suspecte(recents: list[IndicateursEssai], ecart: float) -> str:
    """La voie qui s'écarte le plus du couple estimé est la voie suspecte."""
    gauche = _mediane([e.biais_gauche_estime for e in recents])
    droit = _mediane([e.biais_droit_estime for e in recents])
    if gauche is not None and droit is not None:
        return "voie gauche" if abs(gauche) >= abs(droit) else "voie droite"
    # À défaut, le signe du résidu gauche − droite désigne la voie haute.
    return "voie gauche" if ecart > 0 else "voie droite"


def _derive_zero(recents: list[IndicateursEssai],
                 reference: list[IndicateursEssai]) -> float | None:
    """Déplacement du zéro après essai par rapport à la période de référence."""
    apres = _mediane([e.zero_apres for e in recents])
    if apres is None:
        return None
    base = _mediane([e.zero_avant for e in reference])
    if base is None:
        base = _mediane([e.zero_apres for e in reference]) or 0.0
    return float(apres - base)


def _mediane(valeurs) -> float | None:
    v = _propre([x for x in valeurs if x is not None])
    return float(np.median(v)) if v.size else None


def _correlation(a, b) -> float | None:
    """Coefficient de Pearson sur les couples complètement renseignés."""
    paires = [(x, y) for x, y in zip(a, b)
              if x is not None and y is not None
              and np.isfinite(x) and np.isfinite(y)]
    if len(paires) < 6:
        return None
    xa = np.array([p[0] for p in paires], dtype=float)
    xb = np.array([p[1] for p in paires], dtype=float)
    if np.std(xa) < 1e-12 or np.std(xb) < 1e-12:
        return None
    return float(np.corrcoef(xa, xb)[0, 1])


# --- Verdict et analyse complète ---
def analyser(essais: list[IndicateursEssai],
             reglages: Reglages | None = None) -> Analyse:
    """Enchaîne référence robuste, cartes de contrôle, verdict et discrimination."""
    reglages = reglages or Reglages()
    x = np.array([e.resume(reglages.source).biais for e in essais], dtype=float)
    mu0, sigma0 = reference_robuste(x, reglages.n_reference)
    cusum = carte_cusum(x, mu0, sigma0, reglages.k_cusum, reglages.h_cusum)
    ewma = carte_ewma(x, mu0, sigma0, reglages.lambda_ewma, reglages.limite_L)

    verdict = _verdict(essais, reglages, cusum, ewma)
    indice = verdict.indice_essai if verdict.statut != "conforme" else None
    discrimination = (discriminer(essais, reglages, mu0, sigma0, indice)
                      if verdict.statut in ("vigilance", "non_conforme")
                      else Discrimination("aucune", ""))
    # Dispersion typique des fenêtres, relevée sur la période de référence.
    sigma_fenetre = _mediane([e.resume(reglages.source).ecart_type
                              for e in essais[:reglages.n_reference]]) or 0.0
    return Analyse(essais, reglages.source, x, mu0, sigma0, cusum, ewma,
                   verdict, discrimination, reglages, sigma_fenetre)


def _verdict(essais: list[IndicateursEssai], reglages: Reglages,
             cusum: ResultatCusum, ewma: ResultatEwma) -> Verdict:
    n = len(essais)
    if n < 3:
        return Verdict("indetermine", "En attente", "•",
                       "Chargez au moins trois essais pour établir la référence.")

    # Non conforme : écart supérieur à l'admissible ou dérive de zéro majeure.
    for i, essai in enumerate(essais):
        resume = essai.resume(reglages.source)
        depasse = resume.ecart_max > reglages.ecart_max_admissible
        zero = essai.zero_apres
        zero_majeur = zero is not None and abs(zero) > reglages.zero_majeur
        if depasse or zero_majeur:
            return Verdict(
                "non_conforme", "Non conforme", "✕",
                "Mesure non exploitable. Revalider les essais depuis le "
                f"{date_courte(essai.date)}.", i)

    alarmes = [a for a in (cusum.premiere_alarme, ewma.premiere_alarme)
               if a is not None]
    if alarmes:
        i = min(alarmes)
        return Verdict(
            "vigilance", "Vigilance", "!",
            f"Dérive naissante détectée à l'essai du {date_courte(essais[i].date)}. "
            "Étalonnage de vérification à programmer.", i)

    return Verdict("conforme", "Conforme", "✔",
                   f"Aucune dérive détectée sur les {n} derniers essais.")


def statut_fenetre(residu: float, mu0: float, sigma: float,
                   reglages: Reglages) -> str:
    """Verdict d'une seule fenêtre de mesure, à l'intérieur d'un essai.

    Sert à surligner les zones de dérive dans la visualisation d'un essai.
    « sigma » est l'échelle propre à une fenêtre isolée — voir
    Analyse.echelle_fenetre — et non σ₀, qui mesure la dispersion d'un essai
    à l'autre : une fenêtre comparée à σ₀ sortirait de la bande une fois sur
    deux sur un essai parfaitement sain.
    """
    if abs(residu) > reglages.ecart_max_admissible:
        return "non_conforme"
    if abs(residu - mu0) > 1.96 * max(sigma, 1e-9):
        return "vigilance"
    return "conforme"


def date_courte(date: str) -> str:
    """« 2026-03-14 09:12 » devient « 14/03/2026 »."""
    texte = (date or "").strip()
    if len(texte) >= 10 and texte[4] == "-" and texte[7] == "-":
        return f"{texte[8:10]}/{texte[5:7]}/{texte[0:4]}"
    return texte or "date inconnue"


def horodatage(date: str) -> str:
    """« 2026-03-14 09:12 » devient « 14/03/2026 09:12 »."""
    heure = (date or "")[11:16]
    return f"{date_courte(date)} {heure}".strip()


def essais_depuis_conforme(analyse: Analyse) -> int:
    """Nombre d'essais depuis le dernier essai sans alarme sur les deux cartes."""
    alarmes = analyse.cusum.alarmes | analyse.ewma.alarmes
    if not alarmes.any():
        return 0
    sains = np.flatnonzero(~alarmes)
    dernier = int(sains[-1]) if sains.size else -1
    return len(analyse.essais) - dernier - 1
