# -*- coding: utf-8 -*-
"""Fenêtre de mappage des voies : associer les grandeurs attendues aux noms
réels des signaux d'une acquisition, sans éditer config.yaml à la main.
"""
from __future__ import annotations

from pathlib import Path

from asammdf import MDF
from PyQt5 import QtCore, QtWidgets

from ..coeur.lecture_mf4 import enregistrer_mappage, valeurs_proposees
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
    ("pente", "Pente longitudinale (%)", False),
    ("rapport", "Rapport de boîte engagé", False),
    ("frein_stationnement", "Frein de stationnement (FSE)", False),
)

# Voies d'état dont il faut désigner une valeur particulière : (voie mappée,
# clé du réglage dans config.yaml, libellé, aide).
ETATS = (
    ("rapport", "rapport_neutre", "Valeur du rapport au point mort",
     "À l'arrêt, seul le point mort garantit que la transmission ne retient "
     "pas le véhicule."),
    ("frein_stationnement", "fse_serre", "Valeur du FSE à l'état serré",
     "Un frein serré retient le véhicule à la place de la transmission : "
     "l'arrêt redevient exploitable même en pente."),
)


class DialogueMappage(QtWidgets.QDialog):
    """Associe chaque grandeur à une voie réelle, à partir d'un essai d'exemple."""

    def __init__(self, config: dict, chemin_config: str | Path, parent=None):
        super().__init__(parent)
        self.config = config
        self.chemin_config = chemin_config
        self.exemple = None          # essai d'exemple, source des valeurs d'état
        self.setWindowTitle("Mappage des voies")
        self.resize(620, 700)

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
        disposition.addSpacing(theme.MARGE)

        # --- valeurs d'état : quel code désigne le neutre, quel code le serrage ---
        disposition.addWidget(theme.etiquette("Valeurs d'état des arrêts", "titre"))
        raison = theme.etiquette(
            "Un arrêt n'est retenu pour un relevé de zéro que si le rapport est au "
            "point mort, et que la pente est faible ou le frein de stationnement "
            "serré. À l'arrêt en pente avec un rapport engagé, l'arbre de roue "
            "travaille en torsion : le couple n'y est pas nul.", "secondaire")
        raison.setWordWrap(True)
        disposition.addWidget(raison)

        etats = theme.marges(QtWidgets.QFormLayout(), 0, theme.ESPACE)
        traitement = config.get("traitement", {}) or {}
        self.etats: dict[str, QtWidgets.QComboBox] = {}
        for voie, cle, libelle, aide in ETATS:
            boite = QtWidgets.QComboBox()
            boite.setEditable(True)
            boite.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
            boite.setEditText(str(traitement.get(cle, "") or ""))
            boite.setToolTip(aide)
            self.etats[voie] = boite
            etats.addRow(libelle, boite)
            # La liste se remplit dès qu'on désigne la voie correspondante.
            self.champs[voie].currentTextChanged.connect(
                lambda _, v=voie: self._proposer_valeurs(v))
        disposition.addLayout(etats)
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
        self.exemple = chemin
        self.fichier.setText(f"{Path(chemin).name} — {len(voies)} voies trouvées")
        for boite in self.champs.values():
            actuel = boite.currentText()
            boite.clear()
            boite.addItems(voies)
            boite.setEditText(actuel)   # conserve le choix déjà saisi
        for voie in self.etats:
            self._proposer_valeurs(voie)

    def _proposer_valeurs(self, voie: str):
        """Propose les états d'une voie : son catalogue complet d'abord.

        Un essai ne contient que ce qui s'est produit ce jour-là. Proposer les
        seules valeurs rencontrées priverait du choix « marche arrière » un
        essai sans marche arrière, et du choix « serré » un essai où le frein à
        main n'a pas servi. On propose donc la table de valeurs du fichier,
        qui énumère tout le codage, et l'on n'y ajoute les valeurs observées
        que si elles n'y figurent pas.

        Sans essai d'exemple, le champ reste en saisie libre : on ne devine pas
        le codage d'un rapport de boîte à la place de l'opérateur.
        """
        boite = self.etats.get(voie)
        if boite is None:
            return
        nom = self.champs[voie].currentText().strip()
        actuel = boite.currentText()
        boite.clear()
        aide = ""
        if self.exemple and nom:
            proposees, vues = valeurs_proposees(self.exemple, nom)
            boite.addItems(proposees)
            for rang, valeur in enumerate(proposees):
                # L'infobulle porte la nuance, jamais le libellé : celui-ci est
                # réécrit tel quel dans config.yaml et sert de clé de comparaison.
                boite.setItemData(
                    rang,
                    "Rencontrée dans l'essai d'exemple" if valeur in vues
                    else "Cataloguée par le fichier, absente de cet essai",
                    QtCore.Qt.ToolTipRole)
            catalogues = len(proposees) - len(vues - set(proposees))
            if not proposees:
                aide = ("Aucune valeur proposable : voie absente de cet essai, ou "
                        "trop de valeurs distinctes pour une voie d'état. Saisissez "
                        "la valeur à la main.")
            elif len(vues) < len(proposees):
                accord = "rencontré" if len(vues) < 2 else "rencontrés"
                aide = (f"{len(proposees)} états proposés, dont {len(vues)} "
                        f"{accord} dans cet essai. Les autres viennent de la "
                        "table de valeurs du fichier.")
            else:
                aide = (f"{len(proposees)} états, tous rencontrés dans cet essai. "
                        "Ce fichier ne porte pas de table de valeurs : seuls les "
                        "états réellement roulés peuvent être proposés.")
        boite.setToolTip(aide)
        boite.setEditText(actuel)

    def _enregistrer(self):
        mappage = {cle: boite.currentText().strip() for cle, boite in self.champs.items()}
        if not mappage["couple_gauche"] or not mappage["couple_droit"]:
            self.etat.setText("Les voies de couple gauche et droite sont obligatoires.")
            return
        traitement = {cle: self.etats[voie].currentText().strip()
                      for voie, cle, _, _ in ETATS}
        # Une voie d'état sans valeur désignée ne filtre rien : le dire, plutôt
        # que de laisser croire que le critère est actif.
        oubliees = [libelle for voie, cle, libelle, _ in ETATS
                    if mappage.get(voie) and not traitement[cle]]
        if oubliees:
            self.etat.setText("Voie mappée sans valeur désignée, critère inactif : "
                              + ", ".join(oubliees) + ".")
            return
        enregistrer_mappage(self.chemin_config, mappage, traitement)
        self.config.setdefault("signaux", {}).update(mappage)
        self.config.setdefault("traitement", {}).update(traitement)
        self.accept()
