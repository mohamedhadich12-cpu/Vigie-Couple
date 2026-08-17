# -*- coding: utf-8 -*-
"""Écran 1 — Campagne : charger des acquisitions et calculer les indicateurs.

La lecture se fait dans un fil séparé : l'interface ne se fige jamais, même sur
une trentaine de fichiers MF4.
"""
from __future__ import annotations

from pathlib import Path

from PyQt5 import QtCore, QtWidgets

from ..coeur.detection import Analyse, horodatage
from ..coeur.lecture_mf4 import fichiers_mf4, lire_essai
from . import theme

COLONNES = ("Date", "Essai", "Durée", "Couple max", "Biais du résidu",
            "Écart-type", "Verdict")
DOSSIER_DEMO = Path(__file__).resolve().parents[2] / "donnees_demo" / "essais"


class Chargeur(QtCore.QThread):
    """Lecture des fichiers MF4 en tâche de fond, un essai à la fois."""

    progression = QtCore.pyqtSignal(int, int, str)
    essai_lu = QtCore.pyqtSignal(object)
    echec = QtCore.pyqtSignal(str, str)
    fini = QtCore.pyqtSignal()

    def __init__(self, chemins: list[Path], config: dict, parent=None):
        super().__init__(parent)
        self.chemins = chemins
        self.config = config

    def run(self):
        total = len(self.chemins)
        for rang, chemin in enumerate(self.chemins, start=1):
            self.progression.emit(rang, total, chemin.name)
            try:
                self.essai_lu.emit(lire_essai(chemin, self.config))
            except Exception as erreur:            # fichier illisible ou incomplet
                self.echec.emit(chemin.name, str(erreur))
        self.fini.emit()


class EcranCampagne(QtWidgets.QWidget):
    """Tableau des essais chargés, avec un verdict par essai."""

    essais_charges = QtCore.pyqtSignal(list)

    def __init__(self, config: dict, chemin_config, parent=None):
        super().__init__(parent)
        self.config = config
        self.chemin_config = chemin_config
        self.essais: list = []
        self._chargeur: Chargeur | None = None
        self._dossier = str(DOSSIER_DEMO.parent)

        disposition = theme.marges(QtWidgets.QVBoxLayout(self), theme.MARGE)
        disposition.addWidget(theme.etiquette("Campagne d'essais", "titre"))

        boutons = QtWidgets.QHBoxLayout()
        boutons.setSpacing(theme.ESPACE)
        self.bouton_mappage = QtWidgets.QPushButton("Configurer les voies…")
        self.bouton_fichiers = QtWidgets.QPushButton("Ajouter des fichiers…")
        self.bouton_dossier = QtWidgets.QPushButton("Ajouter un dossier…")
        self.bouton_demo = QtWidgets.QPushButton("Jeu de démonstration")
        self.bouton_mappage.clicked.connect(self._configurer_voies)
        self.bouton_fichiers.clicked.connect(self._choisir_fichiers)
        self.bouton_dossier.clicked.connect(self._choisir_dossier)
        self.bouton_demo.clicked.connect(self._charger_demo)
        # « Configurer les voies… » en premier : c'est la première question à
        # se poser avant de charger des acquisitions qui ne sont pas la démo.
        for bouton in (self.bouton_mappage, self.bouton_fichiers,
                       self.bouton_dossier, self.bouton_demo):
            boutons.addWidget(bouton)
        boutons.addStretch(1)
        disposition.addLayout(boutons)

        self.progression = QtWidgets.QProgressBar()
        self.progression.setTextVisible(False)
        self.progression.hide()
        self.etat = theme.etiquette("Aucun essai chargé.", "secondaire")
        disposition.addWidget(self.progression)
        disposition.addWidget(self.etat)

        self.tableau = QtWidgets.QTableWidget(0, len(COLONNES))
        self.tableau.setHorizontalHeaderLabels(COLONNES)
        self.tableau.setAlternatingRowColors(True)
        self.tableau.verticalHeader().setVisible(False)
        self.tableau.setSelectionBehavior(QtWidgets.QTableWidget.SelectRows)
        self.tableau.setEditTriggers(QtWidgets.QTableWidget.NoEditTriggers)
        entete = self.tableau.horizontalHeader()
        entete.setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        entete.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        disposition.addWidget(self.tableau, 1)

    # --- sélection des fichiers ---
    def _choisir_fichiers(self):
        chemins, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Choisir des acquisitions", self._dossier,
            "Acquisitions MF4 (*.mf4);;Tous les fichiers (*)")
        if chemins:
            self._dossier = str(Path(chemins[0]).parent)
            self._lancer([Path(c) for c in chemins])

    def _choisir_dossier(self):
        dossier = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Choisir un dossier d'essais", self._dossier)
        if dossier:
            self._dossier = dossier
            trouves = fichiers_mf4(dossier)
            if not trouves:
                self.etat.setText("Aucun fichier .mf4 dans ce dossier.")
                return
            self._lancer(trouves)

    def _charger_demo(self):
        trouves = fichiers_mf4(DOSSIER_DEMO) if DOSSIER_DEMO.exists() else []
        if not trouves:
            self.etat.setText("Jeu de démonstration absent : lancez d'abord "
                              "« python donnees_demo/generateur.py ».")
            return
        self._lancer(trouves)

    def _configurer_voies(self):
        from .dialogue_mappage import DialogueMappage  # import tardif : évite un cycle
        if DialogueMappage(self.config, self.chemin_config, self).exec_():
            self.etat.setText("Mappage des voies enregistré.")

    # --- chargement ---
    def _lancer(self, chemins: list[Path]):
        if self._chargeur is not None and self._chargeur.isRunning():
            return
        self.essais.clear()
        self.tableau.setRowCount(0)
        self._activer(False)
        self.progression.setRange(0, len(chemins))
        self.progression.setValue(0)
        self.progression.show()
        self._chargeur = Chargeur(chemins, self.config, self)
        self._chargeur.progression.connect(self._avancer)
        self._chargeur.essai_lu.connect(self._ajouter)
        self._chargeur.echec.connect(self._signaler)
        self._chargeur.fini.connect(self._terminer)
        self._chargeur.start()

    def _activer(self, actif: bool):
        for bouton in (self.bouton_mappage, self.bouton_fichiers,
                       self.bouton_dossier, self.bouton_demo):
            bouton.setEnabled(actif)

    def _avancer(self, rang: int, total: int, nom: str):
        self.progression.setValue(rang - 1)
        self.etat.setText(f"Lecture de l'essai {rang} sur {total} — {nom}")

    def _signaler(self, nom: str, message: str):
        self.etat.setText(f"Essai ignoré — {nom} : {message}")

    def _ajouter(self, essai):
        self.essais.append(essai)
        source = (self.config.get("detection", {}) or {}).get("source", "voie_opposee")
        resume = essai.resume(source)
        minutes, secondes = divmod(int(essai.duree_s), 60)
        valeurs = (horodatage(essai.date), essai.nom,
                   f"{minutes} min {secondes:02d} s",
                   theme.nombre(essai.couple_max, 0, "N·m"),
                   theme.nombre(resume.biais, 2, "N·m", signe=True),
                   theme.nombre(resume.ecart_type, 2, "N·m"), "")
        ligne = self.tableau.rowCount()
        self.tableau.insertRow(ligne)
        for colonne, valeur in enumerate(valeurs):
            cellule = QtWidgets.QTableWidgetItem(valeur)
            if colonne >= 2:
                cellule.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            self.tableau.setItem(ligne, colonne, cellule)
        self.progression.setValue(ligne + 1)

    def _terminer(self):
        self.progression.hide()
        self._activer(True)
        self.etat.setText(f"{len(self.essais)} essais chargés.")
        self.essais_charges.emit(list(self.essais))

    # --- verdicts par essai ---
    def colorer(self, analyse: Analyse):
        """Reporte le verdict de chaque essai dans la dernière colonne."""
        reglages = analyse.reglages
        for ligne, essai in enumerate(analyse.essais):
            if ligne >= self.tableau.rowCount():
                break
            resume = essai.resume(reglages.source)
            zero = essai.zero_apres
            if (resume.ecart_max > reglages.ecart_max_admissible
                    or (zero is not None and abs(zero) > reglages.zero_majeur)):
                statut, libelle = "non_conforme", "Non conforme"
            elif analyse.cusum.alarmes[ligne] or analyse.ewma.alarmes[ligne]:
                statut, libelle = "vigilance", "Vigilance"
            else:
                statut, libelle = "conforme", "Conforme"
            # Seule la pastille porte la couleur : le libellé reste lisible.
            pastille = QtWidgets.QLabel(
                f'<span style="color:{theme.couleur_statut(statut)}">●</span>'
                f'&nbsp;&nbsp;{libelle}')
            pastille.setStyleSheet("background: transparent; padding-left: 4px;")
            self.tableau.setCellWidget(ligne, len(COLONNES) - 1, pastille)
