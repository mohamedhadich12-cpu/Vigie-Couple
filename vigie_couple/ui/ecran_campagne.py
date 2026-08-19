# -*- coding: utf-8 -*-
"""Écran 1 — Campagne : choisir le capteur suivi, charger des acquisitions.

La lecture se fait dans un fil séparé : l'interface ne se fige jamais, même sur
une trentaine de fichiers MF4. Les essais sont rattachés au capteur actif au
moment de l'import, et chaque import complète la liste au lieu de l'écraser.
"""
from __future__ import annotations

from pathlib import Path

from PyQt5 import QtCore, QtWidgets

from ..coeur.detection import Analyse, horodatage
from ..coeur.lecture_mf4 import (MAPPAGE_DEMO, fichiers_mf4, fusionner_essais,
                                 lire_detail, lire_essai)
from ..coeur.stockage import Stockage
from . import theme

COLONNES = ("", "Date", "Essai", "Durée", "Couple max", "Biais du résidu",
            "Écart-type", "Verdict")
DOSSIER_DEMO = Path(__file__).resolve().parents[2] / "donnees_demo" / "essais"
ARBRES = ("Non précisé", "Gauche", "Droite")

# Le jeu de démonstration a son propre capteur : ses essais sont synthétiques et
# n'ont rien à faire dans la fiche de vie d'un capteur réel. Le numéro de série
# sert de clé : recliquer sur le bouton retrouve ce capteur au lieu d'en créer
# un nouveau à chaque fois.
CAPTEUR_DEMO = {
    "reference": "Capteur de démonstration",
    "numero_serie": "DEMO",
    "arbre": "Gauche",
    "vehicule": "Mule fictive",
    "commentaire": "Données synthétiques produites par donnees_demo/generateur.py. "
                   "Ne correspond à aucun capteur réel.",
}


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


class DialogueCapteur(QtWidgets.QDialog):
    """Création ou modification d'un capteur suivi."""

    def __init__(self, infos: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Modifier le capteur" if infos else "Nouveau capteur")
        infos = infos or {}
        formulaire = theme.marges(QtWidgets.QFormLayout(self), theme.MARGE)

        self.reference = QtWidgets.QLineEdit(str(infos.get("reference") or ""))
        self.numero_serie = QtWidgets.QLineEdit(str(infos.get("numero_serie") or ""))
        self.arbre = QtWidgets.QComboBox()
        self.arbre.addItems(ARBRES)
        if infos.get("arbre") in ARBRES:
            self.arbre.setCurrentText(infos["arbre"])
        self.vehicule = QtWidgets.QLineEdit(str(infos.get("vehicule") or ""))
        self.date_service = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
        self.date_service.setDisplayFormat("dd/MM/yyyy")
        self.date_service.setCalendarPopup(True)
        if infos.get("date_service"):
            self.date_service.setDate(QtCore.QDate.fromString(
                str(infos["date_service"])[:10], "yyyy-MM-dd"))
        self.commentaire = QtWidgets.QPlainTextEdit(str(infos.get("commentaire") or ""))
        self.commentaire.setFixedHeight(60)

        formulaire.addRow("Référence", self.reference)
        formulaire.addRow("Numéro de série", self.numero_serie)
        formulaire.addRow("Arbre", self.arbre)
        formulaire.addRow("Véhicule", self.vehicule)
        formulaire.addRow("Mise en service", self.date_service)
        formulaire.addRow("Commentaire", self.commentaire)
        self.etat = theme.etiquette("", "secondaire")
        formulaire.addRow(self.etat)

        boutons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        boutons.button(QtWidgets.QDialogButtonBox.Ok).setText("Enregistrer")
        boutons.button(QtWidgets.QDialogButtonBox.Cancel).setText("Annuler")
        boutons.accepted.connect(self._valider)
        boutons.rejected.connect(self.reject)
        formulaire.addRow(boutons)

    def _valider(self):
        if not self.numero_serie.text().strip():
            self.etat.setText("Le numéro de série identifie le capteur : il est requis.")
            return
        self.accept()

    def valeurs(self) -> dict:
        return {
            "reference": self.reference.text().strip(),
            "numero_serie": self.numero_serie.text().strip(),
            "arbre": self.arbre.currentText(),
            "vehicule": self.vehicule.text().strip(),
            "date_service": self.date_service.date().toString("yyyy-MM-dd"),
            "commentaire": self.commentaire.toPlainText().strip(),
        }


class EcranCampagne(QtWidgets.QWidget):
    """Capteur suivi, chargement des essais, tableau et verdict par essai."""

    essais_charges = QtCore.pyqtSignal(list)
    capteur_change = QtCore.pyqtSignal(int)

    def __init__(self, config: dict, chemin_config, stockage: Stockage, parent=None):
        super().__init__(parent)
        self.config = config
        self.chemin_config = chemin_config
        self.stockage = stockage
        # Les essais restent en mémoire, groupés par capteur : changer de
        # capteur filtre l'affichage sans rien perdre.
        self.essais_par_capteur: dict[int, list] = {}
        self.capteur_id: int | None = None
        self.analyse: Analyse | None = None
        self._mode = "clair"
        self._chargeur: Chargeur | None = None
        self._echecs: list[str] = []
        self._dossier = str(DOSSIER_DEMO.parent)

        disposition = theme.marges(QtWidgets.QVBoxLayout(self), theme.MARGE)
        disposition.addWidget(theme.etiquette("Campagne d'essais", "titre"))

        # --- barre de sélection du capteur suivi ---
        barre = QtWidgets.QHBoxLayout()
        barre.setSpacing(theme.ESPACE)
        self.capteurs = QtWidgets.QComboBox()
        self.capteurs.setMinimumWidth(320)
        self.capteurs.currentIndexChanged.connect(self._changer_capteur)
        self.bouton_nouveau = QtWidgets.QPushButton("Nouveau capteur")
        self.bouton_modifier = QtWidgets.QPushButton("Modifier")
        self.bouton_nouveau.clicked.connect(self._nouveau_capteur)
        self.bouton_modifier.clicked.connect(self._modifier_capteur)
        barre.addWidget(theme.etiquette("Capteur suivi", "secondaire"))
        barre.addWidget(self.capteurs)
        barre.addWidget(self.bouton_nouveau)
        barre.addWidget(self.bouton_modifier)
        barre.addStretch(1)
        disposition.addLayout(barre)

        # --- import et gestion de la liste ---
        boutons = QtWidgets.QHBoxLayout()
        boutons.setSpacing(theme.ESPACE)
        self.bouton_mappage = QtWidgets.QPushButton("Configurer les voies…")
        self.bouton_fichiers = QtWidgets.QPushButton("Ajouter des fichiers…")
        self.bouton_dossier = QtWidgets.QPushButton("Ajouter un dossier…")
        self.bouton_demo = QtWidgets.QPushButton("Jeu de démonstration")
        self.bouton_voir = QtWidgets.QPushButton("Visualiser l'essai…")
        self.bouton_retirer = QtWidgets.QPushButton("Retirer la sélection")
        self.bouton_vider = QtWidgets.QPushButton("Vider la liste")
        self.bouton_mappage.clicked.connect(self._configurer_voies)
        self.bouton_fichiers.clicked.connect(self._choisir_fichiers)
        self.bouton_dossier.clicked.connect(self._choisir_dossier)
        self.bouton_demo.clicked.connect(self._charger_demo)
        self.bouton_voir.clicked.connect(self._visualiser)
        self.bouton_retirer.clicked.connect(self._retirer_selection)
        self.bouton_vider.clicked.connect(self._vider)
        for bouton in (self.bouton_mappage, self.bouton_fichiers,
                       self.bouton_dossier, self.bouton_demo, self.bouton_voir):
            boutons.addWidget(bouton)
        boutons.addStretch(1)
        # Les actions destructives à part, après l'espace : on ne les atteint
        # pas en visant un bouton d'import.
        boutons.addWidget(self.bouton_retirer)
        boutons.addWidget(self.bouton_vider)
        disposition.addLayout(boutons)

        self.progression = QtWidgets.QProgressBar()
        self.progression.setTextVisible(False)
        self.progression.hide()
        self.etat = theme.etiquette("", "secondaire")
        self.etat.setWordWrap(True)
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
        entete.setSectionResizeMode(0, QtWidgets.QHeaderView.Fixed)
        self.tableau.setColumnWidth(0, 28)
        entete.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.tableau.doubleClicked.connect(self._visualiser)
        self.tableau.itemSelectionChanged.connect(self._actualiser_boutons)
        self.tableau.itemChanged.connect(self._actualiser_boutons)
        disposition.addWidget(self.tableau, 1)

        self.rafraichir_capteurs()

    # --- capteur suivi ---
    @property
    def essais(self) -> list:
        """Essais du capteur actif. Liste vivante : on la complète, jamais on ne la remplace."""
        if self.capteur_id is None:
            return []
        return self.essais_par_capteur.setdefault(self.capteur_id, [])

    def rafraichir_capteurs(self, selectionner: int | None = None):
        """Recharge la liste déroulante depuis la base, en gardant la sélection."""
        vise = selectionner if selectionner is not None else self.capteur_id
        if vise is None:
            memorise = self.stockage.preference("capteur_actif")
            vise = int(memorise) if memorise.isdigit() else None
        self.capteurs.blockSignals(True)
        self.capteurs.clear()
        capteurs = self.stockage.capteurs()
        for capteur in capteurs:
            self.capteurs.addItem(self._libelle(capteur), capteur["id"])
        indice = self.capteurs.findData(vise)
        if indice < 0 and capteurs:
            indice = 0
        if indice >= 0:
            self.capteurs.setCurrentIndex(indice)
        self.capteurs.blockSignals(False)
        self._changer_capteur()

    @staticmethod
    def _libelle(capteur: dict) -> str:
        morceaux = [capteur.get("reference"), capteur.get("numero_serie"),
                    capteur.get("arbre"), capteur.get("vehicule")]
        return "  ·  ".join(str(m) for m in morceaux if m and m != "Non précisé")

    def _changer_capteur(self):
        nouveau = self.capteurs.currentData()
        self.capteur_id = int(nouveau) if nouveau is not None else None
        if self.capteur_id is not None:
            self.stockage.definir_preference("capteur_actif", self.capteur_id)
        self._remplir_tableau()
        self._actualiser_boutons()
        self.capteur_change.emit(self.capteur_id if self.capteur_id is not None else -1)
        self.essais_charges.emit(list(self.essais))

    def _nouveau_capteur(self):
        boite = DialogueCapteur(parent=self)
        if boite.exec_() == QtWidgets.QDialog.Accepted:
            identifiant = self.stockage.capteur(boite.valeurs())
            self.rafraichir_capteurs(selectionner=identifiant)

    def _modifier_capteur(self):
        if self.capteur_id is None:
            return
        infos = self.stockage.infos_capteur(self.capteur_id)
        boite = DialogueCapteur(infos, parent=self)
        if boite.exec_() == QtWidgets.QDialog.Accepted:
            valeurs = boite.valeurs()
            # Le numéro de série identifie le capteur : on met à jour la ligne
            # existante plutôt que d'en créer une seconde.
            self.stockage.cx.execute(
                "UPDATE capteur SET reference=?, numero_serie=?, arbre=?,"
                " vehicule=?, date_service=?, commentaire=? WHERE id=?",
                (valeurs["reference"], valeurs["numero_serie"], valeurs["arbre"],
                 valeurs["vehicule"], valeurs["date_service"],
                 valeurs["commentaire"], self.capteur_id))
            self.stockage.cx.commit()
            self.rafraichir_capteurs(selectionner=self.capteur_id)

    def _actualiser_boutons(self):
        """Aucun import sans capteur : c'est ce qui garantit le rattachement."""
        pret = self.capteur_id is not None
        for bouton in (self.bouton_fichiers, self.bouton_dossier):
            bouton.setEnabled(pret)
        self.bouton_demo.setEnabled(True)   # elle bascule sur son propre capteur
        self.bouton_modifier.setEnabled(pret)
        self.bouton_voir.setEnabled(bool(self.tableau.selectedItems()) and pret)
        self.bouton_retirer.setEnabled(bool(self._lignes_cochees()))
        self.bouton_vider.setEnabled(bool(self.essais))
        if not pret:
            self.etat.setText("Sélectionnez ou créez un capteur avant d'importer "
                              "des essais.")
        elif not self.essais:
            self.etat.setText("Aucun essai chargé pour ce capteur.")

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
        # Sur son propre capteur : on ne mélange pas des essais fictifs à
        # l'historique d'un capteur suivi.
        identifiant = self.stockage.capteur(CAPTEUR_DEMO)
        if identifiant != self.capteur_id:
            self.rafraichir_capteurs(selectionner=identifiant)
        # Avec son propre mappage : la démonstration doit marcher même une fois
        # config.yaml adapté aux voies du site. Le générateur construit son
        # couple_estime par roue : on force cette hypothèse même si le site a
        # activé couple_estime_total_essieu, sinon la démo serait faussée d'un
        # facteur ~2 sans raison.
        config = dict(self.config)
        config["signaux"] = MAPPAGE_DEMO
        config["traitement"] = {**(self.config.get("traitement", {}) or {}),
                                "couple_estime_total_essieu": False}
        self._lancer(trouves, config)

    def _configurer_voies(self):
        from .dialogue_mappage import DialogueMappage  # import tardif : évite un cycle
        if DialogueMappage(self.config, self.chemin_config, self).exec_():
            self.etat.setText("Mappage des voies enregistré.")

    def _visualiser(self):
        """Ouvre la visualisation de l'essai sélectionné, relu depuis son fichier."""
        from .fenetre_essai import FenetreEssai
        ligne = self.tableau.currentRow()
        if not 0 <= ligne < len(self.essais):
            return
        essai = self.essais[ligne]
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            detail = lire_detail(essai.chemin, self.config)
        except Exception as erreur:
            self.etat.setText(f"Essai illisible — {essai.nom} : {erreur}")
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        FenetreEssai(detail, self.analyse, self._mode, self.stockage, self).exec_()

    # --- chargement ---
    def _lancer(self, chemins: list[Path], config: dict | None = None):
        if self.capteur_id is None:
            self.etat.setText("Sélectionnez ou créez un capteur avant d'importer "
                              "des essais.")
            return
        if self._chargeur is not None and self._chargeur.isRunning():
            return
        self._ajoutes = self._doublons = 0
        self._echecs: list[str] = []
        self._activer(False)
        self.progression.setRange(0, len(chemins))
        self.progression.setValue(0)
        self.progression.show()
        self._chargeur = Chargeur(chemins, config or self.config, self)
        self._chargeur.progression.connect(self._avancer)
        self._chargeur.essai_lu.connect(self._ajouter)
        self._chargeur.echec.connect(self._signaler)
        self._chargeur.fini.connect(self._terminer)
        self._chargeur.start()

    def _activer(self, actif: bool):
        for bouton in (self.bouton_mappage, self.bouton_fichiers, self.bouton_dossier,
                       self.bouton_demo, self.bouton_retirer, self.bouton_vider,
                       self.bouton_nouveau, self.capteurs):
            bouton.setEnabled(actif)

    def _avancer(self, rang: int, total: int, nom: str):
        self.progression.setValue(rang - 1)
        self.etat.setText(f"Lecture de l'essai {rang} sur {total} — {nom}")

    def _signaler(self, nom: str, message: str):
        self._echecs.append(f"{nom} : {message}")
        self.etat.setText(f"Essai ignoré — {nom} : {message}")

    def _ajouter(self, essai):
        """Complète la liste du capteur actif, sans jamais la remplacer."""
        ajoutes, doublons = fusionner_essais(self.essais, [essai])
        self._ajoutes += ajoutes
        self._doublons += doublons

    def _terminer(self):
        self.progression.hide()
        self._activer(True)
        self._remplir_tableau()
        self.stockage.enregistrer_essais(self.capteur_id, self.essais)
        if self._echecs and not self._ajoutes:
            # Ne pas masquer la cause derrière un décompte à zéro : c'est le
            # message qui permet de comprendre qu'un mappage ne convient pas.
            self.etat.setText(
                f"Aucun essai exploitable sur {len(self._echecs)} fichiers — "
                f"{self._echecs[0]}. Vérifiez le mappage des voies.")
        else:
            message = f"{len(self.essais)} essais chargés — {self._ajoutes} ajoutés"
            if self._doublons:
                message += f", {self._doublons} déjà présents et ignorés"
            if self._echecs:
                message += f", {len(self._echecs)} illisibles"
            self.etat.setText(message + ".")
        self._actualiser_boutons()
        self.essais_charges.emit(list(self.essais))

    # --- tableau ---
    def _remplir_tableau(self):
        self.tableau.blockSignals(True)     # sinon itemChanged part à chaque cellule
        self.tableau.clearContents()
        self.tableau.setRowCount(0)
        for essai in self.essais:
            self._inserer_ligne(essai)
        self.tableau.blockSignals(False)
        self.tableau.viewport().update()

    def _inserer_ligne(self, essai):
        source = (self.config.get("detection", {}) or {}).get("source", "voie_opposee")
        resume = essai.resume(source)
        minutes, secondes = divmod(int(essai.duree_s), 60)
        valeurs = ("", horodatage(essai.date), essai.nom,
                   f"{minutes} min {secondes:02d} s",
                   theme.nombre(essai.couple_max, 0, "N·m"),
                   theme.nombre(resume.biais, 2, "N·m", signe=True),
                   theme.nombre(resume.ecart_type, 2, "N·m"), "")
        ligne = self.tableau.rowCount()
        self.tableau.insertRow(ligne)
        for colonne, valeur in enumerate(valeurs):
            cellule = QtWidgets.QTableWidgetItem(valeur)
            if colonne == 0:
                cellule.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)
                cellule.setCheckState(QtCore.Qt.Unchecked)
            elif colonne >= 3:
                cellule.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            self.tableau.setItem(ligne, colonne, cellule)

    def _lignes_cochees(self) -> list[int]:
        cochees = []
        for ligne in range(self.tableau.rowCount()):
            cellule = self.tableau.item(ligne, 0)
            if cellule is not None and cellule.checkState() == QtCore.Qt.Checked:
                cochees.append(ligne)
        return cochees

    def _retirer_selection(self):
        """Retire les essais cochés de la liste en mémoire."""
        cochees = set(self._lignes_cochees())
        if not cochees:
            self.etat.setText("Cochez les essais à retirer.")
            return
        restants = [e for i, e in enumerate(self.essais) if i not in cochees]
        self.essais[:] = restants        # on modifie la liste en place
        self._remplir_tableau()
        self.etat.setText(f"{len(cochees)} essais retirés — "
                          f"{len(self.essais)} restants.")
        self._actualiser_boutons()
        self.essais_charges.emit(list(self.essais))

    def _vider(self):
        if not self.essais:
            return
        reponse = QtWidgets.QMessageBox.question(
            self, "Vider la liste",
            f"Retirer les {len(self.essais)} essais de ce capteur de la liste ?\n"
            "Leur historique reste dans la fiche de vie.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No)
        if reponse != QtWidgets.QMessageBox.Yes:
            return
        self.essais.clear()
        self._remplir_tableau()
        self.etat.setText("Liste vidée.")
        self._actualiser_boutons()
        self.essais_charges.emit([])

    def appliquer_theme(self, mode: str):
        """Mémorise le thème : la visualisation d'essai s'ouvre dans le même."""
        self._mode = mode

    # --- verdicts par essai ---
    def colorer(self, analyse: Analyse):
        """Reporte le verdict de chaque essai dans la dernière colonne."""
        self.analyse = analyse
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
            cellule = QtWidgets.QTableWidgetItem(theme.pastille(statut), libelle)
            self.tableau.setItem(ligne, len(COLONNES) - 1, cellule)
