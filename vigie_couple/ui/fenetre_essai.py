# -*- coding: utf-8 -*-
"""Visualisation d'un essai : signaux bruts, fenêtres retenues, zones de dérive.

Sert autant à examiner une dérive qu'à comprendre pourquoi un essai ne produit
aucune fenêtre exploitable — la répartition des phases le dit d'un coup d'œil.
"""
from __future__ import annotations

import numpy as np
from PyQt5 import QtWidgets

from ..coeur.detection import Analyse, horodatage, statut_fenetre
from ..coeur.lecture_mf4 import DetailEssai, lire_voie, voies_disponibles
from . import theme

ONGLETS = ("Couple", "Résidu", "Vitesse", "Tracé libre")

# Opérations du tracé libre : libellé affiché → (calcul, gabarit de titre).
# Le titre passe par un gabarit et non par un remplacement de « A » et « B » :
# un nom de voie contenant ces lettres corromprait le libellé.
OPERATIONS = {
    "Voie A seule": (lambda a, b: a, "{a}"),
    "A + B": (lambda a, b: a + b, "{a} + {b}"),
    "A − B": (lambda a, b: a - b, "{a} − {b}"),
    "Moyenne (A + B) / 2": (lambda a, b: 0.5 * (a + b), "({a} + {b}) / 2"),
}


def zones_par_statut(detail: DetailEssai, analyse: Analyse | None) -> list[tuple]:
    """Fusionne les fenêtres voisines de même verdict en plages continues.

    Une plage par zone plutôt qu'un rectangle par fenêtre : le tracé reste
    lisible et léger même avec une centaine de fenêtres.
    """
    if not detail.fenetres:
        return []
    if analyse is None:
        statuts = ["conforme"] * len(detail.fenetres)
    else:
        echelle = analyse.echelle_fenetre
        statuts = [statut_fenetre(r, analyse.mu0, echelle, analyse.reglages)
                   for r in detail.residus_fenetres]
    t = detail.t
    plages, debut, courant = [], detail.fenetres[0].start, statuts[0]
    precedente = detail.fenetres[0]
    for fenetre, statut in zip(detail.fenetres[1:], statuts[1:]):
        contigu = fenetre.start == precedente.stop
        if statut != courant or not contigu:
            plages.append((float(t[debut]), float(t[precedente.stop - 1]), courant))
            debut, courant = fenetre.start, statut
        precedente = fenetre
    plages.append((float(t[debut]), float(t[precedente.stop - 1]), courant))
    return plages


class FenetreEssai(QtWidgets.QDialog):
    """Un seul graphique à la fois, choisi par trois onglets discrets."""

    def __init__(self, detail: DetailEssai, analyse: Analyse | None,
                 mode: str = "clair", parent=None):
        super().__init__(parent)
        self.detail = detail
        self.analyse = analyse
        self._mode = mode
        self._cache: dict[str, tuple] = {}   # voies du tracé libre déjà lues
        indicateurs = detail.indicateurs
        self.setWindowTitle(f"Essai {indicateurs.nom}")
        self.resize(960, 640)

        disposition = theme.marges(QtWidgets.QVBoxLayout(self), theme.MARGE)
        disposition.addWidget(theme.etiquette(indicateurs.nom, "titre"))
        disposition.addWidget(theme.etiquette(self._resume(), "secondaire"))
        disposition.addSpacing(theme.ESPACE)

        self.onglets = QtWidgets.QTabBar()
        self.onglets.setDrawBase(False)
        for nom in ONGLETS:
            self.onglets.addTab(nom)
        self.onglets.currentChanged.connect(self._tracer)
        self.graphique = theme.Graphique(mode)
        self.graphique.setMinimumHeight(320)
        # Fenêtre d'inspection : le zoom sert à séparer des voies quasi confondues.
        self.graphique.setMouseEnabled(x=True, y=True)
        disposition.addWidget(self.onglets)
        disposition.addWidget(self.graphique, 1)

        self.commandes = self._construire_commandes()
        disposition.addWidget(self.commandes)

        self.legende_zones = theme.etiquette("", "secondaire")
        self.legende_zones.setWordWrap(True)
        disposition.addWidget(self.legende_zones)

        boutons = QtWidgets.QDialogButtonBox()
        vue = boutons.addButton("Vue d'ensemble",
                                QtWidgets.QDialogButtonBox.ResetRole)
        vue.setToolTip("Annule le zoom et réajuste les échelles.")
        vue.clicked.connect(lambda: self.graphique.getPlotItem().autoRange())
        fermer = boutons.addButton("Fermer", QtWidgets.QDialogButtonBox.RejectRole)
        fermer.clicked.connect(self.reject)
        disposition.addWidget(boutons)
        self._tracer()

    def _construire_commandes(self) -> QtWidgets.QWidget:
        """Choix des voies du tracé libre ; masqué sur les autres onglets."""
        boite = QtWidgets.QWidget()
        ligne = theme.marges(QtWidgets.QHBoxLayout(boite), 0, theme.ESPACE)
        try:
            voies = voies_disponibles(self.detail.indicateurs.chemin)
        except Exception:
            voies = []
        self.voie_a = QtWidgets.QComboBox()
        self.voie_b = QtWidgets.QComboBox()
        self.operation = QtWidgets.QComboBox()
        self.voie_a.addItems(voies)
        self.voie_b.addItems(voies)
        self.operation.addItems(OPERATIONS)
        if len(voies) > 1:
            self.voie_b.setCurrentIndex(1)
        for widget in (self.voie_a, self.operation, self.voie_b):
            widget.setMinimumWidth(150)
            widget.currentIndexChanged.connect(self._tracer)
        ligne.addWidget(theme.etiquette("Voie A", "secondaire"))
        ligne.addWidget(self.voie_a, 1)
        ligne.addWidget(theme.etiquette("Opération", "secondaire"))
        ligne.addWidget(self.operation)
        ligne.addWidget(theme.etiquette("Voie B", "secondaire"))
        ligne.addWidget(self.voie_b, 1)
        boite.hide()
        return boite

    def _resume(self) -> str:
        """Une ligne : ce qu'il faut savoir de l'essai avant de lire le tracé."""
        ind = self.detail.indicateurs
        resume = ind.resume(self.analyse.source if self.analyse else "voie_opposee")
        parts = self.detail.repartition_phases()
        phases = ", ".join(f"{nom} {part:.0%}" for nom, part in parts.items() if part)
        return (f"{horodatage(ind.date)}  ·  durée {ind.duree_s:.0f} s  ·  "
                f"couple max {theme.nombre(ind.couple_max, 0, 'N·m')}  ·  "
                f"biais {theme.nombre(resume.biais, 2, 'N·m', signe=True)}  ·  "
                f"{len(self.detail.fenetres)} fenêtres retenues "
                f"({self.detail.part_exploitable():.0%} de l'essai)\n"
                f"Phases : {phases}")

    def _tracer(self):
        detail, c = self.detail, theme.couleurs(self._mode)
        t = detail.t
        onglet = ONGLETS[self.onglets.currentIndex()]

        if onglet == "Couple":
            self.graphique.reinitialiser("Couple aux roues", "N·m", "Temps (s)",
                                         "t = {:.1f} s")
            self.graphique.legende()
            # Le couple estimé d'abord : les voies mesurées restent au premier plan.
            if "couple_estime" in detail.voies:
                self.graphique.courbe(t, detail.voies["couple_estime"], c["serie3"],
                                      "Couple estimé", marqueurs=False, pointille=True)
            self.graphique.courbe(t, detail.voies["couple_droit"], c["serie2"],
                                  "Voie droite", marqueurs=False)
            self.graphique.courbe(t, detail.voies["couple_gauche"], c["serie1"],
                                  "Voie gauche", marqueurs=False)
        elif onglet == "Résidu":
            # Une valeur par fenêtre, pas le résidu instantané : à 20 Hz le bruit
            # d'échantillon (± 20 N·m) noierait complètement une dérive de 6 N·m.
            self.graphique.reinitialiser(
                "Résidu par fenêtre — voie gauche − voie droite", "N·m",
                "Temps (s)", "t = {:.1f} s")
            centres = np.array([float(t[(f.start + f.stop) // 2])
                                for f in detail.fenetres])
            if self.analyse is not None and centres.size:   # bande d'une fenêtre
                demi = 1.96 * self.analyse.echelle_fenetre
                self.graphique.bande(centres,
                                     np.full(centres.size, self.analyse.mu0 - demi),
                                     np.full(centres.size, self.analyse.mu0 + demi),
                                     c["texte_secondaire"])
            self.graphique.courbe(centres, np.array(detail.residus_fenetres),
                                  c["serie1"])
        elif onglet == "Vitesse":
            self.graphique.reinitialiser("Vitesse véhicule", "km/h", "Temps (s)",
                                         "t = {:.1f} s")
            vitesse = detail.voies.get("vitesse_vehicule")
            if vitesse is None:
                self.graphique.reinitialiser("Voie de vitesse non mappée", "km/h",
                                             "Temps (s)", "t = {:.1f} s")
            else:
                self.graphique.courbe(t, vitesse, c["serie1"], unite="km/h",
                                      marqueurs=False)
        else:
            self._tracer_libre(t, c)

        self.commandes.setVisible(onglet == "Tracé libre")
        self._surligner()

    def _voie(self, nom: str):
        """Lit une voie à la demande et la garde en mémoire pour cette fenêtre."""
        if nom not in self._cache:
            self._cache[nom] = lire_voie(self.detail.indicateurs.chemin, nom,
                                         self.detail.t)
        return self._cache[nom]

    def _tracer_libre(self, t, c):
        """Trace n'importe quelle voie du fichier, seule ou combinée à une autre."""
        nom_a = self.voie_a.currentText()
        nom_b = self.voie_b.currentText()
        libelle = self.operation.currentText()
        seule = libelle == "Voie A seule"
        if not nom_a:
            self.graphique.reinitialiser("Aucune voie disponible", "", "Temps (s)",
                                         "t = {:.1f} s")
            return

        lu_a = self._voie(nom_a)
        lu_b = None if seule else self._voie(nom_b)
        if lu_a is None or (not seule and lu_b is None):
            manquante = nom_a if lu_a is None else nom_b
            self.graphique.reinitialiser(f"Voie « {manquante} » non traçable",
                                         "", "Temps (s)", "t = {:.1f} s")
            return

        valeurs_a, unite = lu_a
        if seule:
            valeurs, titre = valeurs_a, nom_a
        else:
            calcul, gabarit = OPERATIONS[libelle]
            valeurs = calcul(valeurs_a, lu_b[0])
            titre = gabarit.format(a=nom_a, b=nom_b)
            if lu_b[1] and lu_b[1] != unite:   # unités hétérogènes : on le dit
                unite = f"{unite} / {lu_b[1]}"
        self.graphique.reinitialiser(titre, unite, "Temps (s)", "t = {:.1f} s")
        self.graphique.courbe(t, valeurs, c["serie1"], unite=unite, marqueurs=False)

    def _surligner(self):
        """Surligne les fenêtres retenues, en couleur de statut si elles dérivent."""
        plages = zones_par_statut(self.detail, self.analyse)
        compte = {"conforme": 0, "vigilance": 0, "non_conforme": 0}
        for debut, fin, statut in plages:
            compte[statut] += 1
            couleur = (theme.couleurs(self._mode)["grille"] if statut == "conforme"
                       else theme.couleur_statut(statut))
            opacite = 70 if statut == "conforme" else 60
            self.graphique.zone(debut, fin, couleur, opacite)
        if not plages:
            self.legende_zones.setText(
                "Aucune fenêtre exploitable : vérifiez le mappage des voies et les "
                "seuils de la section « traitement » de config.yaml.")
            return
        # Toujours un libellé texte : la couleur seule ne porte jamais le sens.
        self.legende_zones.setText(
            f"Fond gris : {compte['conforme']} plages retenues et conformes.  ·  "
            f"Fond orange : {compte['vigilance']} plages hors bande d'accord "
            "(±1,96 σ₀).  ·  "
            f"Fond rouge : {compte['non_conforme']} plages au-delà de l'écart "
            "maximal admissible.  ·  Molette pour zoomer, double-clic droit pour "
            "revenir à la vue d'ensemble.")

    def appliquer_theme(self, mode: str):
        self._mode = mode
        self.graphique.appliquer_theme(mode)
        self._tracer()
