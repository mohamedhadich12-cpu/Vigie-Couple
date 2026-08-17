# -*- coding: utf-8 -*-
"""Fenêtre principale : trois écrans, un interrupteur de thème, rien d'autre."""
from __future__ import annotations

from PyQt5 import QtCore, QtWidgets

from ..coeur.detection import Reglages, analyser
from ..coeur.lecture_mf4 import CHEMIN_CONFIG, reglages_depuis_config
from ..coeur.stockage import Stockage, jours_restants
from . import theme
from .ecran_campagne import EcranCampagne
from .ecran_fiche import EcranFiche
from .ecran_surveillance import EcranSurveillance


class Fenetre(QtWidgets.QMainWindow):
    """Assemble les trois écrans et détient l'état partagé de la campagne."""

    def __init__(self, config: dict, chemin_config=CHEMIN_CONFIG, mode: str = "clair"):
        super().__init__()
        self.config = config
        self.mode = mode
        self.reglages: Reglages = reglages_depuis_config(config)
        self.essais: list = []
        self.stockage = Stockage()
        self.capteur_id = self.stockage.capteur(config.get("capteur", {}) or {})

        self.setWindowTitle("Vigie Couple — détection de dérive des capteurs de couple")
        self.resize(1180, 780)

        central = QtWidgets.QWidget()
        disposition = theme.marges(QtWidgets.QVBoxLayout(central), theme.MARGE)

        entete = QtWidgets.QHBoxLayout()
        entete.setSpacing(theme.ESPACE)
        titre = theme.marges(QtWidgets.QVBoxLayout(), 0, 2)
        titre.addWidget(theme.etiquette("Vigie Couple", "titre"))
        titre.addWidget(theme.etiquette(
            "Détection précoce de dérive des capteurs de couple embarqués",
            "secondaire"))
        entete.addLayout(titre)
        entete.addStretch(1)
        self.bouton_theme = QtWidgets.QPushButton("Mode sombre")
        self.bouton_theme.clicked.connect(self._basculer_theme)
        entete.addWidget(self.bouton_theme, 0, QtCore.Qt.AlignTop)
        disposition.addLayout(entete)

        self.campagne = EcranCampagne(config, chemin_config)
        self.surveillance = EcranSurveillance(self.reglages, mode)
        self.fiche = EcranFiche(self.stockage, self.capteur_id, config,
                                self.surveillance.image_residu)

        self.onglets = QtWidgets.QTabWidget()
        self.onglets.addTab(self.campagne, "Campagne")
        self.onglets.addTab(self.surveillance, "Surveillance")
        self.onglets.addTab(self.fiche, "Fiche de vie")
        disposition.addWidget(self.onglets, 1)
        self.setCentralWidget(central)

        self.campagne.essais_charges.connect(self._essais_charges)
        self.surveillance.reglages_modifies.connect(self._recalculer)
        self.appliquer_theme(mode)

    # --- état partagé ---
    def _essais_charges(self, essais: list):
        """La campagne est lue : on archive, on analyse, on montre la surveillance."""
        self.essais = essais
        self.stockage.enregistrer_essais(self.capteur_id, essais, self.reglages.source)
        self._recalculer()
        self.onglets.setCurrentWidget(self.surveillance)

    def _recalculer(self, reglages: Reglages | None = None):
        if reglages is not None:
            self.reglages = reglages
        if not self.essais:
            return
        analyse = analyser(self.essais, self.reglages)
        jours = jours_restants(self.stockage.dernier_etalonnage(self.capteur_id))
        self.surveillance.afficher(analyse, jours)
        self.campagne.colorer(analyse)
        self.fiche.afficher(analyse)

    # --- thème ---
    def _basculer_theme(self):
        self.appliquer_theme("sombre" if self.mode == "clair" else "clair")

    def appliquer_theme(self, mode: str):
        self.mode = mode
        application = QtWidgets.QApplication.instance()
        application.setStyleSheet(theme.feuille_de_style(mode))
        self.bouton_theme.setText("Mode clair" if mode == "sombre" else "Mode sombre")
        self.campagne.appliquer_theme(mode)
        self.surveillance.appliquer_theme(mode)
        self.fiche.appliquer_theme(mode)

    def closeEvent(self, evenement):
        self.stockage.fermer()
        super().closeEvent(evenement)
