# -*- coding: utf-8 -*-
"""Écran 2 — Surveillance : le verdict, un seul graphique, trois tuiles.

C'est l'écran principal : il doit tenir en un coup d'œil. Les paramètres de
réglage sont rangés dans un panneau latéral fermé par défaut.
"""
from __future__ import annotations

import numpy as np
from PyQt5 import QtCore, QtWidgets

from ..coeur.detection import SOURCES, Analyse, Reglages, essais_depuis_conforme
from . import theme

ONGLETS = ("Résidu", "CUSUM", "EWMA")


class Tuile(QtWidgets.QWidget):
    """Une statistique : une valeur lisible, un libellé discret."""

    def __init__(self, libelle: str, parent=None):
        super().__init__(parent)
        self.setFixedWidth(210)
        disposition = theme.marges(QtWidgets.QVBoxLayout(self), 0, 2)
        self.valeur = theme.etiquette("—", "valeur")
        self.libelle = theme.etiquette(libelle, "secondaire")
        self.libelle.setWordWrap(True)
        disposition.addWidget(self.valeur)
        disposition.addWidget(self.libelle)

    def definir(self, texte: str):
        self.valeur.setText(texte)


class PanneauReglages(QtWidgets.QWidget):
    """Panneau latéral repliable : λ, L, k, h, source et écart admissible."""

    modifie = QtCore.pyqtSignal()

    def __init__(self, reglages: Reglages, parent=None):
        super().__init__(parent)
        self.setFixedWidth(250)
        disposition = theme.marges(QtWidgets.QFormLayout(self), theme.ESPACE)
        disposition.setLabelAlignment(QtCore.Qt.AlignLeft)
        disposition.setRowWrapPolicy(QtWidgets.QFormLayout.WrapAllRows)

        self.source = QtWidgets.QComboBox()
        for cle, libelle in SOURCES.items():
            self.source.addItem(libelle, cle)
        self.source.setCurrentIndex(max(0, list(SOURCES).index(reglages.source)))
        self.source.setToolTip("Sources classées par fiabilité décroissante.")
        self.champs = {
            "n_reference": self._entier("Essais de référence", 3, 100,
                                        reglages.n_reference),
            "lambda_ewma": self._reel("λ (EWMA)", 0.01, 1.0, 0.01, 2,
                                      reglages.lambda_ewma),
            "limite_L": self._reel("L (EWMA)", 1.0, 5.0, 0.1, 1, reglages.limite_L),
            "k_cusum": self._reel("k (CUSUM)", 0.1, 2.0, 0.1, 1, reglages.k_cusum),
            "h_cusum": self._reel("h (CUSUM)", 1.0, 12.0, 0.5, 1, reglages.h_cusum),
            "ecart_max_admissible": self._reel("Écart maximal admissible (N·m)",
                                               1.0, 200.0, 1.0, 0,
                                               reglages.ecart_max_admissible),
        }
        disposition.addRow(theme.etiquette("Réglages", "titre"))
        disposition.addRow("Source du résidu", self.source)
        for cle, (libelle, widget) in self.champs.items():
            disposition.addRow(libelle, widget)
        self.source.currentIndexChanged.connect(self.modifie.emit)
        self._modele = reglages

    def _reel(self, libelle, mini, maxi, pas, decimales, valeur):
        boite = QtWidgets.QDoubleSpinBox()
        # Pas de petites flèches : la valeur se saisit, ou se règle à la molette.
        boite.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        boite.setRange(mini, maxi)
        boite.setSingleStep(pas)
        boite.setDecimals(decimales)
        boite.setValue(valeur)
        boite.valueChanged.connect(self.modifie.emit)
        return libelle, boite

    def _entier(self, libelle, mini, maxi, valeur):
        boite = QtWidgets.QSpinBox()
        boite.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        boite.setRange(mini, maxi)
        boite.setValue(valeur)
        boite.valueChanged.connect(self.modifie.emit)
        return libelle, boite

    def reglages(self) -> Reglages:
        """Réglages courants, tels que saisis par l'opérateur."""
        valeurs = {cle: widget.value() for cle, (_, widget) in self.champs.items()}
        valeurs["n_reference"] = int(valeurs["n_reference"])
        return Reglages(source=self.source.currentData(),
                        zero_vigilance=self._modele.zero_vigilance,
                        zero_majeur=self._modele.zero_majeur, **valeurs)


class EcranSurveillance(QtWidgets.QWidget):
    """Verdict unique en haut, un graphique au milieu, trois tuiles en bas."""

    reglages_modifies = QtCore.pyqtSignal(object)

    def __init__(self, reglages: Reglages, mode: str = "clair", parent=None):
        super().__init__(parent)
        self._mode = mode
        self._analyse: Analyse | None = None
        colonne = theme.marges(QtWidgets.QVBoxLayout(), theme.MARGE)

        # On doit toujours savoir de quel capteur parle le verdict affiché.
        self.capteur = theme.etiquette("Aucun capteur sélectionné", "secondaire")
        colonne.addWidget(self.capteur)

        # --- verdict ---
        ligne = QtWidgets.QHBoxLayout()
        ligne.setSpacing(theme.ESPACE + 4)
        self.pastille = QtWidgets.QLabel()
        self.pastille.setFixedSize(26, 26)
        self.verdict = theme.etiquette("En attente", "verdict")
        ligne.addWidget(self.pastille)
        ligne.addWidget(self.verdict)
        ligne.addStretch(1)
        self.phrase = theme.etiquette("Chargez une campagne dans l'écran Campagne.")
        self.phrase.setWordWrap(True)
        self.cause = theme.etiquette("", "secondaire")
        self.cause.setWordWrap(True)
        colonne.addLayout(ligne)
        colonne.addWidget(self.phrase)
        colonne.addWidget(self.cause)
        colonne.addSpacing(theme.MARGE)

        # --- un seul graphique, trois onglets discrets ---
        self.onglets = QtWidgets.QTabBar()
        self.onglets.setDrawBase(False)
        for nom in ONGLETS:
            self.onglets.addTab(nom)
        self.onglets.currentChanged.connect(self._tracer)
        self.graphique = theme.Graphique(mode)
        self.graphique.setMinimumHeight(280)
        colonne.addWidget(self.onglets)
        colonne.addWidget(self.graphique, 1)
        colonne.addSpacing(theme.MARGE)

        # --- trois tuiles ---
        tuiles = QtWidgets.QHBoxLayout()
        tuiles.setSpacing(theme.MARGE)
        self.tuiles = (Tuile("Biais courant"),
                       Tuile("Essais depuis le dernier contrôle conforme"),
                       Tuile("Jours avant échéance d'étalonnage"))
        for tuile in self.tuiles:
            tuiles.addWidget(tuile)
        tuiles.addStretch(1)
        colonne.addLayout(tuiles)

        # --- panneau latéral, fermé par défaut ---
        self.panneau = PanneauReglages(reglages)
        self.panneau.hide()
        self.panneau.modifie.connect(
            lambda: self.reglages_modifies.emit(self.panneau.reglages()))
        self.bouton_panneau = QtWidgets.QPushButton("Réglages ▸")
        self.bouton_panneau.setCheckable(True)
        self.bouton_panneau.toggled.connect(self._basculer_panneau)

        cote = theme.marges(QtWidgets.QVBoxLayout(), theme.MARGE, theme.ESPACE)
        cote.addWidget(self.bouton_panneau, 0, QtCore.Qt.AlignRight)
        cote.addWidget(self.panneau)
        cote.addStretch(1)

        principale = QtWidgets.QHBoxLayout(self)
        principale.setContentsMargins(0, 0, 0, 0)
        principale.addLayout(colonne, 1)
        principale.addLayout(cote)
        self._peindre_pastille("indetermine")

    # --- affichage ---
    def _basculer_panneau(self, ouvert: bool):
        self.panneau.setVisible(ouvert)
        self.bouton_panneau.setText("Réglages ▾" if ouvert else "Réglages ▸")

    def _peindre_pastille(self, statut: str):
        couleur = theme.couleur_statut(statut)
        self.pastille.setStyleSheet(
            f"background: {couleur}; border-radius: 13px;")

    def nommer_capteur(self, libelle: str):
        """Rappelle en permanence le capteur auquel se rapporte le verdict."""
        self.capteur.setText(f"Capteur suivi : {libelle}" if libelle
                             else "Aucun capteur sélectionné")

    def afficher(self, analyse: Analyse, jours_restants: int | None = None):
        """Met à jour le verdict, le graphique et les trois tuiles."""
        self._analyse = analyse
        verdict = analyse.verdict
        self._peindre_pastille(verdict.statut)
        self.verdict.setText(f"{verdict.icone}  {verdict.libelle}")
        self.phrase.setText(verdict.phrase)
        self.cause.setText(analyse.discrimination.phrase)

        courant = analyse.x[-1] if analyse.x.size else None
        self.tuiles[0].definir(theme.nombre(courant, 2, "N·m", signe=True))
        self.tuiles[1].definir(str(essais_depuis_conforme(analyse)))
        if jours_restants is None:
            self.tuiles[2].definir("—")
        elif jours_restants < 0:
            self.tuiles[2].definir(f"dépassée de {-jours_restants} j")
        else:
            self.tuiles[2].definir(f"{jours_restants} j")
        self._tracer()

    def _tracer(self):
        analyse = self._analyse
        if analyse is None or analyse.x.size == 0:
            self.graphique.reinitialiser("Aucun essai chargé", "N·m")
            return
        c = theme.couleurs(self._mode)
        x = np.arange(1, analyse.x.size + 1)
        onglet = ONGLETS[self.onglets.currentIndex()]

        if onglet == "Résidu":
            source = SOURCES.get(analyse.source, analyse.source)
            self.graphique.reinitialiser(f"Résidu essai par essai — {source}", "N·m")
            # Une bande par segment : chacun a sa propre référence.
            for segment in analyse.segments or []:
                if segment.taille == 0:
                    continue
                xs = x[segment.debut:segment.fin]
                demi = 1.96 * segment.sigma0
                self.graphique.bande(xs, np.full(xs.size, segment.mu0 - demi),
                                     np.full(xs.size, segment.mu0 + demi),
                                     c["texte_secondaire"])
            self.graphique.courbe(x, analyse.x, c["serie1"], unite="N·m")
        elif onglet == "CUSUM":
            self.graphique.reinitialiser(
                "Carte CUSUM — somme cumulée et ligne de décision", "N·m")
            self.graphique.legende()
            self.graphique.courbe(x, analyse.cusum.c_plus, c["serie1"], "C⁺")
            self.graphique.courbe(x, analyse.cusum.c_moins, c["serie2"], "C⁻")
            self.graphique.courbe(x, np.full(x.size, analyse.cusum.H),
                                  c["texte_secondaire"], marqueurs=False,
                                  pointille=True, survol=False)
        else:
            self.graphique.reinitialiser(
                "Carte EWMA — statistique lissée et limites de contrôle", "N·m")
            self.graphique.courbe(x, analyse.ewma.z, c["serie1"], unite="N·m")
            for limite in (analyse.ewma.limite_sup, analyse.ewma.limite_inf):
                self.graphique.courbe(x, limite, c["texte_secondaire"],
                                      marqueurs=False, pointille=True, survol=False)

        indice = analyse.verdict.indice_essai
        if indice is not None:                      # repère de l'essai en cause
            self.graphique.repere(indice + 1, c["texte_secondaire"])
        # Traits de rupture : les essais antérieurs restent affichés, mais on
        # voit d'où repart la référence, et pourquoi.
        for segment in analyse.segments or []:
            if segment.rupture is None:
                continue
            libelle = segment.rupture.motif or "réinitialisation"
            self.graphique.repere(segment.debut + 0.5, c["serie2"], libelle)

    # --- thème et export ---
    def appliquer_theme(self, mode: str):
        self._mode = mode
        self.graphique.appliquer_theme(mode)
        if self._analyse is not None:
            self._peindre_pastille(self._analyse.verdict.statut)
        self._tracer()

    def image_residu(self, chemin) -> bool:
        """Capture le graphique du résidu pour la fiche de synthèse PDF."""
        precedent = self.onglets.currentIndex()
        self.onglets.setCurrentIndex(0)
        self._tracer()
        QtWidgets.QApplication.processEvents()
        ok = bool(self.graphique.grab().save(str(chemin), "PNG"))
        self.onglets.setCurrentIndex(precedent)
        return ok
