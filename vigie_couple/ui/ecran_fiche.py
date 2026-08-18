# -*- coding: utf-8 -*-
"""Écran 3 — Fiche de vie : identification, historique, échéance, export PDF."""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

from PyQt5 import QtCore, QtWidgets
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from ..coeur.detection import SOURCES, Analyse, date_courte
from ..coeur.stockage import PLAFOND_JOURS, Stockage, jours_depuis, jours_restants
from . import theme
from .ecran_surveillance import Tuile

CHAMPS = (("reference", "Référence"), ("numero_serie", "Numéro de série"),
          ("arbre", "Arbre"), ("vehicule", "Véhicule"))

# Motifs de réinitialisation du suivi, du plus courant au plus rare.
MOTIFS = ("Réétalonnage", "Remplacement du capteur", "Réfection du collage",
          "Changement d'installation", "Autre")


class DialogueRupture(QtWidgets.QDialog):
    """Motif d'une réinitialisation du suivi. N'efface aucun essai."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Réinitialiser le suivi")
        formulaire = theme.marges(QtWidgets.QFormLayout(self), theme.MARGE)
        explication = theme.etiquette(
            "Le suivi repart d'une nouvelle référence : les cartes de contrôle "
            "sont remises à zéro et μ₀, σ₀ seront réestimés sur les essais qui "
            "suivent. Les essais antérieurs sont conservés et restent affichés.",
            "secondaire")
        explication.setWordWrap(True)
        explication.setFixedWidth(380)
        formulaire.addRow(explication)
        self.jour = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
        self.jour.setDisplayFormat("dd/MM/yyyy")
        self.jour.setCalendarPopup(True)
        self.motif = QtWidgets.QComboBox()
        self.motif.addItems(MOTIFS)
        self.commentaire = QtWidgets.QPlainTextEdit()
        self.commentaire.setFixedHeight(60)
        formulaire.addRow("Date", self.jour)
        formulaire.addRow("Motif", self.motif)
        formulaire.addRow("Commentaire", self.commentaire)
        boutons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        boutons.button(QtWidgets.QDialogButtonBox.Ok).setText("Réinitialiser")
        boutons.button(QtWidgets.QDialogButtonBox.Cancel).setText("Annuler")
        boutons.accepted.connect(self.accept)
        boutons.rejected.connect(self.reject)
        formulaire.addRow(boutons)

    def valeurs(self) -> tuple[str, str, str]:
        return (self.jour.date().toString("yyyy-MM-dd"),
                self.motif.currentText(), self.commentaire.toPlainText().strip())


class DialogueReleve(QtWidgets.QDialog):
    """Petite saisie : un étalonnage ou un contrôle par résistance de shunt."""

    def __init__(self, titre: str, libelle_valeur: str, libelle_texte: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(titre)
        formulaire = theme.marges(QtWidgets.QFormLayout(self), theme.MARGE)
        self.jour = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
        self.jour.setDisplayFormat("dd/MM/yyyy")
        self.valeur = QtWidgets.QDoubleSpinBox()
        self.valeur.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.valeur.setRange(-100.0, 100.0)
        self.valeur.setDecimals(2)
        self.texte = QtWidgets.QLineEdit()
        formulaire.addRow("Date", self.jour)
        formulaire.addRow(libelle_valeur, self.valeur)
        formulaire.addRow(libelle_texte, self.texte)
        boutons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        boutons.button(QtWidgets.QDialogButtonBox.Ok).setText("Enregistrer")
        boutons.button(QtWidgets.QDialogButtonBox.Cancel).setText("Annuler")
        boutons.accepted.connect(self.accept)
        boutons.rejected.connect(self.reject)
        formulaire.addRow(boutons)

    def valeurs(self) -> tuple[str, float, str]:
        return (self.jour.date().toString("yyyy-MM-dd"),
                self.valeur.value(), self.texte.text())


class EcranFiche(QtWidgets.QWidget):
    """Historique persistant d'un capteur, lu et écrit dans le fichier SQLite."""

    suivi_reinitialise = QtCore.pyqtSignal()

    def __init__(self, stockage: Stockage, capteur_id: int, config: dict,
                 image_residu=None, parent=None):
        super().__init__(parent)
        self.stockage = stockage
        self.capteur_id = capteur_id
        self.config = config
        self.image_residu = image_residu
        self._analyse: Analyse | None = None

        disposition = theme.marges(QtWidgets.QVBoxLayout(self), theme.MARGE)
        disposition.addWidget(theme.etiquette("Fiche de vie du capteur", "titre"))

        identification = QtWidgets.QHBoxLayout()
        identification.setSpacing(theme.MARGE)
        self.champs = {}
        for cle, libelle in CHAMPS:
            colonne = theme.marges(QtWidgets.QVBoxLayout(), 0, 2)
            champ = QtWidgets.QLineEdit()
            champ.editingFinished.connect(self._enregistrer_identification)
            colonne.addWidget(theme.etiquette(libelle, "secondaire"))
            colonne.addWidget(champ)
            identification.addLayout(colonne)
            self.champs[cle] = champ
        disposition.addLayout(identification)
        disposition.addSpacing(theme.MARGE)

        self.echeance = theme.etiquette("")
        self.echeance.setWordWrap(True)
        disposition.addWidget(self.echeance)
        disposition.addSpacing(theme.ESPACE)

        tuiles = QtWidgets.QHBoxLayout()
        tuiles.setSpacing(theme.MARGE * 2)
        self.tuiles = (Tuile("Kilométrage d'essai cumulé"),
                       Tuile("Essais réalisés"),
                       Tuile("Essais à forte sollicitation"))
        for tuile in self.tuiles:
            tuiles.addWidget(tuile)
        tuiles.addStretch(1)
        disposition.addLayout(tuiles)
        disposition.addSpacing(theme.MARGE)

        tables = QtWidgets.QHBoxLayout()
        tables.setSpacing(theme.MARGE)
        self.releves = self._table(("Date", "Type", "Valeur", "Essai"),
                                  "Relevés de zéro et contrôles de shunt", tables)
        self.etalonnages = self._table(("Date", "Incertitude élargie", "Certificat"),
                                      "Étalonnages", tables)
        disposition.addLayout(tables, 1)

        boutons = QtWidgets.QHBoxLayout()
        boutons.setSpacing(theme.ESPACE)
        for libelle, action in (("Ajouter un étalonnage…", self._ajouter_etalonnage),
                                ("Ajouter un contrôle de shunt…", self._ajouter_shunt),
                                ("Réinitialiser le suivi…", self._reinitialiser),
                                ("Exporter la fiche PDF", self._exporter)):
            bouton = QtWidgets.QPushButton(libelle)
            bouton.clicked.connect(action)
            boutons.addWidget(bouton)
        boutons.addStretch(1)
        self.etat = theme.etiquette("", "secondaire")
        disposition.addLayout(boutons)
        disposition.addWidget(self.etat)
        self.rafraichir()

    def _table(self, colonnes, titre: str, parent_layout) -> QtWidgets.QTableWidget:
        colonne = theme.marges(QtWidgets.QVBoxLayout(), 0, theme.ESPACE)
        colonne.addWidget(theme.etiquette(titre, "secondaire"))
        table = QtWidgets.QTableWidget(0, len(colonnes))
        table.setHorizontalHeaderLabels(colonnes)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QtWidgets.QTableWidget.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        colonne.addWidget(table)
        parent_layout.addLayout(colonne)
        return table

    # --- lecture et écriture ---
    def _enregistrer_identification(self):
        infos = {cle: champ.text() for cle, champ in self.champs.items()}
        if infos.get("numero_serie"):
            self.capteur_id = self.stockage.capteur(infos)

    def rafraichir(self):
        """Recharge l'identification, l'usage et les deux historiques."""
        infos = self.stockage.infos_capteur(self.capteur_id)
        defauts = self.config.get("capteur", {}) or {}
        for cle, champ in self.champs.items():
            champ.setText(str(infos.get(cle) or defauts.get(cle, "")))

        seuil = float(defauts.get("couple_forte_sollicitation_nm", 750.0))
        usage = self.stockage.usage(self.capteur_id, seuil)
        self.tuiles[0].definir(theme.nombre(usage["km"], 1, "km"))
        self.tuiles[1].definir(str(usage["essais"]))
        self.tuiles[2].definir(str(usage["severes"]))

        # Les réinitialisations figurent dans le même historique que les
        # relevés : c'est la vie du capteur, dans l'ordre.
        lignes = [(r["date"], r["type"],
                   theme.nombre(r["valeur"], 2, "N·m", signe=True),
                   r["commentaire"] or "")
                  for r in self.stockage.releves(self.capteur_id)]
        lignes += [(r["date"], f"réinitialisation — {r['motif']}", "—",
                    r["commentaire"] or "")
                   for r in self.stockage.ruptures(self.capteur_id)]
        lignes.sort(key=lambda l: l[0], reverse=True)
        self._remplir(self.releves, [(date_courte(d), t, v, c)
                                     for d, t, v, c in lignes])
        self._remplir(self.etalonnages, [
            (date_courte(e["date"]), "± " + theme.nombre(e["incertitude"], 2, "N·m"),
             e["certificat"] or "")
            for e in self.stockage.etalonnages(self.capteur_id)])
        self._afficher_echeance()

    def _remplir(self, table: QtWidgets.QTableWidget, lignes):
        table.setRowCount(len(lignes))
        for rang, ligne in enumerate(lignes):
            for colonne, valeur in enumerate(ligne):
                table.setItem(rang, colonne, QtWidgets.QTableWidgetItem(str(valeur)))

    def _afficher_echeance(self):
        """Alerte visuelle au-delà de 370 jours (plafond RTM ONU n° 21)."""
        dernier = self.stockage.dernier_etalonnage(self.capteur_id)
        ecoules, restants = jours_depuis(dernier), jours_restants(dernier)
        if dernier is None:
            statut, icone = "vigilance", "!"
            texte = "Aucun étalonnage enregistré : renseigner le dernier certificat."
        elif restants < 0:
            statut, icone = "non_conforme", "✕"
            texte = (f"Étalonnage du {date_courte(dernier)} : {ecoules} jours écoulés, "
                     f"au-delà du plafond de {PLAFOND_JOURS} jours. "
                     "Capteur à réétalonner avant tout nouvel essai.")
        elif restants <= 30:
            statut, icone = "vigilance", "!"
            texte = (f"Étalonnage du {date_courte(dernier)} : échéance dans "
                     f"{restants} jours. Réétalonnage à programmer.")
        else:
            statut, icone = "conforme", "✔"
            texte = (f"Étalonnage du {date_courte(dernier)} : valide encore "
                     f"{restants} jours.")
        # L'icône porte la couleur de statut, la phrase reste en couleur de texte.
        self.echeance.setText(
            f'<span style="color:{theme.couleur_statut(statut)}">{icone}</span>'
            f"&nbsp;&nbsp;{texte}")

    def afficher(self, analyse: Analyse):
        """Mémorise l'analyse courante : elle alimente la fiche PDF."""
        self._analyse = analyse
        self.rafraichir()

    # --- actions ---
    def _ajouter_etalonnage(self):
        boite = DialogueReleve("Ajouter un étalonnage", "Incertitude élargie (N·m)",
                               "Référence du certificat", self)
        if boite.exec_() == QtWidgets.QDialog.Accepted:
            jour, valeur, texte = boite.valeurs()
            self.stockage.ajouter_etalonnage(self.capteur_id, jour, valeur, texte)
            self.rafraichir()

    def _ajouter_shunt(self):
        boite = DialogueReleve("Ajouter un contrôle de shunt", "Écart relevé (N·m)",
                               "Commentaire", self)
        if boite.exec_() == QtWidgets.QDialog.Accepted:
            jour, valeur, texte = boite.valeurs()
            self.stockage.ajouter_releve(self.capteur_id, jour, "shunt", valeur, texte)
            self.rafraichir()

    def definir_capteur(self, capteur_id: int):
        """Bascule la fiche sur un autre capteur."""
        if capteur_id == self.capteur_id:
            return
        self.capteur_id = capteur_id
        self.rafraichir()

    def _reinitialiser(self):
        """Repart d'une nouvelle référence, sans rien effacer."""
        boite = DialogueRupture(self)
        if boite.exec_() != QtWidgets.QDialog.Accepted:
            return
        jour, motif, commentaire = boite.valeurs()
        self.stockage.ajouter_rupture(self.capteur_id, jour, motif, commentaire)
        self.rafraichir()
        self.etat.setText(f"Suivi réinitialisé au {date_courte(jour)} — {motif}. "
                          "Les essais antérieurs sont conservés.")
        self.suivi_reinitialise.emit()

    def _exporter(self):
        chemin, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Exporter la fiche de synthèse",
            str(Path.home() / "fiche_vigie_couple.pdf"), "Document PDF (*.pdf)")
        if not chemin:
            return
        image = None
        if self.image_residu is not None:
            provisoire = Path(tempfile.gettempdir()) / "vigie_couple_residu.png"
            if self.image_residu(provisoire):
                image = provisoire
        exporter_fiche(Path(chemin), self.stockage, self.capteur_id,
                       self._analyse, image)
        self.etat.setText(f"Fiche exportée : {chemin}")

    def appliquer_theme(self, mode: str):
        self._afficher_echeance()


# --- Fiche de synthèse d'une page ---
def _fr(texte: str) -> str:
    """Virgule décimale : le PDF est un document français."""
    return texte.replace(".", ",")


def exporter_fiche(chemin: Path, stockage: Stockage, capteur_id: int,
                   analyse: Analyse | None, image: Path | None = None):
    """Verdict, graphique du résidu, derniers relevés. Une page, rien de plus."""
    largeur, hauteur = A4
    page = canvas.Canvas(str(chemin), pagesize=A4)
    marge = 42
    curseur = [hauteur - 52]

    def ligne(texte: str, taille: int = 10, gras: bool = False, saut: int = 14,
              gauche: float = 0.0):
        page.setFont("Helvetica-Bold" if gras else "Helvetica", taille)
        page.drawString(marge + gauche, curseur[0], texte)
        curseur[0] -= saut

    infos = stockage.infos_capteur(capteur_id)
    page.setFont("Helvetica", 9)
    page.drawRightString(largeur - marge, curseur[0], f"Édité le {date.today():%d/%m/%Y}")
    ligne("Vigie Couple — fiche de synthèse", 15, True, 22)
    ligne("  ·  ".join(filter(None, (infos.get("reference"), infos.get("numero_serie"),
                                    infos.get("arbre"), infos.get("vehicule")))), 10,
          saut=34)

    if analyse is not None:
        page.setFillColor(theme.couleur_statut(analyse.verdict.statut))
        page.circle(marge + 6, curseur[0] + 4, 6, stroke=0, fill=1)
        page.setFillColorRGB(0, 0, 0)
        ligne(analyse.verdict.libelle, 13, True, 16, gauche=20)
        for phrase in (analyse.verdict.phrase, analyse.discrimination.phrase):
            if phrase:
                ligne(phrase)
        ligne(_fr(f"Source du résidu : {SOURCES.get(analyse.source, analyse.source)}"
                  f"  ·  référence mu0 = {analyse.mu0:+.2f} N·m,"
                  f" sigma0 = {analyse.sigma0:.2f} N·m  ·  ")
              + f"{len(analyse.essais)} essais", 9, saut=20)

    if image is not None and Path(image).exists():
        page.drawImage(ImageReader(str(image)), marge, curseur[0] - 250,
                       width=largeur - 2 * marge, height=248,
                       preserveAspectRatio=True, anchor="n", mask="auto")
        curseur[0] -= 264

    ligne("Derniers relevés", 10, True, 15)
    for releve in stockage.releves(capteur_id, limite=10):
        page.setFont("Helvetica", 9)
        page.drawString(marge, curseur[0], date_courte(releve["date"]))
        page.drawString(marge + 80, curseur[0], str(releve["type"]))
        page.drawRightString(marge + 210, curseur[0], _fr(f"{releve['valeur']:+.2f} N·m"))
        page.drawString(marge + 230, curseur[0], str(releve["commentaire"] or ""))
        curseur[0] -= 12

    etalonnages = stockage.etalonnages(capteur_id)
    if etalonnages:
        dernier = etalonnages[0]
        curseur[0] -= 10
        ligne("Dernier étalonnage", 10, True, 15)
        ligne(_fr(f"{date_courte(dernier['date'])}  ·  incertitude élargie"
                  f" ± {dernier['incertitude']:.2f} N·m")
              + f"  ·  certificat {dernier['certificat']}  ·  échéance dans "
                f"{jours_restants(dernier['date'])} jours", 9)
    page.showPage()
    page.save()
