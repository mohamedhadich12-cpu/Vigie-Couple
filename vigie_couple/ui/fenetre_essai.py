# -*- coding: utf-8 -*-
"""Visualisation d'un essai : signaux bruts, fenêtres retenues, zones de dérive.

Sert autant à examiner une dérive qu'à comprendre pourquoi un essai ne produit
aucune fenêtre exploitable — la répartition des phases le dit d'un coup d'œil.
"""
from __future__ import annotations

import numpy as np
from PyQt5 import QtCore, QtWidgets

from ..coeur.detection import Analyse, horodatage, statut_fenetre
from ..coeur.lecture_mf4 import DetailEssai, lire_voie, voies_disponibles
from . import theme

# Signaux saisis à la main, mémorisés d'un lancement à l'autre.
CLE_SAISIES = "voies_saisies"

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


def reference_de_l_essai(detail: DetailEssai, analyse: Analyse | None):
    """Référence (μ₀, échelle d'une fenêtre) du segment auquel l'essai appartient.

    Un essai antérieur à une rupture de suivi se juge sur la référence de son
    époque : celle du segment en cours ne le concerne pas, et le surlignage
    serait calculé contre un μ₀ qui n'a jamais été le sien.
    """
    if analyse is None:
        return None
    indice = analyse.indice_de(detail.indicateurs)
    if indice is None:
        return analyse.mu0, analyse.echelle_fenetre
    segment = analyse.segment_pour(indice)
    return segment.mu0, segment.echelle_fenetre


def zones_par_statut(detail: DetailEssai, analyse: Analyse | None) -> list[tuple]:
    """Fusionne les fenêtres voisines de même verdict en plages continues.

    Une plage par zone plutôt qu'un rectangle par fenêtre : le tracé reste
    lisible et léger même avec une centaine de fenêtres.
    """
    if not detail.fenetres:
        return []
    reference = reference_de_l_essai(detail, analyse)
    if reference is None:
        statuts = ["conforme"] * len(detail.fenetres)
    else:
        mu0, echelle = reference
        statuts = [statut_fenetre(r, mu0, echelle, analyse.reglages)
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
                 mode: str = "clair", stockage=None, parent=None,
                 numero: int | None = None):
        super().__init__(parent)
        self.detail = detail
        self.analyse = analyse
        self._mode = mode
        self.stockage = stockage
        self._cache: dict[str, tuple] = {}   # voies du tracé libre déjà lues
        self._voies_fichier: list[str] = []
        indicateurs = detail.indicateurs
        # Le numéro d'abord : c'est celui que citent le verdict et le tableau
        # de la campagne, donc celui par lequel on désigne un essai à l'oral.
        rang = f"Essai n° {numero} — " if numero else "Essai "
        self.setWindowTitle(f"{rang}{indicateurs.nom}")
        self.resize(960, 640)

        disposition = theme.marges(QtWidgets.QVBoxLayout(self), theme.MARGE)
        disposition.addWidget(theme.etiquette(
            f"{rang}{indicateurs.nom}" if numero else indicateurs.nom, "titre"))
        disposition.addWidget(theme.etiquette(self._resume(), "secondaire"))
        disposition.addSpacing(theme.ESPACE)

        self.onglets = QtWidgets.QTabBar()
        self.onglets.setDrawBase(False)
        for nom in ONGLETS:
            self.onglets.addTab(nom)
        self.onglets.currentChanged.connect(self._tracer)
        self.graphique = theme.Graphique(mode)
        self.graphique.setMinimumHeight(260)
        # Fenêtre d'inspection : le zoom sert à séparer des voies quasi confondues.
        self.graphique.setMouseEnabled(x=True, y=True)
        disposition.addWidget(self.onglets)
        disposition.addWidget(self.graphique, 3)

        # Cases à cocher du graphique de couple : une par série.
        self.series = QtWidgets.QWidget()
        ligne_series = theme.marges(QtWidgets.QHBoxLayout(self.series), 0, theme.MARGE)
        self.cases = {}
        for cle, libelle, coche in (("gauche", "Voie gauche", True),
                                    ("droite", "Voie droite", True),
                                    ("estime", "Couple estimé", False),
                                    ("somme", "Somme gauche + droite", False)):
            case = QtWidgets.QCheckBox(libelle)
            case.setChecked(coche)
            case.stateChanged.connect(self._tracer)
            ligne_series.addWidget(case)
            self.cases[cle] = case
        ligne_series.addStretch(1)
        disposition.addWidget(self.series)

        # Second tracé : l'écart gauche − droite, le signal le plus parlant
        # pour voir une voie partir avant que les couples eux-mêmes ne bougent.
        self.ecart = theme.Graphique(mode)
        self.ecart.setMinimumHeight(150)
        self.ecart.setMouseEnabled(x=True, y=True)
        self.ecart.setXLink(self.graphique)     # les deux partagent l'axe du temps
        disposition.addWidget(self.ecart, 1)

        self.commandes = self._construire_commandes()
        disposition.addWidget(self.commandes)

        self.legende_zones = theme.etiquette("", "secondaire")
        self.legende_zones.setWordWrap(True)
        disposition.addWidget(self.legende_zones)

        boutons = QtWidgets.QDialogButtonBox()
        vue = boutons.addButton("Vue d'ensemble",
                                QtWidgets.QDialogButtonBox.ResetRole)
        vue.setToolTip("Annule le zoom et réajuste les échelles.")
        vue.clicked.connect(self._vue_ensemble)
        fermer = boutons.addButton("Fermer", QtWidgets.QDialogButtonBox.RejectRole)
        fermer.clicked.connect(self.reject)
        disposition.addWidget(boutons)
        self._tracer()

    def _vue_ensemble(self):
        for graphe in (self.graphique, self.ecart):
            graphe.getPlotItem().autoRange()

    def _construire_commandes(self) -> QtWidgets.QWidget:
        """Choix des voies du tracé libre ; masqué sur les autres onglets."""
        boite = QtWidgets.QWidget()
        grille = theme.marges(QtWidgets.QGridLayout(boite), 0, theme.ESPACE)
        try:
            self._voies_fichier = voies_disponibles(self.detail.indicateurs.chemin)
        except Exception:
            self._voies_fichier = []
        # Les noms déjà saisis à la main restent proposés d'un essai à l'autre.
        propositions = sorted(set(self._voies_fichier) | set(self._saisies_memorisees()))

        self.voie_a = self._combo_voie(propositions)
        self.voie_b = self._combo_voie(propositions)
        self.etiquette_a = QtWidgets.QLineEdit()
        self.etiquette_b = QtWidgets.QLineEdit()
        for champ in (self.etiquette_a, self.etiquette_b):
            champ.setPlaceholderText("Étiquette (facultatif)")
            champ.setMaximumWidth(160)
            champ.editingFinished.connect(self._tracer)
        self.operation = QtWidgets.QComboBox()
        self.operation.addItems(OPERATIONS)
        self.operation.setMinimumWidth(150)
        self.operation.currentIndexChanged.connect(self._tracer)
        if len(propositions) > 1:
            self.voie_b.setEditText(propositions[1])

        grille.addWidget(theme.etiquette("Voie A", "secondaire"), 0, 0)
        grille.addWidget(self.voie_a, 0, 1)
        grille.addWidget(self.etiquette_a, 0, 2)
        grille.addWidget(theme.etiquette("Opération", "secondaire"), 0, 3)
        grille.addWidget(self.operation, 0, 4)
        grille.addWidget(theme.etiquette("Voie B", "secondaire"), 1, 0)
        grille.addWidget(self.voie_b, 1, 1)
        grille.addWidget(self.etiquette_b, 1, 2)
        self.message_voie = theme.etiquette("", "secondaire")
        grille.addWidget(self.message_voie, 2, 0, 1, 5)
        grille.setColumnStretch(1, 1)
        boite.hide()
        return boite

    def _combo_voie(self, propositions: list[str]) -> QtWidgets.QComboBox:
        """Liste éditable : on peut choisir, ou taper un nom de signal."""
        combo = QtWidgets.QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        combo.addItems(propositions)
        combo.setMinimumWidth(220)
        completeur = QtWidgets.QCompleter(propositions, combo)
        completeur.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        completeur.setFilterMode(QtCore.Qt.MatchContains)
        combo.setCompleter(completeur)
        combo.setCurrentIndex(0 if propositions else -1)
        combo.currentIndexChanged.connect(self._tracer)
        combo.lineEdit().editingFinished.connect(self._tracer)
        return combo

    def _saisies_memorisees(self) -> list[str]:
        if self.stockage is None:
            return []
        memorise = self.stockage.preference(CLE_SAISIES, "")
        return [nom for nom in memorise.split("\n") if nom]

    def _memoriser_saisie(self, nom: str):
        """Conserve un nom tapé à la main pour le reproposer plus tard."""
        if self.stockage is None or not nom or nom in self._voies_fichier:
            return
        connues = self._saisies_memorisees()
        if nom not in connues:
            self.stockage.definir_preference(CLE_SAISIES,
                                             "\n".join(connues + [nom])[-4000:])

    def _resume(self) -> str:
        """Une ligne : ce qu'il faut savoir de l'essai avant de lire le tracé."""
        ind = self.detail.indicateurs
        resume = ind.resume(self.analyse.source if self.analyse else "voie_opposee")
        parts = self.detail.repartition_phases()
        phases = ", ".join(f"{nom} {part:.0%}" for nom, part in parts.items() if part)
        # Le compte des arrêts exploitables explique un zéro manquant : un arrêt
        # rapport engagé, ou en pente sans frein serré, ne compte pas.
        arrets = self.detail.arrets_exploitables()
        zeros = sum(v is not None for v in (ind.zero_avant, ind.zero_apres))
        return (f"{horodatage(ind.date)}  ·  durée {ind.duree_s:.0f} s  ·  "
                f"couple max {theme.nombre(ind.couple_max, 0, 'N·m')}  ·  "
                f"biais {theme.nombre(resume.biais, 2, 'N·m', signe=True)}  ·  "
                f"{len(self.detail.fenetres)} fenêtres retenues "
                f"({self.detail.part_exploitable():.0%} de l'essai)\n"
                f"Phases : {phases}  ·  {arrets} arrêts exploitables pour le zéro, "
                f"{zeros} relevés obtenus")

    def _tracer(self):
        detail, c = self.detail, theme.couleurs(self._mode)
        t = detail.t
        onglet = ONGLETS[self.onglets.currentIndex()]
        couple = onglet == "Couple"
        self.series.setVisible(couple)
        self.ecart.setVisible(couple)
        self.commandes.setVisible(onglet == "Tracé libre")

        if couple:
            self._tracer_couple(t, c)
        elif onglet == "Résidu":
            # Une valeur par fenêtre, pas le résidu instantané : à 20 Hz le bruit
            # d'échantillon (± 20 N·m) noierait complètement une dérive de 6 N·m.
            self.graphique.reinitialiser(
                "Résidu par fenêtre — voie gauche − voie droite", "N·m",
                "Temps (s)", "t = {:.1f} s")
            centres = np.array([float(t[(f.start + f.stop) // 2])
                                for f in detail.fenetres])
            reference = reference_de_l_essai(detail, self.analyse)
            if reference is not None and centres.size:      # bande d'une fenêtre
                mu0, echelle = reference
                demi = 1.96 * echelle
                self.graphique.bande(centres, np.full(centres.size, mu0 - demi),
                                     np.full(centres.size, mu0 + demi),
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
        self._surligner()

    def _tracer_couple(self, t, c):
        """Les deux voies sur une même échelle, et leur écart juste en dessous."""
        gauche = self.detail.voies["couple_gauche"]
        droite = self.detail.voies["couple_droit"]
        # Pas de libellé d'abscisse ici : les deux tracés partagent l'axe du
        # temps, et celui du bas le nomme pour les deux.
        self.graphique.reinitialiser("Couple aux roues", "N·m", "",
                                     "t = {:.1f} s")
        self.graphique.legende()
        # Le couple estimé d'abord : les voies mesurées restent au premier plan.
        if self.cases["estime"].isChecked() and "couple_estime" in self.detail.voies:
            self.graphique.courbe(t, self.detail.voies["couple_estime"], c["serie3"],
                                  "Couple estimé", marqueurs=False, pointille=True)
        if self.cases["somme"].isChecked():
            # La somme est une grandeur dérivée, pas une voie : trait tireté et
            # couleur de texte, les trois couleurs de série restant réservées
            # aux voies elles-mêmes.
            self.graphique.courbe(t, gauche + droite, c["texte_secondaire"],
                                  "Somme gauche + droite", marqueurs=False,
                                  pointille=True)
        if self.cases["droite"].isChecked():
            self.graphique.courbe(t, droite, c["serie2"], "Voie droite",
                                  marqueurs=False)
        if self.cases["gauche"].isChecked():
            self.graphique.courbe(t, gauche, c["serie1"], "Voie gauche",
                                  marqueurs=False)
        # L'écart figure dans l'info-bulle des couples, en plus de son tracé.
        self.graphique.survol_seul("Écart G − D", t, gauche - droite)

        # L'écart brut à 20 Hz est dominé par le bruit d'échantillon (± 20 N·m) :
        # c'est la moyenne glissante qui rend lisible une dérive de quelques N·m.
        brut = gauche - droite
        largeur = max(2, int(self.detail.t.size and 2.0 /
                             max(np.mean(np.diff(t)), 1e-6)))
        lisse = np.convolve(brut, np.ones(largeur) / largeur, mode="same")
        self.ecart.reinitialiser(
            "Écart voie gauche − voie droite — moyenne glissante sur 2 s", "N·m",
            "Temps (s)", "t = {:.1f} s")
        # Le tracé brut est un fond de contexte, pas une série : sans nom, donc
        # sans légende, comme les lignes de contrôle des autres graphiques.
        self.ecart.courbe(t, brut, c["grille"], marqueurs=False, survol=False)
        self.ecart.courbe(t, lisse, c["serie1"], marqueurs=False)

    def _voie(self, nom: str):
        """Lit une voie à la demande et la garde en mémoire pour cette fenêtre."""
        if nom not in self._cache:
            self._cache[nom] = lire_voie(self.detail.indicateurs.chemin, nom,
                                         self.detail.t)
        return self._cache[nom]

    def _tracer_libre(self, t, c):
        """Trace n'importe quelle voie du fichier, seule ou combinée à une autre."""
        nom_a = self.voie_a.currentText().strip()
        nom_b = self.voie_b.currentText().strip()
        libelle = self.operation.currentText()
        seule = libelle == "Voie A seule"
        self.message_voie.setText("")
        for nom in (nom_a,) if seule else (nom_a, nom_b):
            self._memoriser_saisie(nom)
        if not nom_a:
            self.graphique.reinitialiser("Choisissez une voie", "", "Temps (s)",
                                         "t = {:.1f} s")
            return

        lu_a = self._voie(nom_a)
        lu_b = None if seule else self._voie(nom_b)
        attendus = [(nom_a, lu_a)] if seule else [(nom_a, lu_a), (nom_b, lu_b)]
        introuvables = [nom for nom, lu in attendus if lu is None]
        if introuvables:
            # On signale sans bloquer ni vider le champ : la saisie reste
            # valable pour un autre essai de la campagne.
            self.message_voie.setText(
                "Signal introuvable dans cet essai : " + ", ".join(introuvables))
            self.graphique.reinitialiser("", "", "Temps (s)", "t = {:.1f} s")
            return

        valeurs_a, unite = lu_a
        etiquette_a = self.etiquette_a.text().strip() or nom_a
        etiquette_b = self.etiquette_b.text().strip() or nom_b
        if seule:
            valeurs, titre = valeurs_a, etiquette_a
        else:
            calcul, gabarit = OPERATIONS[libelle]
            valeurs = calcul(valeurs_a, lu_b[0])
            titre = gabarit.format(a=etiquette_a, b=etiquette_b)
            if lu_b[1] and lu_b[1] != unite:   # unités hétérogènes : on le dit
                unite = f"{unite} / {lu_b[1]}"
        self.graphique.reinitialiser(titre, unite, "Temps (s)", "t = {:.1f} s")
        self.graphique.courbe(t, valeurs, c["serie1"], unite=unite, marqueurs=False)

    def _surligner(self):
        """Surligne les fenêtres retenues, en couleur de statut si elles dérivent."""
        plages = zones_par_statut(self.detail, self.analyse)
        compte = {"conforme": 0, "vigilance": 0, "non_conforme": 0}
        cibles = [self.graphique] + ([self.ecart] if self.ecart.isVisible() else [])
        for debut, fin, statut in plages:
            compte[statut] += 1
            # Les trois zones parlent la même langue que le verdict : vert,
            # orange, rouge. Le gris neutre d'origine se confondait avec la
            # grille du graphique et ne se voyait pas. Le vert est adouci
            # parce qu'il couvre l'essentiel d'un essai sain, là où l'orange
            # et le rouge ne marquent que des exceptions à repérer vite.
            couleur = theme.couleur_statut(statut)
            opacite = 38 if statut == "conforme" else 70
            for cible in cibles:
                cible.zone(debut, fin, couleur, opacite)
        if not plages:
            self.legende_zones.setText(
                "Aucune fenêtre exploitable : vérifiez le mappage des voies et les "
                "seuils de la section « traitement » de config.yaml.")
            return
        # Toujours un libellé texte : la couleur seule ne porte jamais le sens.
        self.legende_zones.setText(
            f"Fond vert : {compte['conforme']} plages retenues et conformes.  ·  "
            f"Fond orange : {compte['vigilance']} plages hors bande d'accord "
            "(±1,96 σ₀).  ·  "
            f"Fond rouge : {compte['non_conforme']} plages au-delà de l'écart "
            "maximal admissible.  ·  Molette pour zoomer, double-clic droit pour "
            "revenir à la vue d'ensemble.")

    def appliquer_theme(self, mode: str):
        self._mode = mode
        self.graphique.appliquer_theme(mode)
        self.ecart.appliquer_theme(mode)
        self._tracer()
