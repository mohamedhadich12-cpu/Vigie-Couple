# -*- coding: utf-8 -*-
"""Générateur du jeu de démonstration : 30 essais synthétiques au format MF4.

Campagne construite pour montrer la détection sans aucune donnée réelle :

* essais 1 à 12  : capteur sain, résidu centré sur zéro ;
* essais 13 à 22 : dérive de zéro lente sur la voie gauche, amplitude finale
  de l'ordre de 1,5 σ du résidu essai par essai ;
* essais 23 à 30 : dérive de sensibilité de 2 % sur la même voie, qui s'ajoute
  à la précédente ;
* essai 18       : valeur aberrante isolée, pour vérifier que l'estimateur
  robuste ne se laisse pas tirer par elle.

Usage : python donnees_demo/generateur.py [dossier_de_sortie]
"""
from __future__ import annotations

import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
from asammdf import MDF, Signal

# Véhicule d'essais et chaîne de mesure (transmission instrumentée, ±1 500 N·m).
MASSE_KG = 1800.0
RAYON_ROUE_M = 0.33
BRUIT_CAPTEUR = 4.5          # N·m efficaces, soit 0,3 % de l'étendue
SIGMA_ESSAI = 0.8            # N·m, reproductibilité d'un essai à l'autre
DERIVE_ZERO_FINALE = 1.5 * SIGMA_ESSAI   # amplitude finale de la dérive de zéro
DERIVE_SENSIBILITE = 0.02                # 2 % de la lecture
ABERRANT_NM = 7.0            # décalage de l'essai 18 seul
FREQ_COUPLE = 50.0           # Hz, télémétrie Manner PCM16
FREQ_CAN = 20.0              # Hz, voies calculateur
FREQ_TEMP = 2.0              # Hz, température du capteur

# Parcours de la boucle d'essai : (durée en s, vitesse visée en km/h, pente en %).
# Les côtes donnent des paliers de couple élevé à vitesse stabilisée, seule
# façon d'obtenir des fenêtres exploitables au-delà de 200 N·m.
PROFIL = [(20, 0, 0), (15, 55, 0), (30, 55, 0), (10, 55, 6), (35, 55, 6),
          (10, 50, 11), (30, 50, 11), (10, 45, 15), (30, 45, 15),
          (15, 95, 0), (35, 95, 0), (10, 110, 0), (25, 110, 0),
          (20, 0, 0), (20, 0, 0)]
PESANTEUR = 9.81


def parcours(rng: np.random.Generator, pas: float):
    """Base de temps, vitesse lissée (km/h) et pente de la piste (%)."""
    temps, vitesses, pentes = [0.0], [0.0], [0.0]
    for duree, cible, pente in PROFIL:
        duree *= float(rng.uniform(0.95, 1.05))
        cible *= float(rng.uniform(0.98, 1.02)) if cible else 1.0
        temps.append(temps[-1] + duree)
        vitesses.append(cible)
        pentes.append(pente)
    t = np.arange(0.0, temps[-1], pas)
    v = np.interp(t, temps, vitesses)
    pente = np.interp(t, temps, pentes)
    # Lissage sur 2 s : évite des accélérations irréalistes aux ruptures.
    largeur = max(1, int(2.0 / pas))
    noyau = np.ones(largeur) / largeur
    v = np.convolve(v, noyau, mode="same")
    pente = np.convolve(pente, noyau, mode="same")
    return t, np.clip(v, 0.0, None), pente


def couple_nominal(t: np.ndarray, v_kmh: np.ndarray, pente: np.ndarray) -> np.ndarray:
    """Couple à la roue attendu (N·m par roue) déduit du parcours."""
    v = v_kmh / 3.6
    a = np.gradient(v, t)
    resistance = 220.0 + 0.42 * v ** 2          # roulement et aérodynamique
    gravite = MASSE_KG * PESANTEUR * pente / 100.0
    effort = MASSE_KG * a + np.where(v > 0.3, resistance + gravite, 0.0)
    couple = 0.5 * effort * RAYON_ROUE_M
    return np.clip(couple, -1500.0, 1500.0)


def defauts(indice: int) -> tuple[float, float, float]:
    """Rend (dérive de zéro, dérive de sensibilité, aberrant) pour l'essai n° indice."""
    zero = sensibilite = aberrant = 0.0
    if 13 <= indice <= 22:                       # montée progressive du zéro
        zero = DERIVE_ZERO_FINALE * (indice - 12) / 10.0
    elif indice >= 23:                           # zéro figé, sensibilité en plus
        zero = DERIVE_ZERO_FINALE
        sensibilite = DERIVE_SENSIBILITE
    if indice == 18:
        aberrant = ABERRANT_NM
    return zero, sensibilite, aberrant


def construire_essai(indice: int, debut: datetime, rng: np.random.Generator) -> MDF:
    """Fabrique un essai complet, voies capteur et voies calculateur."""
    t_c, v_c, pente = parcours(rng, 1.0 / FREQ_COUPLE)
    nominal = couple_nominal(t_c, v_c, pente)
    zero_derive, sensibilite, aberrant = defauts(indice)

    # Effet essai : montage, température ambiante, conditions de piste.
    offset_gauche = float(rng.normal(0.0, SIGMA_ESSAI))
    offset_droit = float(rng.normal(0.0, SIGMA_ESSAI * 0.4))
    dissymetrie = 1.0 + float(rng.normal(0.0, 0.0015))   # transmission réelle

    gauche = (nominal * (1.0 + sensibilite) + offset_gauche + zero_derive + aberrant
              + rng.normal(0.0, BRUIT_CAPTEUR, t_c.size))
    droit = (nominal * dissymetrie + offset_droit
             + rng.normal(0.0, BRUIT_CAPTEUR, t_c.size))

    t_can = np.arange(0.0, t_c[-1], 1.0 / FREQ_CAN)
    v_can = np.interp(t_can, t_c, v_c)
    nom_can = np.interp(t_can, t_c, nominal)
    # Le couple estimé lit 0,5 % bas et porte sa propre erreur de modèle.
    estime = nom_can * 0.995 + 2.0 + rng.normal(0.0, 9.0, t_can.size)
    demande = np.where(nom_can > 0.0, nom_can * 1.01, 0.0) + rng.normal(0.0, 6.0, t_can.size)
    pedale = np.clip(nom_can / 7.0, 0.0, 100.0) * (v_can > 0.5)

    t_temp = np.arange(0.0, t_c[-1], 1.0 / FREQ_TEMP)
    ambiante = 18.0 + float(rng.uniform(-6.0, 12.0))
    temperature = ambiante + 32.0 * (1.0 - np.exp(-t_temp / 90.0))

    # Ces noms sont repris dans MAPPAGE_DEMO (coeur/lecture_mf4.py) : les deux
    # listes doivent rester identiques.
    voies = [
        Signal(gauche, t_c, name="CRoue_Trans_G", unit="N.m"),
        Signal(droit, t_c, name="CRoue_Trans_D", unit="N.m"),
        Signal(estime, t_can, name="TqWhlEst_tqWhlPt_RTE", unit="N.m"),
        Signal(demande, t_can, name="TqSpl_tqWhlFrntReq_RTE", unit="N.m"),
        Signal(v_can, t_can, name="Veh_spdVeh_RTE", unit="km/h"),
        Signal(pedale, t_can, name="AcP_rAcc_P_RTE", unit="%"),
        Signal(temperature, t_temp, name="Temp_Capteur_G", unit="degC"),
    ]
    mdf = MDF(version="4.10")
    mdf.append(voies, comment=f"Vigie Couple - essai de démonstration {indice:02d}")
    mdf.header.start_time = debut
    return mdf


def seuil_etalonnage_demo():
    """Étalonnage de démonstration inscrit dans la fiche de vie, s'il n'y en a aucun.

    Sans lui, la tuile « jours avant échéance » de l'écran Surveillance reste
    vide : le jeu de démonstration doit se suffire à lui-même.

    Il s'inscrit sur le **capteur de démonstration**, celui-là même sur lequel
    le bouton bascule, et non sur le capteur de config.yaml : sinon l'étalonnage
    et les trente essais atterrissent sur deux capteurs différents, et la tuile
    reste vide malgré tout.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        from vigie_couple.coeur.lecture_mf4 import CAPTEUR_DEMO
        from vigie_couple.coeur.stockage import Stockage
    except ImportError:
        return
    stockage = Stockage()
    capteur = stockage.capteur(CAPTEUR_DEMO)
    if stockage.dernier_etalonnage(capteur) is None:
        jour = date.today() - timedelta(days=280)   # échéance dans 90 jours
        stockage.ajouter_etalonnage(capteur, jour.isoformat(), 7.5, "CERT-2025-118")
        print(f"  étalonnage de démonstration inscrit au {jour:%d/%m/%Y}")
    stockage.fermer()


def generer(dossier: Path, nombre: int = 30) -> list[Path]:
    """Écrit les fichiers MF4 et rend la liste des chemins produits."""
    dossier.mkdir(parents=True, exist_ok=True)
    for ancien in sorted(dossier.glob("essai_*.mf4")):   # évite les doublons
        ancien.unlink()
        print(f"  ancien fichier retiré : {ancien.name}")
    # Campagne calée sur la date du jour : elle reste crédible quand on la rejoue.
    premier = datetime.combine(date.today() - timedelta(days=60), time(8, 30))
    chemins = []
    for indice in range(1, nombre + 1):
        rng = np.random.default_rng(2026 + indice)
        # Un essai par jour ouvré, à une heure légèrement variable.
        debut = premier + timedelta(days=int(indice * 1.4), hours=indice % 5)
        chemin = dossier / f"essai_{indice:02d}_{debut:%Y%m%d}.mf4"
        mdf = construire_essai(indice, debut, rng)
        mdf.save(chemin, overwrite=True)
        mdf.close()
        chemins.append(chemin)
        print(f"  essai {indice:02d}  {chemin.name}")
    return chemins


if __name__ == "__main__":
    sortie = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "essais"
    print(f"Génération du jeu de démonstration dans {sortie}")
    fichiers = generer(sortie)
    seuil_etalonnage_demo()
    print(f"{len(fichiers)} essais écrits.")
