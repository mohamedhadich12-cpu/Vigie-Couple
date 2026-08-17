# -*- coding: utf-8 -*-
"""Fenêtre de mappage des voies : associer les grandeurs attendues aux noms
réels des signaux d'une acquisition, sans éditer config.yaml à la main.
"""
from __future__ import annotations

from pathlib import Path

from asammdf import MDF
from PyQt5 import QtWidgets

from ..coeur.lecture_mf4 import enregistrer_mappage
from . import theme

# (clé, libellé, obligatoire)
CHAMPS = (
    ("couple_gauche", "Couple voie gauche", True),
    ("couple_droit", "Couple voie droite", True),
    ("couple_estime", "Couple estimé (calculateur)", False),
    ("couple_demande", "Couple demandé", False),
    ("vitesse_vehicule", "Vitesse véhicule", False),
    ("pedale", "Pédale d'accélérateur", False),
    ("temperature", "Température capteur", False),
    ("vitesse_lacet", "Vitesse de lacet", False),
)


class DialogueMappage(QtWidgets.QDialog):
    """Associe chaque grandeur à une voie réelle, à partir d'un essai d'exemple."""

    def __init__(self, config: dict, chemin_config: str | Path, parent=None):
        super().__init__(parent)
        self.config = config
        self.chemin_config = chemin_config
        self.setWindowTitle("Mappage des voies")
        self.resize(540, 500)

        disposition = theme.marges(QtWidgets.QVBoxLayout(self), theme.MARGE)
        disposition.addWidget(theme.etiquette("Mappage des voies", "titre"))
        explication = theme.etiquette(
            "Associez chaque grandeur nécessaire à la détection à la voie "
            "correspondante dans vos acquisitions. Chargez un essai d'exemple "
            "pour choisir dans la liste des voies disponibles ; sinon, saisissez "
            "directement le nom du signal.", "secondaire")
        explication.setWordWrap(True)
        disposition.addWidget(explication)
        disposition.addSpacing(theme.ESPACE)

        ligne = QtWidgets.QHBoxLayout()
        ligne.setSpacing(theme.ESPACE)
        self.bouton_fichier = QtWidgets.QPushButton("Choisir un fichier d'exemple (.mf4)…")
        self.bouton_fichier.clicked.connect(self._choisir_fichier)
        self.fichier = theme.etiquette("Aucun fichier chargé : saisie libre ci-dessous.",
                                       "secondaire")
        ligne.addWidget(self.bouton_fichier)
        ligne.addWidget(self.fichier, 1)
        disposition.addLayout(ligne)
        disposition.addSpacing(theme.MARGE)

        formulaire = theme.marges(QtWidgets.QFormLayout(), 0, theme.ESPACE)
        signaux = config.get("signaux", {}) or {}
        self.champs: dict[str, QtWidgets.QComboBox] = {}
        for cle, libelle, obligatoire in CHAMPS:
            boite = QtWidgets.QComboBox()
            boite.setEditable(True)
            boite.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
            boite.setEditText(str(signaux.get(cle, "") or ""))
            self.champs[cle] = boite
            formulaire.addRow(libelle + (" *" if obligatoire else ""), boite)
        disposition.addLayout(formulaire)
        disposition.addWidget(theme.etiquette("* voies obligatoires", "secondaire"))
        disposition.addStretch(1)

        self.etat = theme.etiquette("", "secondaire")
        self.etat.setWordWrap(True)
        disposition.addWidget(self.etat)

        boutons = QtWidgets.QDialogButtonBox()
        bouton_enregistrer = boutons.addButton(
            "Enregistrer", QtWidgets.QDialogButtonBox.AcceptRole)
        bouton_continuer = boutons.addButton(
            "Continuer sans modifier", QtWidgets.QDialogButtonBox.RejectRole)
        bouton_enregistrer.clicked.connect(self._enregistrer)
        bouton_continuer.clicked.connect(self.reject)
        bouton_continuer.setDefault(True)   # un « Entrée » ne modifie rien par défaut
        disposition.addWidget(boutons)

    def _choisir_fichier(self):
        chemin, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choisir un essai d'exemple", "",
            "Acquisitions MF4 (*.mf4);;Tous les fichiers (*)")
        if not chemin:
            return
        try:
            with MDF(chemin) as mdf:
                voies = sorted(mdf.channels_db.keys())
        except Exception as erreur:
            self.etat.setText(f"Fichier illisible : {erreur}")
            return
        self.fichier.setText(f"{Path(chemin).name} — {len(voies)} voies trouvées")
        for boite in self.champs.values():
            actuel = boite.currentText()
            boite.clear()
            boite.addItems(voies)
            boite.setEditText(actuel)   # conserve le choix déjà saisi

    def _enregistrer(self):
        mappage = {cle: boite.currentText().strip() for cle, boite in self.champs.items()}
        if not mappage["couple_gauche"] or not mappage["couple_droit"]:
            self.etat.setText("Les voies de couple gauche et droite sont obligatoires.")
            return
        enregistrer_mappage(self.chemin_config, mappage)
        self.config.setdefault("signaux", {}).update(mappage)
        self.accept()
