# -*- coding: utf-8 -*-
"""Point d'entrée de Vigie Couple.

Usage : python -m vigie_couple.main [--sombre] [chemin/config.yaml]
"""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt5 import QtCore, QtWidgets

from .coeur.lecture_mf4 import CHEMIN_CONFIG, charger_config
from .ui import theme
from .ui.fenetre import Fenetre


def main(arguments: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    mode = "sombre" if "--sombre" in arguments else "clair"
    chemins = [a for a in arguments if not a.startswith("--")]

    application = QtWidgets.QApplication(sys.argv)
    application.setApplicationName("Vigie Couple")
    # Locale française : virgule décimale dans les champs, dates en jj/mm/aaaa.
    QtCore.QLocale.setDefault(QtCore.QLocale(QtCore.QLocale.French,
                                             QtCore.QLocale.France))
    theme.preparer_pyqtgraph()
    chemin_config = Path(chemins[0]) if chemins else CHEMIN_CONFIG
    fenetre = Fenetre(charger_config(chemin_config), chemin_config, mode)
    fenetre.show()
    return application.exec_()


if __name__ == "__main__":
    sys.exit(main())
