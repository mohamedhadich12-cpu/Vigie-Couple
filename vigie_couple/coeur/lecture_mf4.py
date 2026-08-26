# -*- coding: utf-8 -*-
"""Lecture des acquisitions MF4, segmentation en phases et calcul des résidus.

Le mappage des voies vient de config.yaml : le seul mappage en dur est celui du
jeu de démonstration, dont nous produisons nous-mêmes les fichiers.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml
from asammdf import MDF
from asammdf.blocks import v4_constants as v4c
from scipy import stats

from .detection import IndicateursEssai, Reglages, ResumeResidu

CHEMIN_CONFIG = Path(__file__).resolve().parents[1] / "config.yaml"

# Phases d'un essai, dans l'ordre d'affichage.
PHASES = ("arrêt", "traction", "freinage récupératif", "transitoire")

# Voies d'état : des grandeurs discrètes, pas des mesures continues. Elles sont
# rééchantillonnées par maintien de la dernière valeur et comparées à une
# valeur choisie par l'opérateur, jamais interpolées ni moyennées.
VOIES_ETAT = ("rapport", "frein_stationnement")

# Conversions MF4 qui énumèrent des états nommés : « valeur vers texte » et
# « plage de valeurs vers texte ». Les autres conversions sont numériques
# (mise à l'échelle, interpolation) et ne cataloguent aucun état.
TABLES_DE_VALEURS = (v4c.CONVERSION_TYPE_TABX, v4c.CONVERSION_TYPE_RTABX)
_RANG_TEXTE = re.compile(r"text_(\d+)")

# Voies du jeu de démonstration. Elles sont fixées par donnees_demo/generateur.py
# et ne doivent pas dépendre du mappage adapté aux acquisitions du site : sinon
# la démonstration cesse de fonctionner dès qu'on configure ses propres voies.
MAPPAGE_DEMO = {
    "couple_gauche": "CRoue_Trans_G",
    "couple_droit": "CRoue_Trans_D",
    "couple_estime": "TqWhlEst_tqWhlPt_RTE",
    "couple_demande": "TqSpl_tqWhlFrntReq_RTE",
    "vitesse_vehicule": "Veh_spdVeh_RTE",
    "pedale": "AcP_rAcc_P_RTE",
    "temperature": "Temp_Capteur_G",
    "vitesse_lacet": "",
    # Le générateur ne produit ni pente, ni rapport, ni frein de stationnement :
    # les critères d'arrêt correspondants sont simplement sautés sur la démo.
    "pente": "",
    "rapport": "",
    "frein_stationnement": "",
}

# Capteur du jeu de démonstration. Il vit ici, à côté du mappage, et non dans
# l'interface : le générateur doit pouvoir l'atteindre sans importer Qt, sinon
# l'étalonnage de démonstration s'inscrit sur le capteur de config.yaml et la
# tuile « jours avant échéance » reste vide pendant la démonstration.
CAPTEUR_DEMO = {
    "reference": "Capteur de démonstration",
    "numero_serie": "DEMO",
    "arbre": "Gauche",
    "vehicule": "Mule fictive",
    "commentaire": "Données synthétiques produites par donnees_demo/generateur.py. "
                   "Ne correspond à aucun capteur réel.",
}


def charger_config(chemin: str | Path | None = None) -> dict:
    """Charge config.yaml. Les chemins sont résolus de façon portable (Windows compris)."""
    fichier = Path(chemin) if chemin else CHEMIN_CONFIG
    with open(fichier, "r", encoding="utf-8") as flux:
        return yaml.safe_load(flux) or {}


def scalaire_yaml(valeur: str) -> str:
    """Rend un nom de voie sous une forme que YAML relira à l'identique.

    Les noms de signaux d'une acquisition réelle contiennent couramment « : »,
    « # », « * » ou « @ », qui sont de la syntaxe pour YAML. Écrits tels quels,
    ils rendent config.yaml illisible et l'application ne redémarre plus. Le
    guillemet double est le seul style YAML qui accepte des échappements, donc
    n'importe quel nom.
    """
    echappe = str(valeur).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{echappe}"'


def _patcher_section(texte: str, valeurs: dict[str, str], section: str) -> str:
    """Réécrit des clés dans le texte YAML, en les créant sous « section: » au besoin."""
    for cle, valeur in valeurs.items():
        rendu = scalaire_yaml(valeur)
        motif = re.compile(rf"(?m)^(\s*{re.escape(cle)}:).*$")
        texte, nb = motif.subn(lambda m, r=rendu: f"{m.group(1)} {r}", texte, count=1)
        if nb == 0:   # clé absente du fichier : on l'ajoute en tête de sa section
            texte = texte.replace(f"{section}:", f"{section}:\n  {cle}: {rendu}", 1)
    return texte


def enregistrer_mappage(chemin_config: str | Path, mappage: dict[str, str],
                        traitement: dict[str, str] | None = None) -> None:
    """Réécrit les voies choisies dans config.yaml, sans toucher au reste du fichier.

    Un patch ciblé ligne à ligne plutôt qu'un ré-export YAML complet : les
    commentaires et la mise en forme du fichier sont préservés.

    « traitement » porte les valeurs d'état qui accompagnent le mappage — la
    valeur du rapport qui désigne le neutre, celle du frein de stationnement
    qui désigne l'état serré. Elles vont dans la section « traitement », pas
    dans « signaux » : ce sont des réglages, pas des noms de voies.
    """
    chemin_config = Path(chemin_config)
    texte = chemin_config.read_text(encoding="utf-8")
    texte = _patcher_section(texte, mappage, "signaux")
    if traitement:
        texte = _patcher_section(texte, traitement, "traitement")
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
def texte_mf4(valeur) -> str:
    """Décode un texte de fichier MF4, quel que soit son encodage.

    La norme MDF4 prescrit l'UTF-8, mais des outils d'acquisition écrivent
    encore en latin-1. Décoder systématiquement en latin-1 rendait « desserré »
    sous la forme « desserrÃ© » : illisible à l'écran, et surtout réécrit tel
    quel dans config.yaml, où il ne correspondrait plus à rien.
    """
    if not isinstance(valeur, bytes):
        return str(valeur).strip()
    for encodage in ("utf-8", "latin-1"):
        try:
            return valeur.decode(encodage).strip()
        except UnicodeDecodeError:
            continue
    return valeur.decode("latin-1", "replace").strip()


def _echantillons_etat(echantillons) -> np.ndarray:
    """Voie d'état : numérique si elle l'est, texte sinon.

    Un rapport de boîte ou un frein de stationnement arrive tantôt en valeurs
    numériques brutes, tantôt déjà traduit par une table de valeurs du fichier
    MF4 (« N », « P », « serré »). Les deux formes sont acceptées, et
    comparées ensuite chacune à sa manière.
    """
    tableau = np.asarray(echantillons).ravel()
    if tableau.dtype.kind in "fiub":
        return tableau
    return np.asarray([texte_mf4(v) for v in tableau])


def _maintien(t: np.ndarray, ts: np.ndarray, echantillons: np.ndarray) -> np.ndarray:
    """Rééchantillonne une voie d'état par maintien de la dernière valeur connue.

    Surtout pas d'interpolation linéaire : entre la 2ᵉ et la 3ᵉ, un rapport
    interpolé vaudrait « 2,4 », qui n'est pas un rapport. Le maintien d'ordre
    zéro reproduit ce que fait réellement le calculateur entre deux trames.
    """
    indices = np.clip(np.searchsorted(ts, t, side="right") - 1,
                      0, echantillons.size - 1)
    return echantillons[indices]


def _voies(mdf: MDF, noms: dict,
           frequence: float) -> tuple[np.ndarray, dict, dict]:
    """Rééchantillonne les voies utiles sur une base de temps commune.

    Rend (temps, voies continues, voies d'état). Les voies d'état sont tenues
    à part : elles ne s'interpolent pas, et peuvent être du texte.
    """
    brut, brut_etat = {}, {}
    for cle, nom in noms.items():
        if not nom:
            continue
        try:
            signal = mdf.get(nom)
        except Exception:       # voie absente de cette acquisition
            continue
        temps = np.asarray(signal.timestamps, dtype=float)
        if cle in VOIES_ETAT:
            brut_etat[cle] = (temps, _echantillons_etat(signal.samples))
            continue
        try:
            brut[cle] = (temps, np.asarray(signal.samples, dtype=float))
        except (ValueError, TypeError):   # voie non numérique : inexploitable ici
            continue
    if "couple_gauche" not in brut or "couple_droit" not in brut:
        raise ValueError("voies de couple gauche et droite introuvables")

    toutes = list(brut.values()) + list(brut_etat.values())
    debut = max(t[0] for t, _ in toutes)
    fin = min(t[-1] for t, _ in toutes)
    if fin <= debut:
        raise ValueError("les voies ne se recouvrent pas dans le temps")
    t = np.arange(debut, fin, 1.0 / frequence)
    voies = {cle: np.interp(t, ts, xs) for cle, (ts, xs) in brut.items()}
    etats = {cle: _maintien(t, ts, xs) for cle, (ts, xs) in brut_etat.items()}
    return t, voies, etats


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


def comparaison_couple_estime(gauche, droit, estime, total_essieu: bool):
    """Grandeurs à comparer au couple estimé, à l'échelle où il est exprimé.

    Le calculateur peut estimer le couple *total de l'essieu* — les deux roues
    additionnées — ou le couple *d'une roue*. On compare toujours à l'échelle
    du signal estimé, sans jamais le remettre à l'échelle lui-même :

    * essieu total : c'est la **somme** des deux voies qui lui fait face ;
    * par roue     : c'est leur **moyenne**.

    Comparer une moyenne à un total, ou l'inverse, produirait un biais
    artificiel d'un facteur ~2 sans rapport avec une vraie dérive.

    Rend (mesure, part_par_roue) : « mesure − estimé » est le résidu de la
    source « couple estimé », et « voie − part_par_roue » l'écart d'une seule
    voie, dont la discrimination se sert pour désigner la voie suspecte.
    """
    if total_essieu:
        return gauche + droit, 0.5 * estime
    return 0.5 * (gauche + droit), estime


def valeur_etat(valeurs: np.ndarray, choix) -> np.ndarray | None:
    """Compare une voie d'état à la valeur désignée par l'opérateur.

    Le choix vient d'une liste déroulante, donc sous forme de texte : on
    compare numériquement quand la voie est numérique, littéralement sinon.
    Rend None quand la comparaison n'a pas de sens, auquel cas le critère
    correspondant est simplement sauté.
    """
    texte = str(choix if choix is not None else "").strip()
    if not texte or valeurs is None or not len(valeurs):
        return None
    if valeurs.dtype.kind in "fiub":
        try:
            return np.isclose(valeurs.astype(float), float(texte.replace(",", ".")))
        except ValueError:      # voie numérique, choix textuel : incomparable
            return None
    return np.asarray([str(v).strip() == texte for v in valeurs])


def masque_arret_zero(etats: dict, voies: dict, phases: np.ndarray,
                      param: dict) -> np.ndarray:
    """Plages d'arrêt réellement exploitables pour un relevé de zéro.

    Être immobile ne suffit pas. **À l'arrêt dans une pente, un rapport engagé
    retient le véhicule par la transmission** : l'arbre de roue travaille en
    torsion et le couple n'est pas nul, alors que la vitesse l'est. Relever le
    zéro là reviendrait à prendre une charge bien réelle pour une dérive du
    capteur, et à polluer la référence de toute la campagne.

    Trois critères, chacun ignoré si sa voie n'est pas mappée, ce qui laisse le
    comportement inchangé sur une installation qui ne les fournit pas :

    * le **rapport** doit être au neutre : sans cela la transmission peut
      transmettre un couple de retenue, quelle que soit la pente ;
    * la **pente** doit être faible, **ou** le **frein de stationnement**
      serré, auquel cas c'est lui qui retient le véhicule et non la ligne de
      transmission. Si une seule des deux voies est mappée, elle décide seule.
    """
    masque = phases == PHASES.index("arrêt")

    au_neutre = valeur_etat(etats.get("rapport"), param.get("rapport_neutre"))
    if au_neutre is not None:
        masque = masque & au_neutre

    a_plat = None
    if "pente" in voies:
        seuil = float(param.get("pente_max_arret_pourcent", 2.0))
        a_plat = np.abs(voies["pente"]) <= seuil
    serre = valeur_etat(etats.get("frein_stationnement"), param.get("fse_serre"))

    if a_plat is not None and serre is not None:
        masque = masque & (a_plat | serre)
    elif a_plat is not None:
        masque = masque & a_plat
    elif serre is not None:
        masque = masque & serre
    return masque


def _zero(voies: dict, masque_arret: np.ndarray, fin: bool) -> float | None:
    """Résidu gauche − droite relevé à couple nul, avant ou après essai.

    Un essai qui ne comporte qu'une seule plage d'arrêt exploitable ne fournit
    pas de zéro de fin : rendre deux fois le même relevé afficherait une dérive
    intra-essai nulle par construction, ce qui se lirait à tort comme un zéro
    stable.
    """
    blocs = _blocs(masque_arret)
    if not blocs or (fin and len(blocs) < 2):
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
    etats: dict = field(default_factory=dict)
    masque_arret: np.ndarray | None = None

    @property
    def residu(self) -> np.ndarray:
        """Résidu instantané gauche − droite, sur toute la durée de l'essai."""
        return self.voies["couple_gauche"] - self.voies["couple_droit"]

    def part_exploitable(self) -> float:
        """Proportion de l'essai retenue pour le calcul du résidu."""
        return float(self.masque.mean()) if self.masque.size else 0.0

    def arrets_exploitables(self) -> int:
        """Nombre de plages d'arrêt retenues pour un relevé de zéro.

        Zéro alors que l'essai comporte des arrêts signifie que le rapport
        n'était pas au neutre, ou que le véhicule était retenu dans une pente.
        """
        if self.masque_arret is None:
            return 0
        return len(_blocs(self.masque_arret))

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
        t, voies, etats = _voies(mdf, config.get("signaux", {}) or {}, frequence)
        debut = mdf.header.start_time

    phases = segmenter(t, voies, param)
    arrets = masque_arret_zero(etats, voies, phases, param)
    masque = _masque_exploitable(t, voies, phases, param)
    taille_min = max(2, int(float(param.get("duree_fenetre_s", 2.0)) * frequence))
    fenetres = _fenetres(masque, taille_min)

    gauche, droit = voies["couple_gauche"], voies["couple_droit"]
    estime = voies.get("couple_estime")
    mesure = part_roue = None
    if estime is not None:
        mesure, part_roue = comparaison_couple_estime(
            gauche, droit, estime,
            bool(param.get("couple_estime_total_essieu", False)))
    r_voie, r_estime, niveau, g_est, d_est = [], [], [], [], []
    for f in fenetres:
        r_voie.append(float(np.mean(gauche[f] - droit[f])))
        niveau.append(float(np.mean(0.5 * (gauche[f] + droit[f]))))
        if estime is not None:
            r_estime.append(float(np.mean(mesure[f] - estime[f])))
            g_est.append(float(np.mean(gauche[f] - part_roue[f])))
            d_est.append(float(np.mean(droit[f] - part_roue[f])))

    zero_avant = _zero(voies, arrets, fin=False)
    zero_apres = _zero(voies, arrets, fin=True)
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
    return DetailEssai(indicateurs, t, voies, phases, masque, fenetres, r_voie,
                       etats, arrets)


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


def rendre_valeur(valeur) -> str:
    """Valeur d'état sous forme lisible, pour une liste déroulante.

    Un rapport lu « 3.0 » s'affiche « 3 » : c'est ce que l'opérateur reconnaît,
    et c'est ce qui sera réécrit tel quel dans config.yaml.
    """
    if isinstance(valeur, (bool, np.bool_)):
        return str(bool(valeur))
    if isinstance(valeur, (int, float, np.integer, np.floating)):
        nombre = float(valeur)
        return str(int(nombre)) if nombre == int(nombre) else f"{nombre:g}"
    return str(valeur).strip()


def valeurs_distinctes(chemin: str | Path, nom: str,
                       limite: int = 40) -> list[str]:
    """Valeurs distinctes réellement prises par une voie dans un essai d'exemple.

    Une voie qui prend trop de valeurs différentes n'est pas une voie d'état :
    on rend une liste vide plutôt qu'un menu de plusieurs milliers d'entrées.
    """
    with MDF(Path(chemin)) as mdf:
        try:
            signal = mdf.get(nom)
        except Exception:       # voie absente de cet essai
            return []
        echantillons = _echantillons_etat(signal.samples)
    if not echantillons.size:
        return []
    uniques = np.unique(echantillons)
    if uniques.size > limite:
        return []
    return [rendre_valeur(v) for v in uniques]


def catalogue_valeurs(chemin: str | Path, nom: str) -> list[str]:
    """Tous les états catalogués par la table de valeurs de la voie.

    Un essai ne contient que ce qui s'est produit : celui où la marche arrière
    n'a pas servi ne montre jamais « R », celui où le frein à main est resté
    desserré ne montre jamais « serré ». La **table de valeurs** du fichier
    MF4, elle, énumère tout le codage du véhicule, indépendamment de ce qui a
    été roulé ce jour-là. C'est elle qu'il faut proposer à l'opérateur.

    Rend une liste vide quand la voie ne porte pas de table de valeurs : son
    codage est alors numérique brut, et seules les valeurs rencontrées peuvent
    être proposées.
    """
    with MDF(Path(chemin)) as mdf:
        try:
            # La conversion n'est lisible que sur le signal brut : appliquée,
            # asammdf la consomme et ne la rattache plus au signal rendu.
            signal = mdf.get(nom, raw=True)
        except Exception:
            return []
        conversion = getattr(signal, "conversion", None)
        if conversion is None:
            return []
        if getattr(conversion, "conversion_type", None) not in TABLES_DE_VALEURS:
            return []       # conversion numérique (échelle, interpolation) : pas des états
        blocs = getattr(conversion, "referenced_blocks", None) or {}
        catalogue = []
        for cle in sorted((c for c in blocs if _RANG_TEXTE.fullmatch(c)),
                          key=lambda c: int(c.split("_")[1])):
            texte = texte_mf4(getattr(blocs[cle], "text", blocs[cle]))
            if texte and texte not in catalogue:
                catalogue.append(texte)
    return catalogue


def valeurs_proposees(chemin: str | Path, nom: str,
                      limite: int = 60) -> tuple[list[str], set[str]]:
    """Valeurs à proposer pour une voie d'état, et celles vues dans l'essai.

    Le catalogue de la table de valeurs vient d'abord, dans son ordre : c'est
    le codage complet du véhicule. Les valeurs rencontrées qui n'y figurent pas
    le suivent. Rend aussi l'ensemble de celles réellement présentes, pour que
    l'interface puisse distinguer « catalogué » de « observé » sans altérer le
    libellé, qui sera réécrit tel quel dans config.yaml.
    """
    vues = valeurs_distinctes(chemin, nom, limite)
    proposees = list(catalogue_valeurs(chemin, nom))
    for valeur in vues:
        if valeur not in proposees:
            proposees.append(valeur)
    return proposees[:limite], set(vues)


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
