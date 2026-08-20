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

# Capteur créé d'office pour recueillir les essais enregistrés avant que le
# rattachement à un capteur ne devienne obligatoire.
CAPTEUR_ORPHELIN = "Non renseigné"

SCHEMA = """
CREATE TABLE IF NOT EXISTS capteur (
    id INTEGER PRIMARY KEY,
    reference TEXT, numero_serie TEXT UNIQUE,
    arbre TEXT, vehicule TEXT,
    date_service TEXT, commentaire TEXT);
CREATE TABLE IF NOT EXISTS essai (
    id INTEGER PRIMARY KEY, capteur_id INTEGER, nom TEXT, date TEXT,
    duree_s REAL, couple_max REAL, distance_km REAL,
    biais REAL, ecart_type REAL, ecart_max REAL, empreinte TEXT,
    UNIQUE(capteur_id, nom));
CREATE TABLE IF NOT EXISTS rupture (
    id INTEGER PRIMARY KEY, capteur_id INTEGER, date TEXT,
    motif TEXT, commentaire TEXT);
CREATE TABLE IF NOT EXISTS preference (
    cle TEXT PRIMARY KEY, valeur TEXT);
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
        self._migrer()
        self.cx.commit()

    def _migrer(self):
        """Complète le schéma des bases créées par une version antérieure.

        Les colonnes manquantes sont ajoutées et les essais sans capteur sont
        rattachés à un capteur « Non renseigné » : aucune donnée n'est perdue.
        """
        for table, colonne, type_sql in (
                ("capteur", "date_service", "TEXT"),
                ("capteur", "commentaire", "TEXT"),
                ("essai", "empreinte", "TEXT")):
            existantes = {ligne["name"] for ligne in
                          self.cx.execute(f"PRAGMA table_info({table})")}
            if colonne not in existantes:
                self.cx.execute(f"ALTER TABLE {table} ADD COLUMN {colonne} {type_sql}")
        orphelins = self.cx.execute(
            "SELECT COUNT(*) AS n FROM essai WHERE capteur_id IS NULL"
            " OR capteur_id NOT IN (SELECT id FROM capteur)").fetchone()["n"]
        if orphelins:
            recueil = self.capteur({"reference": CAPTEUR_ORPHELIN,
                                    "numero_serie": CAPTEUR_ORPHELIN})
            self.cx.execute(
                "UPDATE essai SET capteur_id = ? WHERE capteur_id IS NULL"
                " OR capteur_id NOT IN (SELECT id FROM capteur WHERE id != ?)",
                (recueil, recueil))
            print(f"{orphelins} essais sans capteur rattachés à « {CAPTEUR_ORPHELIN} ».")

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
                "UPDATE capteur SET reference=?, arbre=?, vehicule=?,"
                " date_service=?, commentaire=? WHERE id=?",
                (infos.get("reference", ""), infos.get("arbre", ""),
                 infos.get("vehicule", ""), infos.get("date_service", ""),
                 infos.get("commentaire", ""), ligne["id"]))
            self.cx.commit()
            return int(ligne["id"])
        curseur = self.cx.execute(
            "INSERT INTO capteur (reference, numero_serie, arbre, vehicule,"
            " date_service, commentaire) VALUES (?,?,?,?,?,?)",
            (infos.get("reference", ""), serie, infos.get("arbre", ""),
             infos.get("vehicule", ""), infos.get("date_service", ""),
             infos.get("commentaire", "")))
        self.cx.commit()
        return int(curseur.lastrowid)

    def modifier_capteur(self, capteur_id: int, infos: dict) -> bool:
        """Modifie un capteur **désigné par son identifiant**, champ par champ.

        À la différence de capteur(), qui identifie par numéro de série et crée
        la ligne au besoin : ici on modifie une ligne existante, y compris son
        numéro de série. Seules les clés fournies sont écrites — un écran qui
        n'affiche pas la date de mise en service ne doit pas l'effacer en
        enregistrant les champs qu'il affiche.

        Rend False si le numéro de série demandé appartient déjà à un autre
        capteur : deux capteurs de même série ne seraient plus distinguables.
        """
        colonnes = [cle for cle in ("reference", "numero_serie", "arbre", "vehicule",
                                    "date_service", "commentaire") if cle in infos]
        if not colonnes:
            return True
        serie = infos.get("numero_serie")
        if serie is not None:
            occupe = self.cx.execute(
                "SELECT id FROM capteur WHERE numero_serie = ? AND id != ?",
                (str(serie), capteur_id)).fetchone()
            if occupe:
                return False
        self.cx.execute(
            f"UPDATE capteur SET {', '.join(f'{c}=?' for c in colonnes)} WHERE id=?",
            [str(infos[c] or "") for c in colonnes] + [capteur_id])
        self.cx.commit()
        return True

    def capteurs(self) -> list[dict]:
        """Tous les capteurs enregistrés, le plus récemment créé en dernier."""
        return [dict(ligne) for ligne in
                self.cx.execute("SELECT * FROM capteur ORDER BY id")]

    def supprimer_capteur(self, capteur_id: int):
        """Efface un capteur et tout ce qui s'y rattache. Sans retour possible."""
        for table in ("essai", "releve", "etalonnage", "rupture"):
            self.cx.execute(f"DELETE FROM {table} WHERE capteur_id = ?", (capteur_id,))
        self.cx.execute("DELETE FROM capteur WHERE id = ?", (capteur_id,))
        self.cx.commit()

    def infos_capteur(self, capteur_id: int) -> dict:
        ligne = self.cx.execute(
            "SELECT * FROM capteur WHERE id = ?", (capteur_id,)).fetchone()
        return dict(ligne) if ligne else {}

    # --- essais et relevés ---
    def enregistrer_essais(self, capteur_id: int, essais, source: str = "voie_opposee"):
        """Archive les essais d'une campagne et les relevés de zéro associés.

        Un essai déjà archivé est **mis à jour**, pas ignoré : les indicateurs
        dépendent de la source du résidu, et celle-ci se change à tout moment
        depuis le panneau de réglages. Un INSERT OR IGNORE aurait figé pour
        toujours la source en vigueur au premier import, et la fiche de vie
        aurait archivé en silence un résidu qui n'est pas celui du verdict.
        """
        for essai in essais:
            resume = essai.resume(source)
            self.cx.execute(
                "INSERT INTO essai (capteur_id, nom, date, duree_s,"
                " couple_max, distance_km, biais, ecart_type, ecart_max, empreinte)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(capteur_id, nom) DO UPDATE SET"
                " date=excluded.date, duree_s=excluded.duree_s,"
                " couple_max=excluded.couple_max, distance_km=excluded.distance_km,"
                " biais=excluded.biais, ecart_type=excluded.ecart_type,"
                " ecart_max=excluded.ecart_max, empreinte=excluded.empreinte",
                (capteur_id, essai.nom, essai.date, essai.duree_s, essai.couple_max,
                 essai.distance_km, resume.biais, resume.ecart_type, resume.ecart_max,
                 essai.empreinte))
            for type_releve, valeur in (("zéro avant", essai.zero_avant),
                                        ("zéro après", essai.zero_apres)):
                if valeur is not None:
                    # Horodatage complet, pas seulement le jour : la contrainte
                    # d'unicité est (capteur_id, date, type), et deux essais du
                    # même jour partageraient sinon la même ligne — seul le
                    # premier importé serait conservé, les suivants ignorés en
                    # silence par INSERT OR IGNORE, même en cas de vraie dérive.
                    self.ajouter_releve(capteur_id, essai.date, type_releve,
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

    # --- ruptures de suivi ---
    def ajouter_rupture(self, capteur_id: int, date: str, motif: str,
                        commentaire: str = ""):
        """Enregistre une réinitialisation de suivi. N'efface aucun essai."""
        self.cx.execute(
            "INSERT INTO rupture (capteur_id, date, motif, commentaire)"
            " VALUES (?,?,?,?)", (capteur_id, date, motif, commentaire))
        self.cx.commit()

    def supprimer_derniere_rupture(self, capteur_id: int) -> dict | None:
        """Annule la dernière réinitialisation. Rend celle qui a été retirée."""
        ligne = self.cx.execute(
            "SELECT id, date, motif FROM rupture WHERE capteur_id = ?"
            " ORDER BY date DESC, id DESC LIMIT 1", (capteur_id,)).fetchone()
        if ligne is None:
            return None
        self.cx.execute("DELETE FROM rupture WHERE id = ?", (ligne["id"],))
        self.cx.commit()
        return dict(ligne)

    def ruptures(self, capteur_id: int) -> list[dict]:
        lignes = self.cx.execute(
            "SELECT date, motif, commentaire FROM rupture WHERE capteur_id = ?"
            " ORDER BY date", (capteur_id,)).fetchall()
        return [dict(ligne) for ligne in lignes]

    # --- préférences ---
    def preference(self, cle: str, defaut: str = "") -> str:
        ligne = self.cx.execute(
            "SELECT valeur FROM preference WHERE cle = ?", (cle,)).fetchone()
        return ligne["valeur"] if ligne else defaut

    def definir_preference(self, cle: str, valeur: str):
        self.cx.execute(
            "INSERT INTO preference (cle, valeur) VALUES (?,?)"
            " ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
            (cle, str(valeur)))
        self.cx.commit()

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
