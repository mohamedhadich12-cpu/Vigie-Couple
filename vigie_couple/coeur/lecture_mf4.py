# -*- coding: utf-8 -*-
"""Lecture des acquisitions MF4, segmentation en phases et calcul des résidus.

Le mappage des voies vient de config.yaml : aucun nom de signal en dur ici.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml
from asammdf import MDF
from scipy import stats

from .detection import IndicateursEssai, Reglages, ResumeResidu

CHEMIN_CONFIG = Path(__file__).resolve().parents[1] / "config.yaml"

# Phases d'un essai, dans l'ordre d'affichage.
PHASES = ("arrêt", "traction", "freinage récupératif", "transitoire")


def charger_config(chemin: str | Path | None = None) -> dict:
    """Charge config.yaml. Les chemins sont résolus de façon portable (Windows compris)."""
    fichier = Path(chemin) if chemin else CHEMIN_CONFIG
    with open(fichier, "r", encoding="utf-8") as flux:
        return yaml.safe_load(flux) or {}


def enregistrer_mappage(chemin_config: str | Path, mappage: dict[str, str]) -> None:
    """Réécrit les voies choisies dans config.yaml, sans toucher au reste du fichier.

    Un patch ciblé ligne à ligne plutôt qu'un ré-export YAML complet : les
    commentaires et la mise en forme du fichier sont préservés.
    """
    chemin_config = Path(chemin_config)
    texte = chemin_config.read_text(encoding="utf-8")
    for cle, valeur in mappage.items():
        rendu = f'"{valeur}"' if valeur == "" else valeur
        motif = re.compile(rf"(?m)^(\s*{re.escape(cle)}:).*$")
        texte, nb = motif.subn(lambda m, r=rendu: f"{m.group(1)} {r}", texte, count=1)
        if nb == 0:   # clé absente du fichier : on l'ajoute à la fin de « signaux: »
            texte = texte.replace("signaux:", f"signaux:\n  {cle}: {rendu}", 1)
    chemin_config.write_text(texte, encoding="utf-8")


def reglages_depuis_config(config: dict) -> Reglages:
    """Traduit la section « detection » du fichier de configuration."""
    d = config.get("detection", {}) or {}
    return Reglages(
        lambda_ewma=float(d.get("lambda", 0.10)),
        limite_L=float(d.get("L", 2.7)),
        k_cusum=float(d.get("k", 0.5)),
        h_cusum=float(d.get("h", 5.0)),
        n_reference=int(d.get("n_reference", 10)),
        source=str(d.get("source", "voie_opposee")),
        ecart_max_admissible=float(d.get("ecart_max_admissible_nm", 15.0)),
        zero_vigilance=float(d.get("zero_vigilance_nm", 3.0)),
        zero_majeur=float(d.get("zero_majeur_nm", 10.0)),
    )


# --- Lecture et rééchantillonnage ---
def _voies(mdf: MDF, noms: dict, frequence: float) -> tuple[np.ndarray, dict]:
    """Rééchantillonne toutes les voies utiles sur une base de temps commune."""
    brut = {}
    for cle, nom in noms.items():
        if not nom:
            continue
        try:
            signal = mdf.get(nom)
        except Exception:       # voie absente de cette acquisition
            continue
        brut[cle] = (np.asarray(signal.timestamps, dtype=float),
                     np.asarray(signal.samples, dtype=float))
    if "couple_gauche" not in brut or "couple_droit" not in brut:
        raise ValueError("voies de couple gauche et droite introuvables")

    debut = max(t[0] for t, _ in brut.values())
    fin = min(t[-1] for t, _ in brut.values())
    if fin <= debut:
        raise ValueError("les voies ne se recouvrent pas dans le temps")
    t = np.arange(debut, fin, 1.0 / frequence)
    return t, {cle: np.interp(t, ts, xs) for cle, (ts, xs) in brut.items()}


def segmenter(t: np.ndarray, voies: dict, param: dict) -> np.ndarray:
    """Attribue une phase à chaque échantillon : arrêt, traction, freinage, transitoire."""
    vitesse = voies.get("vitesse_vehicule", np.zeros_like(t))
    couple = 0.5 * (voies["couple_gauche"] + voies["couple_droit"])
    pedale = voies.get("pedale", np.zeros_like(t))
    acceleration = np.gradient(vitesse / 3.6, t)

    phases = np.full(t.size, PHASES.index("traction"), dtype=int)
    phases[couple < -20.0] = PHASES.index("freinage récupératif")
    fort = np.abs(acceleration) > float(param.get("acceleration_max_ms2", 0.4))
    phases[fort] = PHASES.index("transitoire")
    phases[vitesse < 1.0] = PHASES.index("arrêt")
    phases[(vitesse < 1.0) & (pedale > 5.0)] = PHASES.index("transitoire")
    return phases


def _masque_exploitable(t, voies, phases, param) -> np.ndarray:
    """Fenêtres retenues : vitesse stabilisée, ligne droite, hors transitoire.

    Les transitoires sont exclus : un défaut de synchronisation entre les deux
    voies y produit un élargissement de dispersion qu'on confondrait avec du bruit.
    """
    vitesse = voies.get("vitesse_vehicule", np.zeros_like(t))
    couple = 0.5 * (voies["couple_gauche"] + voies["couple_droit"])
    masque = phases != PHASES.index("transitoire")
    masque &= phases != PHASES.index("arrêt")
    masque &= vitesse >= float(param.get("vitesse_min_kmh", 20.0))
    masque &= np.abs(couple) >= float(param.get("couple_min_nm", 60.0))
    if "couple_demande" in voies:   # hors intervention du contrôle de motricité
        ecart = np.abs(couple - voies["couple_demande"])
        masque &= ecart <= float(param.get("ecart_demande_max_nm", 120.0))
    if "vitesse_lacet" in voies:    # ligne droite, si la voie existe
        masque &= np.abs(voies["vitesse_lacet"]) <= float(param.get("lacet_max_degs", 3.0))
    return masque


def _blocs(masque: np.ndarray) -> list[slice]:
    """Zones contiguës où le masque est vrai."""
    bords = np.flatnonzero(np.diff(masque.astype(np.int8)))
    debuts = np.concatenate(([0], bords + 1))
    fins = np.concatenate((bords + 1, [masque.size]))
    return [slice(int(d), int(f)) for d, f in zip(debuts, fins) if masque[d]]


def _fenetres(masque: np.ndarray, taille: int) -> list[slice]:
    """Découpe les zones retenues en fenêtres de longueur fixe.

    Une fenêtre donne une valeur de résidu : le bruit d'échantillon est moyenné
    et chaque fenêtre pèse le même poids dans les indicateurs de l'essai.
    """
    fenetres = []
    for bloc in _blocs(masque):
        for depart in range(bloc.start, bloc.stop - taille + 1, taille):
            fenetres.append(slice(depart, depart + taille))
    return fenetres


def _zero(voies: dict, phases: np.ndarray, fin: bool) -> float | None:
    """Résidu gauche − droite relevé à couple nul, avant ou après essai."""
    blocs = _blocs(phases == PHASES.index("arrêt"))
    if not blocs:
        return None
    bloc = blocs[-1] if fin else blocs[0]
    longueur = bloc.stop - bloc.start
    if longueur < 20:
        return None
    marge = max(1, longueur // 10)   # écarte l'entrée et la sortie de l'arrêt
    zone = slice(bloc.start + marge, bloc.stop - marge)
    ecart = voies["couple_gauche"][zone] - voies["couple_droit"][zone]
    return float(np.mean(ecart))


# --- Indicateurs d'un essai ---
@dataclass
class DetailEssai:
    """Un essai avec ses données brutes rééchantillonnées, pour la visualisation.

    lire_essai() ne garde que les indicateurs ; lire_detail() conserve en plus
    les signaux, les phases et le découpage en fenêtres, ce qui permet de voir
    où le résidu dérive et pourquoi telle portion d'essai a été écartée.
    """

    indicateurs: IndicateursEssai
    t: np.ndarray
    voies: dict
    phases: np.ndarray
    masque: np.ndarray
    fenetres: list = field(default_factory=list)
    residus_fenetres: list = field(default_factory=list)

    @property
    def residu(self) -> np.ndarray:
        """Résidu instantané gauche − droite, sur toute la durée de l'essai."""
        return self.voies["couple_gauche"] - self.voies["couple_droit"]

    def part_exploitable(self) -> float:
        """Proportion de l'essai retenue pour le calcul du résidu."""
        return float(self.masque.mean()) if self.masque.size else 0.0

    def repartition_phases(self) -> dict[str, float]:
        """Part de chaque phase dans l'essai, pour expliquer les exclusions."""
        if not self.phases.size:
            return {}
        return {nom: float(np.mean(self.phases == rang))
                for rang, nom in enumerate(PHASES)}


def lire_detail(chemin: str | Path, config: dict) -> DetailEssai:
    """Lit un MF4 et rend indicateurs et données brutes rééchantillonnées."""
    chemin = Path(chemin)
    param = config.get("traitement", {}) or {}
    frequence = float(param.get("frequence_hz", 20.0))

    with MDF(chemin) as mdf:
        t, voies = _voies(mdf, config.get("signaux", {}) or {}, frequence)
        debut = mdf.header.start_time

    phases = segmenter(t, voies, param)
    masque = _masque_exploitable(t, voies, phases, param)
    taille_min = max(2, int(float(param.get("duree_fenetre_s", 2.0)) * frequence))
    fenetres = _fenetres(masque, taille_min)

    gauche, droit = voies["couple_gauche"], voies["couple_droit"]
    estime = voies.get("couple_estime")
    r_voie, r_estime, niveau, g_est, d_est = [], [], [], [], []
    for f in fenetres:
        r_voie.append(float(np.mean(gauche[f] - droit[f])))
        moyen = 0.5 * (gauche[f] + droit[f])
        niveau.append(float(np.mean(moyen)))
        if estime is not None:
            r_estime.append(float(np.mean(moyen - estime[f])))
            g_est.append(float(np.mean(gauche[f] - estime[f])))
            d_est.append(float(np.mean(droit[f] - estime[f])))

    zero_avant = _zero(voies, phases, fin=False)
    zero_apres = _zero(voies, phases, fin=True)
    residus = {"voie_opposee": _resume(r_voie)}
    if r_estime:
        residus["couple_estime"] = _resume(r_estime)
    residus["zero"] = _resume([v for v in (zero_avant, zero_apres) if v is not None])

    temperature = voies.get("temperature")
    couple_max = float(np.max(np.abs(0.5 * (gauche + droit)))) if t.size else 0.0
    vitesse = voies.get("vitesse_vehicule")
    distance = float(np.trapezoid(vitesse / 3.6, t) / 1000.0) if vitesse is not None else 0.0
    indicateurs = IndicateursEssai(
        nom=chemin.stem,
        date=debut.strftime("%Y-%m-%d %H:%M") if debut else "",
        duree_s=float(t[-1] - t[0]) if t.size else 0.0,
        couple_max=couple_max,
        distance_km=distance,
        residus=residus,
        biais_gauche_estime=float(np.median(g_est)) if g_est else None,
        biais_droit_estime=float(np.median(d_est)) if d_est else None,
        zero_avant=zero_avant,
        zero_apres=zero_apres,
        temperature=float(np.mean(temperature)) if temperature is not None else None,
        pente_couple=_pente(niveau, r_voie),
        chemin=str(chemin),
        empreinte=empreinte(chemin),
    )
    return DetailEssai(indicateurs, t, voies, phases, masque, fenetres, r_voie)


def lire_essai(chemin: str | Path, config: dict) -> IndicateursEssai:
    """Lit un fichier MF4 et rend les indicateurs de l'essai, sources comprises."""
    return lire_detail(chemin, config).indicateurs


def _resume(valeurs) -> ResumeResidu:
    v = np.asarray([x for x in valeurs if np.isfinite(x)], dtype=float)
    if v.size == 0:
        return ResumeResidu()
    return ResumeResidu(biais=float(np.mean(v)),
                        ecart_type=float(np.std(v, ddof=1)) if v.size > 1 else 0.0,
                        ecart_max=float(np.max(np.abs(v))),
                        n_points=int(v.size))


def _pente(niveau, residu) -> float | None:
    """Sensibilité du résidu au niveau de couple, en N·m par N·m.

    Sans étendue de couple suffisante entre les fenêtres, la pente n'a pas de
    sens : on rend None plutôt qu'une valeur ajustée sur du bruit.
    """
    x = np.asarray(niveau, dtype=float)
    y = np.asarray(residu, dtype=float)
    if x.size < 4 or float(np.ptp(x)) < 100.0:
        return None
    return float(stats.linregress(x, y).slope)


def cle_essai(essai: IndicateursEssai) -> str:
    """Identité d'un essai : son contenu d'abord, son chemin à défaut.

    L'empreinte reconnaît un même fichier importé depuis deux emplacements
    différents, ce qu'une comparaison de chemins manquerait.
    """
    return essai.empreinte or essai.chemin or essai.nom


def fusionner_essais(existants: list[IndicateursEssai],
                     nouveaux) -> tuple[int, int]:
    """Complète la liste existante, sans doublon, et la retrie par date.

    La liste est modifiée sur place : un import ajoute à la collection, il ne
    la remplace jamais. Rend (nombre ajouté, nombre de doublons ignorés).
    L'ordre chronologique est rétabli après coup, car un essai ancien importé
    après coup doit reprendre sa place dans la série que suivent les cartes.
    """
    connues = {cle_essai(e) for e in existants}
    ajoutes = doublons = 0
    for essai in nouveaux:
        if cle_essai(essai) in connues:
            doublons += 1
            continue
        connues.add(cle_essai(essai))
        existants.append(essai)
        ajoutes += 1
    existants.sort(key=lambda e: e.date)
    return ajoutes, doublons


def empreinte(chemin: str | Path) -> str:
    """Empreinte du contenu d'un fichier, lue par blocs.

    Sert à reconnaître un essai déjà importé même s'il arrive depuis un autre
    chemin. Le coût est négligeable devant l'analyse du MF4 elle-même.
    """
    condensat = hashlib.blake2b(digest_size=16)
    with open(chemin, "rb") as flux:
        for bloc in iter(lambda: flux.read(1 << 20), b""):
            condensat.update(bloc)
    return condensat.hexdigest()


def fichiers_mf4(dossier: str | Path) -> list[Path]:
    """Tous les .mf4 d'un dossier, triés par nom (insensible à la casse Windows)."""
    return sorted(Path(dossier).glob("*.mf4"), key=lambda p: p.name.lower())


# --- Tracé libre : n'importe quelle voie du fichier ---
def voies_disponibles(chemin: str | Path) -> list[str]:
    """Noms de toutes les voies du fichier, mappées ou non."""
    with MDF(Path(chemin)) as mdf:
        return sorted(mdf.channels_db)


def lire_voie(chemin: str | Path, nom: str,
              t: np.ndarray) -> tuple[np.ndarray, str] | None:
    """Lit une voie quelconque et la ramène sur la base de temps de l'essai.

    Rend None si la voie est absente ou non numérique : toutes les voies d'une
    acquisition ne sont pas traçables (chaînes de caractères, tableaux).
    """
    with MDF(Path(chemin)) as mdf:
        try:
            signal = mdf.get(nom)
        except Exception:
            return None
        echantillons = np.asarray(signal.samples)
        unite = str(signal.unit or "")
    if echantillons.ndim != 1 or echantillons.dtype.kind not in "fiub":
        return None
    return np.interp(t, np.asarray(signal.timestamps, dtype=float),
                     echantillons.astype(float)), unite
