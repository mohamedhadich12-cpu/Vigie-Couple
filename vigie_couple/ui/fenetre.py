# -*- coding: utf-8 -*-
"""Fenêtre principale : trois écrans, un interrupteur de thème, rien d'autre."""
from __future__ import annotations

from PyQt5 import QtCore, QtWidgets

from ..coeur.detection import Reglages, Rupture, analyser
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
        # Un capteur par défaut, issu de config.yaml, pour que l'application
        # soit utilisable dès le premier lancement.
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

        self.campagne = EcranCampagne(config, chemin_config, self.stockage)
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
        self.campagne.capteur_change.connect(self._changer_capteur)
        self.surveillance.reglages_modifies.connect(self._recalculer)
        self.fiche.suivi_reinitialise.connect(self._recalculer)
        self.fiche.capteur_modifie.connect(self._capteur_modifie)
        self._construire_menu()
        self.capteur_id = self.campagne.capteur_id or self.capteur_id
        self._changer_capteur(self.capteur_id)
        self.appliquer_theme(mode)

    def _construire_menu(self):
        """La suppression définitive vit dans un menu, pas sous un bouton :
        elle ne doit pas pouvoir être déclenchée d'un clic distrait."""
        menu = self.menuBar().addMenu("Capteur")
        action = menu.addAction("Supprimer définitivement les données de ce capteur…")
        action.triggered.connect(self._supprimer_capteur)

    # --- état partagé ---
    def _changer_capteur(self, capteur_id: int):
        """Bascule tous les écrans sur un autre capteur suivi."""
        if capteur_id is None or capteur_id < 0:
            return
        self.capteur_id = capteur_id
        infos = self.stockage.infos_capteur(capteur_id)
        self.surveillance.nommer_capteur("  ·  ".join(
            str(infos.get(cle)) for cle in ("reference", "numero_serie", "vehicule")
            if infos.get(cle)))
        self.fiche.definir_capteur(capteur_id)
        self._recalculer()

    def _capteur_modifie(self, capteur_id: int):
        """L'identification a changé dans la fiche : les autres écrans la citent."""
        self.campagne.rafraichir_capteurs(selectionner=capteur_id)

    def _essais_charges(self, essais: list):
        """La campagne est lue : on archive, on analyse, on montre la surveillance."""
        nouveaux = len(essais) > len(self.essais)
        self.essais = essais
        if essais:
            self.stockage.enregistrer_essais(self.capteur_id, essais,
                                             self.reglages.source)
        self._recalculer()
        if nouveaux:
            self.onglets.setCurrentWidget(self.surveillance)

    def _ruptures(self) -> list[Rupture]:
        """Ruptures du capteur suivi, telles que le cœur de calcul les attend."""
        return [Rupture(date=r["date"], motif=r["motif"],
                        commentaire=r["commentaire"] or "")
                for r in self.stockage.ruptures(self.capteur_id)]

    def _recalculer(self, reglages: Reglages | None = None):
        if reglages is not None:
            self.reglages = reglages
        analyse = analyser(self.essais, self.reglages, self._ruptures())
        jours = jours_restants(self.stockage.dernier_etalonnage(self.capteur_id))
        self.surveillance.afficher(analyse, jours)
        self.campagne.colorer(analyse)
        self.fiche.afficher(analyse)

    def _supprimer_capteur(self):
        """Efface réellement les données du capteur. Double confirmation."""
        infos = self.stockage.infos_capteur(self.capteur_id)
        nom = str(infos.get("numero_serie") or "")
        if not nom:
            return
        premier = QtWidgets.QMessageBox.warning(
            self, "Supprimer les données du capteur",
            f"Toutes les données du capteur « {nom} » seront effacées :\n"
            "essais, relevés, étalonnages et réinitialisations.\n\n"
            "Cette action est irréversible. Continuer ?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
            QtWidgets.QMessageBox.Cancel)
        if premier != QtWidgets.QMessageBox.Yes:
            return
        saisi, valide = QtWidgets.QInputDialog.getText(
            self, "Confirmation", f"Saisissez « {nom} » pour confirmer :")
        if not valide or saisi.strip() != nom:
            QtWidgets.QMessageBox.information(
                self, "Suppression annulée", "Le nom saisi ne correspond pas.")
            return
        self.stockage.supprimer_capteur(self.capteur_id)
        self.campagne.essais_par_capteur.pop(self.capteur_id, None)
        self.essais = []
        self.campagne.rafraichir_capteurs()

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
