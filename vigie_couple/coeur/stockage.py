# -*- coding: utf-8 -*-
"""Fiche de vie des capteurs : un seul fichier SQLite, aucune autre persistance."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

CHEMIN_BASE = Path(__file__).resolve().parents[1] / "vigie_couple.db"

# Plafond imposé par le règlement technique mondial ONU n° 21 pour la mesure
# de couple aux essieux : 370 jours entre deux étalonnages.
PLAFOND_JOURS = 370

SCHEMA = """
CREATE TABLE IF NOT EXISTS capteur (
    id INTEGER PRIMARY KEY,
    reference TEXT, numero_serie TEXT UNIQUE,
    arbre TEXT, vehicule TEXT);
CREATE TABLE IF NOT EXISTS essai (
    id INTEGER PRIMARY KEY, capteur_id INTEGER, nom TEXT, date TEXT,
    duree_s REAL, couple_max REAL, distance_km REAL,
    biais REAL, ecart_type REAL, ecart_max REAL,
    UNIQUE(capteur_id, nom));
CREATE TABLE IF NOT EXISTS releve (
    id INTEGER PRIMARY KEY, capteur_id INTEGER, date TEXT, type TEXT,
    valeur REAL, commentaire TEXT,
    UNIQUE(capteur_id, date, type));
CREATE TABLE IF NOT EXISTS etalonnage (
    id INTEGER PRIMARY KEY, capteur_id INTEGER, date TEXT,
    incertitude REAL, certificat TEXT,
    UNIQUE(capteur_id, date));
"""


class Stockage:
    """Accès à la base ; toutes les écritures sont idempotentes (INSERT OR IGNORE)."""

    def __init__(self, chemin: str | Path | None = None):
        self.chemin = Path(chemin) if chemin else CHEMIN_BASE
        self.cx = sqlite3.connect(str(self.chemin))
        self.cx.row_factory = sqlite3.Row
        self.cx.executescript(SCHEMA)
        self.cx.commit()

    def fermer(self):
        self.cx.close()

    # --- identification ---
    def capteur(self, infos: dict) -> int:
        """Rend l'identifiant du capteur, créé au besoin d'après son numéro de série."""
        serie = str(infos.get("numero_serie", "inconnu"))
        ligne = self.cx.execute(
            "SELECT id FROM capteur WHERE numero_serie = ?", (serie,)).fetchone()
        if ligne:
            self.cx.execute(
                "UPDATE capteur SET reference=?, arbre=?, vehicule=? WHERE id=?",
                (infos.get("reference", ""), infos.get("arbre", ""),
                 infos.get("vehicule", ""), ligne["id"]))
            self.cx.commit()
            return int(ligne["id"])
        curseur = self.cx.execute(
            "INSERT INTO capteur (reference, numero_serie, arbre, vehicule)"
            " VALUES (?,?,?,?)",
            (infos.get("reference", ""), serie, infos.get("arbre", ""),
             infos.get("vehicule", "")))
        self.cx.commit()
        return int(curseur.lastrowid)

    def infos_capteur(self, capteur_id: int) -> dict:
        ligne = self.cx.execute(
            "SELECT * FROM capteur WHERE id = ?", (capteur_id,)).fetchone()
        return dict(ligne) if ligne else {}

    # --- essais et relevés ---
    def enregistrer_essais(self, capteur_id: int, essais, source: str = "voie_opposee"):
        """Archive les essais d'une campagne et les relevés de zéro associés."""
        for essai in essais:
            resume = essai.resume(source)
            self.cx.execute(
                "INSERT OR IGNORE INTO essai (capteur_id, nom, date, duree_s,"
                " couple_max, distance_km, biais, ecart_type, ecart_max)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (capteur_id, essai.nom, essai.date, essai.duree_s, essai.couple_max,
                 essai.distance_km, resume.biais, resume.ecart_type, resume.ecart_max))
            for type_releve, valeur in (("zéro avant", essai.zero_avant),
                                        ("zéro après", essai.zero_apres)):
                if valeur is not None:
                    self.ajouter_releve(capteur_id, essai.date[:10], type_releve,
                                        valeur, essai.nom, valider=False)
        self.cx.commit()

    def ajouter_releve(self, capteur_id: int, jour: str, type_releve: str,
                       valeur: float, commentaire: str = "", valider: bool = True):
        self.cx.execute(
            "INSERT OR IGNORE INTO releve (capteur_id, date, type, valeur, commentaire)"
            " VALUES (?,?,?,?,?)",
            (capteur_id, jour, type_releve, float(valeur), commentaire))
        if valider:
            self.cx.commit()

    def releves(self, capteur_id: int, limite: int = 12) -> list[dict]:
        lignes = self.cx.execute(
            "SELECT date, type, valeur, commentaire FROM releve WHERE capteur_id = ?"
            " ORDER BY date DESC, id DESC LIMIT ?", (capteur_id, limite)).fetchall()
        return [dict(ligne) for ligne in lignes]

    # --- étalonnages ---
    def ajouter_etalonnage(self, capteur_id: int, jour: str,
                           incertitude: float, certificat: str):
        self.cx.execute(
            "INSERT OR IGNORE INTO etalonnage (capteur_id, date, incertitude,"
            " certificat) VALUES (?,?,?,?)",
            (capteur_id, jour, float(incertitude), certificat))
        self.cx.commit()

    def etalonnages(self, capteur_id: int) -> list[dict]:
        lignes = self.cx.execute(
            "SELECT date, incertitude, certificat FROM etalonnage"
            " WHERE capteur_id = ? ORDER BY date DESC", (capteur_id,)).fetchall()
        return [dict(ligne) for ligne in lignes]

    def dernier_etalonnage(self, capteur_id: int) -> str | None:
        ligne = self.cx.execute(
            "SELECT MAX(date) AS jour FROM etalonnage WHERE capteur_id = ?",
            (capteur_id,)).fetchone()
        return ligne["jour"] if ligne and ligne["jour"] else None

    # --- usage cumulé ---
    def usage(self, capteur_id: int, seuil_severe: float = 750.0) -> dict:
        ligne = self.cx.execute(
            "SELECT COUNT(*) AS essais, COALESCE(SUM(distance_km), 0) AS km,"
            " COALESCE(SUM(couple_max >= ?), 0) AS severes"
            " FROM essai WHERE capteur_id = ?", (seuil_severe, capteur_id)).fetchone()
        return {"essais": int(ligne["essais"]), "km": float(ligne["km"]),
                "severes": int(ligne["severes"])}


def jours_depuis(jour: str | None) -> int | None:
    """Nombre de jours écoulés depuis une date « AAAA-MM-JJ »."""
    if not jour:
        return None
    try:
        depart = datetime.strptime(jour[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return (date.today() - depart).days


def jours_restants(dernier: str | None) -> int | None:
    """Jours restants avant l'échéance de réétalonnage (plafond 370 jours)."""
    ecoules = jours_depuis(dernier)
    return None if ecoules is None else PLAFOND_JOURS - ecoules
