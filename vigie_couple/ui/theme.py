# -*- coding: utf-8 -*-
"""Palette, styles, mode clair/sombre et widget de graphique commun.

Les valeurs de couleur sont imposées par la spécification visuelle : elles sont
validées pour la vision des couleurs déficiente. Les couleurs de statut sont
réservées au verdict et ne servent jamais à une série de données.
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt5 import QtCore, QtGui, QtWidgets

MARGE = 16      # espace autour d'un bloc
ESPACE = 8      # espace entre éléments liés
POLICES = '"Segoe UI", "Inter", "DejaVu Sans", sans-serif'

PALETTES = {
    "clair": {
        "surface": "#fcfcfb",
        "texte": "#0b0b0b",
        "texte_secondaire": "#52514e",
        "serie1": "#2a78d6",
        "serie2": "#eb6834",
        "serie3": "#1baf7a",
        "grille": "#e2e2de",
        "alternance": "#f4f4f1",
    },
    "sombre": {
        "surface": "#1a1a19",
        "texte": "#ffffff",
        "texte_secondaire": "#c3c2b7",
        "serie1": "#3987e5",
        "serie2": "#d95926",
        "serie3": "#199e70",
        "grille": "#333331",
        "alternance": "#222220",
    },
}

# Statuts : identiques dans les deux modes, réservés au verdict.
STATUTS = {
    "conforme": "#0ca30c",
    "vigilance": "#fab219",
    "non_conforme": "#d03b3b",
    "indetermine": "#52514e",
}


def couleurs(mode: str) -> dict:
    return PALETTES.get(mode, PALETTES["clair"])


def couleur_statut(statut: str) -> str:
    return STATUTS.get(statut, STATUTS["indetermine"])


def nombre(valeur, decimales: int = 2, unite: str = "", signe: bool = False) -> str:
    """Formatage français : virgule décimale, unité séparée par une espace.

    Le signe n'est explicite que pour les grandeurs qui en portent un sens
    (un biais, un écart) : jamais pour un écart-type ou un couple maximal.
    """
    if valeur is None:
        return "—"
    texte = f"{valeur:+.{decimales}f}" if signe else f"{valeur:.{decimales}f}"
    texte = texte.replace(".", ",")
    return f"{texte} {unite}".strip()


def feuille_de_style(mode: str) -> str:
    """Feuille de style unique : aucune bordure, les zones sont séparées par du vide."""
    c = couleurs(mode)
    return f"""
    QWidget {{
        background: {c['surface']};
        color: {c['texte']};
        font-family: {POLICES};
        font-size: 12px;
    }}
    QLabel[role="titre"] {{ font-size: 13px; font-weight: 600; }}
    QLabel[role="secondaire"] {{ color: {c['texte_secondaire']}; }}
    QLabel[role="verdict"] {{ font-size: 26px; font-weight: 600; }}
    QLabel[role="valeur"] {{ font-size: 22px; font-weight: 600; }}
    QPushButton {{
        background: {c['alternance']};
        border: none; border-radius: 4px;
        padding: 7px 14px; color: {c['texte']};
    }}
    QPushButton:hover {{ background: {c['grille']}; }}
    QPushButton:disabled {{ color: {c['texte_secondaire']}; }}
    QTabBar::tab {{
        background: transparent; border: none;
        padding: 7px 14px; color: {c['texte_secondaire']};
    }}
    QTabBar::tab:selected {{
        color: {c['texte']};
        border-bottom: 2px solid {c['serie1']};
    }}
    QTabWidget::pane {{ border: none; }}
    QTableWidget {{
        background: {c['surface']}; border: none;
        alternate-background-color: {c['alternance']};
        gridline-color: transparent;
    }}
    QHeaderView::section {{
        background: {c['surface']}; border: none;
        color: {c['texte_secondaire']}; padding: 6px;
    }}
    QTableWidget::item {{ padding: 4px; }}
    QTableWidget::item:selected {{ background: {c['grille']}; color: {c['texte']}; }}
    QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QDateEdit {{
        background: {c['alternance']}; border: none;
        border-radius: 4px; padding: 5px; color: {c['texte']};
    }}
    QComboBox QAbstractItemView {{
        background: {c['alternance']}; border: none;
        selection-background-color: {c['grille']}; color: {c['texte']};
    }}
    QProgressBar {{
        background: {c['alternance']}; border: none;
        border-radius: 3px; height: 6px; text-align: center; color: transparent;
    }}
    QProgressBar::chunk {{ background: {c['serie1']}; border-radius: 3px; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; }}
    QScrollBar::handle:vertical {{ background: {c['grille']}; border-radius: 4px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    """


def pastille(statut: str, taille: int = 10) -> QtGui.QIcon:
    """Pastille de statut sous forme d'icône, pour une cellule de tableau.

    Une icône plutôt qu'un widget dans la cellule : un widget resterait enfant
    du viewport à chaque reconstruction du tableau, et finirait par s'empiler.
    Le libellé garde ainsi la couleur du texte, seule la pastille est colorée.
    """
    image = QtGui.QPixmap(taille, taille)
    image.fill(QtCore.Qt.transparent)
    peintre = QtGui.QPainter(image)
    peintre.setRenderHint(QtGui.QPainter.Antialiasing)
    peintre.setBrush(QtGui.QColor(couleur_statut(statut)))
    peintre.setPen(QtCore.Qt.NoPen)
    peintre.drawEllipse(0, 0, taille - 1, taille - 1)
    peintre.end()
    return QtGui.QIcon(image)


def etiquette(texte: str, role: str = "", parent=None) -> QtWidgets.QLabel:
    """Libellé porteur d'un rôle de style ; la couleur reste celle du texte."""
    label = QtWidgets.QLabel(texte, parent)
    if role:
        label.setProperty("role", role)
    return label


def marges(layout, marge: int = MARGE, espace: int = ESPACE):
    layout.setContentsMargins(marge, marge, marge, marge)
    layout.setSpacing(espace)
    return layout


class Graphique(pg.PlotWidget):
    """Graphique unique, épuré, avec curseur et info-bulle au survol.

    Règles appliquées : lignes de 2 px, marqueurs de 8 px, grille discrète,
    jamais de second axe des ordonnées, légende dès deux séries.
    """

    def __init__(self, mode: str = "clair", parent=None):
        super().__init__(parent)
        self._mode = mode
        self._series: list[tuple[str, object, object, str]] = []
        self._legende = None
        self.format_x = "Essai {:.0f}"
        self.setMenuEnabled(False)
        self.setMouseEnabled(x=False, y=False)
        self.showGrid(x=True, y=True, alpha=0.18)
        self._curseur = pg.InfiniteLine(angle=90, movable=False)
        self._bulle = pg.TextItem(anchor=(0, 1))
        self.addItem(self._curseur, ignoreBounds=True)
        self.addItem(self._bulle, ignoreBounds=True)
        self._curseur.hide()
        self._bulle.hide()
        self.scene().sigMouseMoved.connect(self._survol)
        self.appliquer_theme(mode)

    # --- thème ---
    def appliquer_theme(self, mode: str):
        self._mode = mode
        c = couleurs(mode)
        self.setBackground(c["surface"])
        stylo = pg.mkPen(c["grille"], width=1)
        for cote in ("left", "bottom"):
            axe = self.getAxis(cote)
            axe.setPen(stylo)
            axe.setTextPen(pg.mkPen(c["texte_secondaire"]))
        self.getPlotItem().titleLabel.setText(
            self.getPlotItem().titleLabel.text, color=c["texte"], size="13px")
        self._curseur.setPen(pg.mkPen(c["texte_secondaire"], width=1,
                                      style=QtCore.Qt.DashLine))
        self._bulle.setColor(QtGui.QColor(c["texte"]))
        self._bulle.fill = pg.mkBrush(c["alternance"])

    # --- tracé ---
    def reinitialiser(self, titre: str, y_libelle: str, x_libelle: str = "Essai",
                      format_x: str = "Essai {:.0f}"):
        self.clear()
        self._series.clear()
        self.format_x = format_x        # en-tête de l'info-bulle de survol
        # Sans cela, la bulle du tracé précédent reste affichée, avec ses
        # anciennes valeurs, par-dessus le nouveau graphique.
        self._curseur.hide()
        self._bulle.hide()
        if self._legende is not None:
            # clear() a pu détacher la légende de la scène : on ne la retire
            # que si elle s'y trouve encore.
            scene = self._legende.scene()
            if scene is not None:
                scene.removeItem(self._legende)
            self._legende = None
            # addLegend() rendrait la légende détachée au lieu d'en créer une.
            self.getPlotItem().legend = None
        c = couleurs(self._mode)
        self.setTitle(titre, color=c["texte"], size="13px")
        for cote, texte in (("left", y_libelle), ("bottom", x_libelle)):
            self.setLabel(cote, texte, color=c["texte_secondaire"], size="12px")
        self.addItem(self._curseur, ignoreBounds=True)
        self.addItem(self._bulle, ignoreBounds=True)

    def legende(self):
        """Légende ajoutée seulement quand il y a deux séries ou plus."""
        if self._legende is None:
            c = couleurs(self._mode)
            self._legende = self.addLegend(offset=(10, 10), labelTextColor=c["texte"])
        return self._legende

    def courbe(self, x, y, couleur: str, nom: str = "", unite: str = "N·m",
               marqueurs: bool = True, pointille: bool = False, survol: bool = True):
        style = QtCore.Qt.DashLine if pointille else QtCore.Qt.SolidLine
        stylo = pg.mkPen(couleur, width=2, style=style)
        courbe = self.plot(x, y, pen=stylo, name=nom or None,
                           symbol="o" if marqueurs else None,
                           symbolSize=8, symbolBrush=couleur, symbolPen=None)
        if survol:
            self._series.append((nom, x, y, unite))
        return courbe

    def survol_seul(self, nom: str, x, y, unite: str = "N·m"):
        """Ajoute une grandeur à l'info-bulle sans la tracer."""
        self._series.append((nom, x, y, unite))

    def bande(self, x, bas, haut, couleur: str):
        """Bande d'accord en fond : deux courbes discrètes et un remplissage."""
        stylo = pg.mkPen(QtGui.QColor(couleur), width=1, style=QtCore.Qt.DotLine)
        c1 = self.plot(x, bas, pen=stylo)
        c2 = self.plot(x, haut, pen=stylo)
        teinte = QtGui.QColor(couleur)
        teinte.setAlpha(30)
        self.addItem(pg.FillBetweenItem(c1, c2, brush=pg.mkBrush(teinte)))

    def repere(self, x: float, couleur: str, libelle: str = ""):
        """Repère vertical discret, avec un libellé facultatif à sa base."""
        stylo = pg.mkPen(couleur, width=1, style=QtCore.Qt.DashLine)
        trait = pg.InfiniteLine(pos=x, angle=90, movable=False, pen=stylo)
        if libelle:
            trait.label = pg.InfLineLabel(trait, libelle, position=0.06,
                                          color=couleur, movable=False)
        self.addItem(trait, ignoreBounds=True)

    def zone(self, x0: float, x1: float, couleur: str, opacite: int = 45):
        """Surligne une plage de l'axe des abscisses, en fond du tracé."""
        teinte = QtGui.QColor(couleur)
        teinte.setAlpha(opacite)
        region = pg.LinearRegionItem([x0, x1], movable=False,
                                     brush=pg.mkBrush(teinte))
        for trait in region.lines:      # pas de bord : seul le fond compte
            trait.setPen(pg.mkPen(None))
        region.setZValue(-10)
        self.addItem(region, ignoreBounds=True)

    # --- survol ---
    def _survol(self, position):
        if not self._series or not self.sceneBoundingRect().contains(position):
            self._curseur.hide()
            self._bulle.hide()
            return
        point = self.getPlotItem().vb.mapSceneToView(position)
        textes, x_cible, y_cible = [], None, None
        for nom, xs, ys, unite in self._series:
            if len(xs) == 0:
                continue
            # Recherche vectorisée : les tracés d'un essai font des milliers de points.
            indice = int(np.argmin(np.abs(np.asarray(xs, dtype=float) - point.x())))
            x_cible = xs[indice]
            y_cible = ys[indice] if y_cible is None else y_cible
            prefixe = f"{nom} : " if nom else ""
            textes.append(f"{prefixe}{nombre(ys[indice], 2, unite, True)}")
        if x_cible is None:
            return
        self._curseur.setPos(x_cible)
        self._curseur.show()
        self._bulle.setHtml("<div>{} — {}</div>".format(
            self.format_x.format(x_cible), " · ".join(textes)))
        self._bulle.setPos(x_cible, y_cible)
        self._bulle.show()


def preparer_pyqtgraph():
    """Réglages globaux de pyqtgraph, une seule fois au démarrage."""
    pg.setConfigOptions(antialias=True, useOpenGL=False)
