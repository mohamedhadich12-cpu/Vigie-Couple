# -*- coding: utf-8 -*-
"""Génère la notice technique de Vigie Couple au format PDF.

Usage : python documentation/notice.py [sortie.pdf]

Le document décrit le principe, la logique de calcul et le rôle de chaque
commande de l'interface. Il est régénéré depuis ce script pour rester en phase
avec le code : les seuils cités proviennent de config.yaml, lu à l'exécution.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

RACINE = Path(__file__).resolve().parents[1]

# Palette de l'application, reprise telle quelle.
BLEU = colors.HexColor("#2a78d6")
TEXTE = colors.HexColor("#0b0b0b")
GRIS = colors.HexColor("#52514e")
FILET = colors.HexColor("#e2e2de")
FOND = colors.HexColor("#f4f4f1")

# Polices Unicode : indispensables pour μ, σ, λ, √, ≈ — absents des polices
# intégrées de reportlab. On essaie DejaVu (Linux) puis Arial (Windows).
CANDIDATS = (
    ("DejaVuSans", "DejaVuSans-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("DejaVuSans", "DejaVuSans-Bold", "C:/Windows/Fonts/DejaVuSans.ttf",
     "C:/Windows/Fonts/DejaVuSans-Bold.ttf"),
    ("Arial", "Arial-Bold", "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
)


def polices() -> tuple[str, str]:
    """Enregistre une police Unicode ; se rabat sur Helvetica si aucune n'existe."""
    for normale, grasse, chemin_n, chemin_g in CANDIDATS:
        if Path(chemin_n).exists() and Path(chemin_g).exists():
            pdfmetrics.registerFont(TTFont(normale, chemin_n))
            pdfmetrics.registerFont(TTFont(grasse, chemin_g))
            # Sans déclaration de famille, le balisage <b> des Paragraph est
            # ignoré silencieusement avec une police TrueType.
            pdfmetrics.registerFontFamily(normale, normal=normale, bold=grasse,
                                          italic=normale, boldItalic=grasse)
            return normale, grasse
    print("Police Unicode introuvable : repli sur Helvetica, "
          "les lettres grecques risquent de ne pas s'afficher.")
    return "Helvetica", "Helvetica-Bold"


NORMALE, GRASSE = polices()
STYLES = getSampleStyleSheet()


def style(nom, taille, gras=False, espace_avant=0, espace_apres=6,
          couleur=TEXTE, gauche=0, justifie=True, solidaire=False):
    """solidaire : le bloc reste collé au suivant, pour ne pas orpheliner un titre."""
    return ParagraphStyle(
        nom, parent=STYLES["Normal"], fontName=GRASSE if gras else NORMALE,
        fontSize=taille, leading=taille * 1.45, textColor=couleur,
        spaceBefore=espace_avant, spaceAfter=espace_apres, leftIndent=gauche,
        keepWithNext=solidaire,
        alignment=TA_JUSTIFY if justifie else 0)


S = {
    "titre": style("t", 24, True, 0, 4, justifie=False),
    "sous_titre": style("st", 12, False, 0, 30, GRIS, justifie=False),
    "h1": style("h1", 15, True, 18, 10, BLEU, justifie=False, solidaire=True),
    "h2": style("h2", 11.5, True, 12, 5, justifie=False, solidaire=True),
    "corps": style("c", 9.5),
    "puce": style("p", 9.5, gauche=12, espace_apres=3, justifie=False),
    "formule": style("f", 10, gauche=14, justifie=False),
    "legende": style("l", 8.5, couleur=GRIS),
    "cellule": style("ce", 8.5, justifie=False),
    "cellule_g": style("cg", 8.5, True, justifie=False),
}


def config() -> dict:
    with open(RACINE / "vigie_couple" / "config.yaml", encoding="utf-8") as flux:
        return yaml.safe_load(flux)


CFG = config()
TR, DE = CFG["traitement"], CFG["detection"]


def nb(valeur) -> str:
    """Nombre à la française : virgule décimale, entiers sans décimale inutile."""
    if isinstance(valeur, float) and valeur.is_integer():
        return str(int(valeur))
    return str(valeur).replace(".", ",")

recit = []


def h1(texte):
    recit.append(Paragraph(texte, S["h1"]))


def h2(texte):
    recit.append(Paragraph(texte, S["h2"]))


def p(texte, cle="corps"):
    recit.append(Paragraph(texte, S[cle]))


def puces(elements):
    for element in elements:
        recit.append(Paragraph(f"•&nbsp;&nbsp;{element}", S["puce"]))
    recit.append(Spacer(1, 4))


def formule(texte):
    """Formule encadrée d'un léger fond : elle se distingue sans trait."""
    tableau = Table([[Paragraph(texte, S["formule"])]], colWidths=[165 * mm])
    tableau.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), FOND),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    recit.append(tableau)
    recit.append(Spacer(1, 8))


def table(entetes, lignes, largeurs):
    """Tableau sobre : pas de quadrillage, un filet fin sous chaque ligne."""
    donnees = [[Paragraph(f"<b>{c}</b>", S["cellule_g"]) for c in entetes]]
    donnees += [[Paragraph(str(c), S["cellule"]) for c in ligne] for ligne in lignes]
    tableau = Table(donnees, colWidths=[l * mm for l in largeurs], repeatRows=1)
    tableau.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, GRIS),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, FILET),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    recit.append(tableau)
    recit.append(Spacer(1, 10))


def pied(canevas, document):
    """Numéro de page et rappel du titre, discrets, en bas de chaque page."""
    canevas.saveState()
    canevas.setFont(NORMALE, 8)
    canevas.setFillColor(GRIS)
    if document.page > 1:
        canevas.drawString(20 * mm, 12 * mm, "Vigie Couple — notice technique")
        canevas.drawRightString(190 * mm, 12 * mm, str(document.page))
    canevas.restoreState()


# ===========================================================================
# Page de garde
# ===========================================================================
p("Vigie Couple", "titre")
p("Notice technique — principe, logique de calcul et guide des commandes",
  "sous_titre")
p("Détection précoce de dérive des capteurs de couple embarqués sur véhicules "
  "d'essais : transmissions instrumentées, télémétrie Manner PCM16, étendue "
  "±1 500 N·m. Livrable logiciel d'un stage d'ingénieur chez FEV France "
  "(centre technique de Belchamp, pour le compte de Stellantis).")
recit.append(Spacer(1, 6))
table(["Section", "Contenu"], [
    ["1. Le principe", "La question posée, pourquoi un résidu, les trois sources de comparaison"],
    ["2. Traitement d'un essai", "De la lecture du fichier MF4 aux indicateurs de l'essai"],
    ["3. Surveillance", "Référence robuste, CUSUM, EWMA, verdict, discrimination"],
    ["4. Les écrans et leurs commandes", "Rôle exact de chaque bouton, champ et onglet"],
    ["5. Configuration", "Les clés de config.yaml et leur effet"],
    ["6. Limites connues", "Ce que l'outil ne sait pas faire, et pourquoi"],
], [42, 123])

# ===========================================================================
# 1. Le principe
# ===========================================================================
h1("1. Le principe")

h2("1.1 La question posée")
p("L'application répond à une seule question, essai après essai : "
  "<b>ce capteur de couple a-t-il commencé à dériver ?</b> Tout ce qui n'aide "
  "pas à y répondre est hors périmètre. Elle ne corrige pas la mesure, "
  "ne rejoue pas les essais et ne remplace pas un étalonnage : elle dit quand "
  "en programmer un.")

h2("1.2 Pourquoi un résidu")
p("Un capteur embarqué ne dispose d'aucun étalon de référence à bord. On ne "
  "peut donc pas mesurer son erreur directement. En revanche, on peut le "
  "comparer à une grandeur qui devrait lui être égale, et suivre l'écart — "
  "le <b>résidu</b> — au fil des essais. Un capteur sain donne un résidu "
  "stable autour d'une valeur fixe ; un capteur qui dérive fait lentement "
  "glisser cette valeur.")
p("Toute la difficulté est que la grandeur de comparaison est elle-même "
  "imparfaite. L'application en utilise trois, classées par fiabilité "
  "décroissante, et l'opérateur choisit laquelle sert de source.")

h2("1.3 Les trois sources de comparaison")
table(["Rang", "Source", "Calcul du résidu", "Ce qu'elle vaut"], [
    ["1", "Voie opposée (défaut)",
     "couple gauche − couple droit",
     "Ne dépend d'aucun modèle : c'est une mesure comparée à une autre mesure. "
     "Suppose un essieu symétrique, donc valable en ligne droite hors "
     "intervention du contrôle de motricité. La plus fiable."],
    ["2", "Zéro à couple nul",
     "écart gauche − droite relevé véhicule à l'arrêt, avant et après essai",
     "Contrôle direct du décalage de zéro, la dérive la plus fréquente sur "
     "un capteur à jauges. Ne dit rien sur la sensibilité."],
    ["3", "Couple estimé",
     "moyenne des deux voies − couple estimé par le calculateur",
     "Dernier recours : le modèle d'estimation a sa propre erreur, souvent "
     "supérieure à la dérive cherchée. Sert surtout à désigner laquelle des "
     "deux voies dérive, une fois l'écart gauche/droite établi."],
], [12, 30, 45, 78])

# ===========================================================================
# 2. Traitement d'un essai
# ===========================================================================
h1("2. Le traitement d'un essai")
p("Cette chaîne s'exécute pour chaque fichier MF4 chargé, dans un fil "
  "d'exécution séparé afin que l'interface ne se fige jamais. Elle est "
  "entièrement contenue dans <font face='%s'>coeur/lecture_mf4.py</font>."
  % NORMALE)

h2("2.1 Lecture et rééchantillonnage")
p("Les voies utiles sont lues via <b>asammdf</b> d'après le mappage de "
  "config.yaml — aucun nom de signal n'est écrit en dur dans le code. Chaque "
  "voie d'une acquisition a sa propre cadence (la télémétrie de couple est "
  "typiquement plus rapide que les voies calculateur) ; elles sont donc "
  "ramenées par interpolation linéaire sur une <b>base de temps commune à "
  "%s Hz</b>, restreinte à l'intervalle où toutes les voies existent." % nb(TR["frequence_hz"]))
p("Si les voies de couple gauche et droite sont absentes, l'essai est rejeté "
  "avec un message : sans elles, aucun résidu n'est calculable. Les autres "
  "voies sont facultatives et leur absence désactive simplement les tests qui "
  "en dépendent.", "legende")

h2("2.2 Segmentation en phases")
p("Chaque échantillon reçoit une phase, déduite de la vitesse, de la pédale "
  "et du couple. L'ordre d'application compte : une règle écrase la précédente.")
table(["Phase", "Règle appliquée"], [
    ["traction", "état par défaut de tout échantillon"],
    ["freinage récupératif", "couple moyen des deux roues inférieur à −20 N·m"],
    ["transitoire", "accélération longitudinale supérieure à %s m/s² en valeur "
     "absolue" % nb(TR["acceleration_max_ms2"])],
    ["arrêt", "vitesse inférieure à 1 km/h"],
    ["transitoire", "vitesse inférieure à 1 km/h avec pédale au-delà de 5 % "
     "(départ imminent)"],
], [38, 127])

h2("2.3 Sélection des fenêtres exploitables")
p("Un échantillon n'est retenu que s'il satisfait <b>toutes</b> les conditions "
  "suivantes. Les deux dernières ne s'appliquent que si la voie concernée est "
  "mappée.")
table(["Condition", "Seuil", "Raison"], [
    ["Hors transitoire", "accélération ≤ %s m/s²" % nb(TR["acceleration_max_ms2"]),
     "<b>Point essentiel.</b> Un défaut de synchronisation entre les deux voies "
     "produit en transitoire un élargissement de la dispersion du résidu, qu'on "
     "confondrait avec du bruit de mesure — et donc avec une dégradation du capteur."],
    ["Hors arrêt", "vitesse ≥ 1 km/h", "Le zéro est traité séparément (§ 2.5)."],
    ["Vitesse suffisante", "≥ %s km/h" % nb(TR["vitesse_min_kmh"]),
     "En deçà, le couple est trop faible pour que la comparaison soit informative."],
    ["Couple suffisant", "≥ %s N·m" % nb(TR["couple_min_nm"]),
     "Un résidu relevé à couple quasi nul ne renseigne que sur le zéro."],
    ["Hors intervention motricité", "écart mesure/demande ≤ %s N·m"
     % nb(TR["ecart_demande_max_nm"]),
     "Un contrôle de motricité qui coupe le couple d'une roue rompt la symétrie "
     "de l'essieu : la comparaison gauche/droite perdrait son sens."],
    ["Ligne droite", "vitesse de lacet ≤ %s °/s" % nb(TR["lacet_max_degs"]),
     "En virage, le différentiel répartit le couple inégalement. Si la voie de "
     "lacet n'est pas mappée, ce critère est sauté et l'on s'appuie sur les "
     "précédents."],
], [36, 34, 95])

h2("2.4 Du résidu instantané aux indicateurs de l'essai")
p("Les zones retenues sont découpées en <b>fenêtres de longueur fixe "
  "(%s s, soit %d échantillons)</b>, et chaque fenêtre donne <b>une</b> valeur "
  "de résidu : la moyenne du résidu instantané sur la fenêtre. Le reliquat de "
  "fin de zone, trop court pour une fenêtre entière, est écarté."
  % (nb(TR["duree_fenetre_s"]), int(TR["duree_fenetre_s"] * TR["frequence_hz"])))
p("Ce moyennage n'est pas cosmétique. À %s Hz, le bruit d'échantillon d'un "
  "capteur de cette étendue atteint ±20 N·m crête, alors que la dérive "
  "recherchée est de quelques N·m : le résidu instantané est inexploitable tel "
  "quel. Moyenner sur %s s divise l'écart-type du bruit par environ %.0f et "
  "rend la dérive visible. Chaque fenêtre pèse ensuite le même poids dans les "
  "indicateurs, quelle que soit la longueur de la zone dont elle provient."
  % (nb(TR["frequence_hz"]), nb(TR["duree_fenetre_s"]),
     (TR["duree_fenetre_s"] * TR["frequence_hz"]) ** 0.5))
p("Les indicateurs de l'essai sont alors calculés sur cette série de valeurs "
  "de fenêtres — et non sur les échantillons bruts :")
table(["Indicateur", "Calcul", "Usage"], [
    ["Biais", "moyenne des résidus de fenêtre",
     "C'est <b>la</b> valeur suivie par les cartes de contrôle : un point par essai."],
    ["Écart-type", "écart-type des résidus de fenêtre",
     "Dispersion interne à l'essai. Sert d'échelle au surlignage (§ 3.6) et "
     "signale, s'il augmente, une dégradation de la répétabilité."],
    ["Écart maximal", "plus grand résidu de fenêtre en valeur absolue",
     "Comparé à l'écart maximal admissible pour le verdict « non conforme »."],
    ["Nombre de fenêtres", "cardinal de la série",
     "Indice de confiance : un essai à trois fenêtres ne vaut pas un essai à cent."],
], [32, 48, 85])

h2("2.5 Relevés de zéro")
p("Le zéro est relevé sur la <b>première</b> et la <b>dernière</b> plage "
  "d'arrêt de l'essai, en écartant 10 % de leur durée à chaque extrémité pour "
  "ne pas capter l'entrée et la sortie d'immobilisation. La valeur retenue est "
  "la moyenne de l'écart gauche − droite sur cette plage. Une plage d'arrêt de "
  "moins de 20 échantillons est jugée trop courte et ne produit pas de relevé.")
p("Ces deux valeurs alimentent la source de résidu « zéro », le test de dérive "
  "de zéro de la discrimination, et sont archivées automatiquement dans la "
  "fiche de vie du capteur.")

h2("2.6 Grandeurs annexes")
table(["Grandeur", "Calcul", "À quoi elle sert"], [
    ["Pente couple", "régression linéaire (scipy) du résidu de fenêtre sur le "
     "niveau de couple de la fenêtre ; None si l'étendue de couple entre "
     "fenêtres est inférieure à 100 N·m",
     "Distingue une dérive de <b>sensibilité</b> (erreur proportionnelle au "
     "couple) d'une dérive de <b>zéro</b> (erreur constante). Rendre None plutôt "
     "qu'une pente ajustée sur du bruit évite une conclusion fabriquée."],
    ["Écarts à l'estimé", "médiane, par voie, de l'écart au couple estimé",
     "Désigne laquelle des deux voies dérive quand l'écart gauche/droite est établi."],
    ["Température", "moyenne de la voie température sur l'essai",
     "Alimente le test de corrélation thermique."],
    ["Distance", "intégration de la vitesse sur la durée de l'essai",
     "Kilométrage d'essai cumulé de la fiche de vie."],
    ["Couple maximal", "plus grande valeur absolue du couple moyen des deux roues",
     "Affiché au tableau ; sert au comptage des essais à forte sollicitation."],
], [30, 62, 73])


# ===========================================================================
# 3. Surveillance
# ===========================================================================
h1("3. La surveillance essai après essai")
p("À partir d'ici, chaque essai est réduit à un seul nombre : son biais. La "
  "série de ces nombres, dans l'ordre chronologique, est la matière de la "
  "surveillance. Tout ce chapitre est implémenté dans "
  "<font face='%s'>coeur/detection.py</font>, qui n'importe rien de Qt et se "
  "teste donc seul." % NORMALE)

h2("3.1 La référence robuste")
p("Les seuils d'alarme se calculent à partir d'une référence : la position "
  "μ<sub>0</sub> et la dispersion σ<sub>0</sub> du résidu quand le capteur est "
  "sain. Elles sont estimées sur les <b>%s premiers essais</b> de la campagne, "
  "supposés sans défaut." % nb(DE["n_reference"]))
formule("μ<sub>0</sub> = médiane(x<sub>1</sub> … x<sub>N</sub>)"
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
        "σ<sub>0</sub> = 1,4826 × médiane( | x<sub>i</sub> − μ<sub>0</sub> | )")
p("Médiane et écart absolu médian (MAD), et non moyenne et écart-type : ce "
  "choix est <b>déterminant</b>. Un seul essai aberrant dans la période de "
  "référence — un montage mal serré, une jauge décollée le temps d'un essai — "
  "tirerait une moyenne et gonflerait un écart-type classique. Tous les seuils "
  "en découleraient faussés, et la carte deviendrait aveugle à la dérive "
  "qu'elle est censée détecter. La médiane ignore une valeur extrême, et le "
  "facteur 1,4826 ramène le MAD à l'échelle d'un écart-type gaussien.")
p("Vérification sur le jeu de démonstration, qui contient un essai aberrant à "
  "9 σ : en portant la période de référence de 10 à 20 essais — donc en y "
  "incluant l'aberrant —, μ<sub>0</sub> ne bouge que de −0,16 à −0,08 N·m. "
  "Un estimateur classique aurait été déplacé d'un ordre de grandeur.", "legende")

h2("3.2 Carte CUSUM")
p("La somme cumulée détecte un décalage <b>persistant</b> de faible amplitude, "
  "que l'observation essai par essai ne verrait pas. Elle accumule les écarts "
  "à la référence au-delà d'une zone morte K, séparément vers le haut et vers "
  "le bas.")
formule("C<super>+</super><sub>i</sub> = max( 0 ; x<sub>i</sub> − (μ<sub>0</sub> + K) + C<super>+</super><sub>i−1</sub> )<br/>"
        "C<super>−</super><sub>i</sub> = max( 0 ; (μ<sub>0</sub> − K) − x<sub>i</sub> + C<super>−</super><sub>i−1</sub> )<br/><br/>"
        "avec K = k·σ<sub>0</sub> et alarme dès que C<super>+</super><sub>i</sub> &gt; H ou C<super>−</super><sub>i</sub> &gt; H, où H = h·σ<sub>0</sub>")
p("Réglage par défaut : k = %s et h = %s. La zone morte k = 0,5 signifie que "
  "l'on ne cumule que ce qui dépasse un demi-écart-type : le bruit ordinaire "
  "ne fait pas monter la somme, seule une dérive systématique l'alimente. "
  "Ce couple de valeurs est le réglage classique de la littérature, calibré "
  "pour détecter un décalage de 1 σ."
  % (nb(DE["k"]), nb(DE["h"])))

h2("3.3 Carte EWMA")
p("La moyenne mobile à pondération exponentielle lisse la série en donnant un "
  "poids décroissant aux essais anciens. Elle réagit à une dérive progressive "
  "là où la CUSUM réagit à un décalage franc ; les deux tournent en parallèle "
  "et une alarme de l'une suffit.")
formule("z<sub>i</sub> = λ·x<sub>i</sub> + (1 − λ)·z<sub>i−1</sub>&nbsp;&nbsp;&nbsp;&nbsp;avec z<sub>0</sub> = μ<sub>0</sub><br/><br/>"
        "limites = μ<sub>0</sub> ± L·σ<sub>0</sub>·√[ (λ / (2 − λ)) · (1 − (1 − λ)<super>2i</super>) ]")
p("Réglage par défaut : λ = %s et L = %s. Le terme <b>(1 − (1 − λ)<super>2i</super>)</b> "
  "est indispensable et souvent omis. Sans lui, les limites valent d'emblée "
  "leur valeur asymptotique, très large, alors que la statistique z part de "
  "μ<sub>0</sub> et n'a pas encore accumulé de variance. Les premiers essais "
  "seraient alors couverts par une bande démesurée et une dérive présente dès "
  "le départ passerait inaperçue — précisément là où la détection précoce "
  "compte le plus. Avec le terme transitoire, la limite s'ouvre "
  "progressivement : à i = 1 elle vaut L·σ<sub>0</sub>·λ, soit %s σ<sub>0</sub>, "
  "contre %s σ<sub>0</sub> à l'asymptote."
  % (nb(DE["lambda"]), nb(DE["L"]),
        nb("%.2f" % (DE["L"] * DE["lambda"])),
        nb("%.2f" % (DE["L"] * (DE["lambda"] / (2 - DE["lambda"])) ** 0.5))))

h2("3.4 Performances mesurées")
p("Les tests automatiques mesurent le comportement réel des deux cartes sur "
  "des séries simulées, μ<sub>0</sub> et σ<sub>0</sub> connus. La longueur "
  "moyenne de série (ARL) est le nombre moyen d'essais avant alarme.")
table(["Carte", "ARL sans défaut", "Détection d'un décalage de 1 σ", "Lecture"], [
    ["CUSUM (k=0,5 ; h=5)", "≈ 450 essais", "moins de 15 essais en moyenne",
     "Une fausse alarme tous les 450 essais environ : sur une campagne de 30, "
     "le risque reste faible."],
    ["EWMA (λ=0,10 ; L=2,7)", "≈ 315 essais", "moins de 15 essais en moyenne",
     "Légèrement plus sensible, donc un peu plus bavarde. Complémentaire."],
], [38, 30, 42, 55])

h2("3.5 Le verdict")
p("Le verdict est évalué dans cet ordre, et le premier cas rencontré l'emporte.")
table(["Verdict", "Condition", "Phrase affichée"], [
    ["<b>En attente</b> (gris)", "moins de trois essais chargés",
     "« Chargez au moins trois essais pour établir la référence. »"],
    ["<b>Non conforme</b> (rouge)",
     "un essai dont l'écart maximal dépasse %s N·m, ou dont le zéro après essai "
     "dépasse %s N·m en valeur absolue" % (nb(DE["ecart_max_admissible_nm"]),
                                           nb(DE["zero_majeur_nm"])),
     "« Mesure non exploitable. Revalider les essais depuis le « date ». »"],
    ["<b>Vigilance</b> (orange)", "une des deux cartes a franchi son seuil",
     "« Dérive naissante détectée à l'essai du « date ». Étalonnage de "
     "vérification à programmer. »"],
    ["<b>Conforme</b> (vert)", "aucun des cas précédents",
     "« Aucune dérive détectée sur les N derniers essais. »"],
], [36, 62, 67])
p("La date citée est celle du <b>premier</b> essai en cause, pas du dernier : "
  "c'est à partir de là que les mesures sont à revalider. Le verdict est "
  "toujours accompagné d'une icône et d'un libellé écrit — jamais de la "
  "couleur seule, qui serait illisible pour une vision des couleurs "
  "déficiente.", "legende")

h2("3.6 La discrimination")
p("Dire « ça dérive » ne suffit pas à décider quoi faire. Quand une carte "
  "alarme, l'application exécute une séquence de tests <b>ordonnée du plus "
  "indépendant du modèle au plus dépendant</b>, et affiche la première "
  "conclusion atteinte, en une phrase sous le verdict. Les tests portent sur "
  "les essais depuis l'alarme, comparés à la période de référence.")
table(["#", "Test", "Seuil", "Conclusion"], [
    ["1", "Écart gauche/droite présent ?",
     "médiane des résidus récents à plus de 2 σ<sub>0</sub> de μ<sub>0</sub>",
     "Dérive d'une des deux voies. Celle qui s'écarte le plus du couple estimé "
     "est désignée ; à défaut, le signe du résidu tranche."],
    ["2", "Le zéro a-t-il bougé ?",
     "déplacement du zéro supérieur à %s N·m" % nb(DE["zero_vigilance_nm"]),
     "Dérive de zéro confirmée."],
    ["3", "L'écart suit-il la température ?",
     "corrélation de Pearson supérieure à 0,70 en valeur absolue, sur au moins "
     "six essais renseignés",
     "Dérive thermique : le capteur réagit à son environnement, pas au couple."],
    ["4", "L'écart suit-il le niveau de couple ?",
     "pente supérieure à 0,5 %, ou corrélation avec le couple maximal "
     "supérieure à 0,70",
     "Dérive de sensibilité plutôt que de zéro : le gain du capteur a changé."],
    ["5", "Aucun des précédents", "—",
     "Écart non expliqué : programmer un étalonnage de vérification."],
], [8, 44, 52, 61])
p("L'ordre n'est pas arbitraire. Le test 1 ne suppose aucun modèle : il compare "
  "deux mesures. Le test 2 s'appuie sur un relevé direct. Les tests 3 et 4 "
  "supposent une relation de cause à effet, et le test 4 s'appuie en partie sur "
  "le couple estimé, la source la moins fiable. Conclure au plus tôt, c'est "
  "conclure sur l'hypothèse la plus solide.", "legende")

h2("3.7 Statut d'une fenêtre et surlignage")
p("La visualisation d'un essai surligne les zones où le résidu s'écarte. Le "
  "critère ne peut pas être celui des cartes de contrôle, et c'est un point "
  "subtil : σ<sub>0</sub> mesure la dispersion du biais <b>d'un essai à "
  "l'autre</b>, alors qu'une fenêtre isolée porte en plus la dispersion "
  "<b>interne</b> à l'essai. Les deux variances s'additionnent.")
formule("échelle d'une fenêtre = √( σ<sub>0</sub>² + σ<sub>fenêtre</sub>² )"
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
        "où σ<sub>fenêtre</sub> = médiane des écarts-types des essais de référence")
p("Sur le jeu de démonstration, σ<sub>0</sub> = 0,82 N·m et "
  "σ<sub>fenêtre</sub> = 0,93 N·m : l'échelle correcte vaut 1,23 N·m, soit une "
  "bande à ±2,42 N·m au lieu de ±1,60. Avec le mauvais critère, un essai "
  "parfaitement sain voyait la moitié de ses fenêtres signalées en dérive ; "
  "avec le bon, il en reste 2 à 5 %, ce qu'une bande à 1,96 σ doit "
  "statistiquement produire.")
table(["Fond de la zone", "Condition", "Signification"], [
    ["Gris", "résidu dans la bande",
     "Fenêtre retenue pour le calcul, conforme à la référence de campagne."],
    ["Orange", "hors bande à 1,96 × échelle de fenêtre",
     "La fenêtre s'écarte de la référence. Quelques-unes sur un essai sain sont "
     "normales ; une majorité signe une dérive."],
    ["Rouge", "au-delà de l'écart maximal admissible (%s N·m)"
     % nb(DE["ecart_max_admissible_nm"]),
     "Mesure inexploitable sur cette portion d'essai."],
    ["Aucun fond", "hors fenêtre retenue",
     "Portion écartée par la sélection : transitoire, arrêt, vitesse ou couple "
     "insuffisant, virage, intervention motricité."],
], [30, 55, 80])


# ===========================================================================
# 4. Les écrans et leurs commandes
# ===========================================================================
h1("4. Les écrans et leurs commandes")
p("L'application tient en trois écrans, plus deux fenêtres qui s'ouvrent à la "
  "demande. Cette section décrit le rôle exact de chaque commande.")

h2("4.1 Fenêtre principale")
table(["Commande", "Effet", "À savoir"], [
    ["Onglets <b>Campagne</b> / <b>Surveillance</b> / <b>Fiche de vie</b>",
     "Navigation entre les trois écrans.",
     "L'application démarre sur Campagne et bascule automatiquement sur "
     "Surveillance dès qu'une campagne finit de charger."],
    ["<b>Mode sombre</b> / <b>Mode clair</b>",
     "Bascule l'ensemble de l'interface, graphiques compris.",
     "Le mode sombre n'est pas une inversion automatique : c'est une seconde "
     "palette, définie couleur par couleur pour rester lisible."],
], [42, 55, 68])

h2("4.2 Écran 1 — Campagne")
p("Rôle : charger des acquisitions et calculer les indicateurs de chaque essai. "
  "Les boutons sont dans l'ordre où l'on s'en sert.")
table(["Commande", "Effet", "À savoir"], [
    ["<b>Configurer les voies…</b>",
     "Ouvre la fenêtre de mappage (§ 4.3).",
     "<b>Premier réflexe</b> devant des acquisitions réelles. Sans mappage "
     "correct, les essais sont rejetés et rien ne se calcule."],
    ["<b>Ajouter des fichiers…</b>",
     "Sélection multiple de fichiers .mf4.",
     "Le dossier de la dernière sélection est mémorisé pour la fois suivante."],
    ["<b>Ajouter un dossier…</b>",
     "Charge tous les .mf4 d'un dossier, triés par nom.",
     "Le tri par nom suppose une convention de nommage chronologique. À défaut, "
     "l'ordre chronologique réel vient de l'horodatage interne des fichiers, "
     "affiché en première colonne."],
    ["<b>Jeu de démonstration</b>",
     "Charge les 30 essais synthétiques.",
     "Absent tant que <font face='%s'>donnees_demo/generateur.py</font> n'a pas "
     "été lancé une fois ; le bouton le signale alors." % NORMALE],
    ["<b>Visualiser l'essai…</b>",
     "Ouvre la fenêtre de visualisation de l'essai sélectionné (§ 4.4).",
     "Inactif tant qu'aucune ligne n'est sélectionnée. Un <b>double-clic</b> sur "
     "une ligne fait la même chose."],
    ["Barre de progression et ligne d'état",
     "Avancement de la lecture, fichier par fichier.",
     "La lecture tourne dans un fil séparé : l'interface reste réactive. C'est "
     "aussi là que s'affichent les essais rejetés et la raison du rejet."],
], [36, 52, 77])
p("<b>Le tableau</b> donne une ligne par essai : date et heure d'acquisition, "
  "nom du fichier, durée, couple maximal atteint, biais et écart-type du "
  "résidu, et un verdict par essai (pastille colorée doublée du mot). Le "
  "verdict d'une ligne suit les mêmes règles que le verdict global, appliquées "
  "à cet essai seul.")

h2("4.3 Fenêtre de mappage des voies")
p("Associe chaque grandeur nécessaire au calcul au nom réel du signal dans vos "
  "acquisitions, sans éditer le fichier YAML à la main.")
table(["Commande", "Effet", "À savoir"], [
    ["<b>Choisir un fichier d'exemple (.mf4)…</b>",
     "Lit la liste des voies du fichier et en remplit les listes déroulantes.",
     "Facultatif : sans fichier d'exemple, les champs restent en saisie libre. "
     "Le fichier n'est pas chargé comme essai, il sert seulement de catalogue."],
    ["Les huit listes déroulantes",
     "Une par grandeur attendue. Éditables : on peut taper un nom absent de la liste.",
     "<b>Couple gauche et couple droit sont obligatoires.</b> Les six autres "
     "sont facultatives ; laissées vides, elles désactivent les traitements qui "
     "en dépendent, sans bloquer le calcul du résidu."],
    ["<b>Enregistrer</b>",
     "Vérifie les deux voies obligatoires puis réécrit config.yaml.",
     "Seules les lignes de voies sont modifiées : commentaires, seuils de "
     "traitement et réglages de détection sont préservés. Effet immédiat, sans "
     "redémarrage."],
    ["<b>Continuer sans modifier</b>", "Ferme sans rien écrire.",
     "C'est l'action par défaut : une validation au clavier ne modifie rien."],
], [40, 55, 70])

h2("4.4 Fenêtre de visualisation d'un essai")
p("Outil d'inspection et de diagnostic. L'en-tête rappelle date, durée, couple "
  "maximal, biais, <b>nombre de fenêtres retenues et part exploitable de "
  "l'essai</b>, ainsi que la répartition des phases. C'est le premier endroit "
  "où regarder quand un essai ne produit aucun indicateur.")
table(["Commande", "Effet", "À savoir"], [
    ["Onglet <b>Couple</b>",
     "Voie gauche, voie droite et couple estimé en pointillés.",
     "Les trois courbes sont à quelques N·m les unes des autres sur une étendue "
     "de 1 500 : il faut zoomer pour les séparer. Les voies mesurées sont "
     "dessinées par-dessus l'estimé."],
    ["Onglet <b>Résidu</b>",
     "Résidu par fenêtre, avec la bande d'accord en fond.",
     "Une valeur par fenêtre, pas le résidu instantané (voir § 2.4). C'est "
     "l'onglet où une dérive de sensibilité se lit directement : le résidu suit "
     "le niveau de couple."],
    ["Onglet <b>Vitesse</b>", "Profil de vitesse de l'essai.",
     "Permet de rapprocher les zones retenues du déroulé du roulage."],
    ["Onglet <b>Tracé libre</b>",
     "Trace n'importe quelle voie du fichier, mappée ou non.",
     "Voir la ligne suivante pour les trois listes."],
    ["<b>Voie A</b>, <b>Opération</b>, <b>Voie B</b>",
     "Choix des voies et de l'opération : voie seule, A + B, A − B, ou moyenne "
     "des deux.",
     "Utile pour reconstituer le couple d'essieu, contrôler une voie absente du "
     "mappage ou comparer deux grandeurs. Les voies sont lues à la demande et "
     "mises en cache ; une voie non numérique est signalée à l'écran."],
    ["<b>Vue d'ensemble</b>", "Annule le zoom et réajuste les échelles.",
     "La molette zoome, le glissé déplace. Le surlignage suit le zoom."],
], [34, 55, 76])

h2("4.5 Écran 2 — Surveillance")
p("L'écran principal, conçu pour tenir en un coup d'œil : un verdict en haut, "
  "un seul graphique au milieu, trois chiffres en bas.")
table(["Élément", "Contenu", "À savoir"], [
    ["Bandeau de verdict",
     "Pastille, icône, mot, phrase d'explication, et sous elle la conclusion de "
     "la discrimination.",
     "C'est la seule chose à regarder pour répondre à la question posée. Tout "
     "le reste sert à comprendre <b>pourquoi</b>."],
    ["Onglet <b>Résidu</b>",
     "Le biais essai par essai, avec la bande d'accord (±1,96 σ<sub>0</sub>) en fond.",
     "Un repère vertical marque l'essai qui a déclenché le verdict."],
    ["Onglet <b>CUSUM</b>", "Les statistiques C⁺ et C⁻ et la ligne de décision H.",
     "Après une alarme la somme continue de croître : c'est normal, la carte "
     "n'est pas remise à zéro automatiquement."],
    ["Onglet <b>EWMA</b>", "La statistique lissée et ses limites de contrôle.",
     "L'évasement des limites en début de série est le terme transitoire (§ 3.3)."],
    ["Tuile <b>Biais courant</b>", "Biais du dernier essai chargé.",
     "Même valeur que la dernière ligne du tableau de campagne."],
    ["Tuile <b>Essais depuis le dernier contrôle conforme</b>",
     "Nombre d'essais depuis le dernier essai sans alarme sur les deux cartes.",
     "Mesure l'ancienneté du problème : plus il monte, plus la revalidation "
     "sera lourde."],
    ["Tuile <b>Jours avant échéance d'étalonnage</b>",
     "Décompte à partir du dernier étalonnage enregistré.",
     "Affiche « — » tant qu'aucun étalonnage n'est saisi dans la fiche de vie."],
], [40, 55, 70])
p("<b>Le panneau latéral « Réglages »</b> est replié par défaut ; il ne doit "
  "pas encombrer la lecture du verdict. Ouvert, il expose les paramètres "
  "ci-dessous, et <b>toute modification recalcule immédiatement</b> l'ensemble "
  "de l'analyse.")
table(["Réglage", "Effet", "Défaut"], [
    ["<b>Source du résidu</b>", "Bascule entre voie opposée, zéro et couple "
     "estimé (§ 1.3).", "voie opposée"],
    ["<b>Essais de référence</b>", "Nombre d'essais servant à estimer "
     "μ<sub>0</sub> et σ<sub>0</sub>.", nb(DE["n_reference"])],
    ["<b>λ (EWMA)</b>", "Poids de l'essai courant. Plus petit = plus lissé, "
     "plus lent.", nb(DE["lambda"])],
    ["<b>L (EWMA)</b>", "Largeur des limites de contrôle en écarts-types.",
     nb(DE["L"])],
    ["<b>k (CUSUM)</b>", "Zone morte, en écarts-types.", nb(DE["k"])],
    ["<b>h (CUSUM)</b>", "Seuil de décision, en écarts-types.", nb(DE["h"])],
    ["<b>Écart maximal admissible</b>",
     "Au-delà, la mesure est déclarée non exploitable.",
     "%s N·m" % nb(DE["ecart_max_admissible_nm"])],
], [42, 90, 33])

h2("4.6 Écran 3 — Fiche de vie")
p("Historique persistant par capteur, stocké dans un unique fichier SQLite "
  "créé au premier lancement. Les relevés de zéro y sont versés "
  "automatiquement à chaque campagne chargée.")
table(["Commande", "Effet", "À savoir"], [
    ["Les quatre champs d'identification",
     "Référence, numéro de série, arbre, véhicule.",
     "Enregistrés dès que le champ perd le focus. Le numéro de série "
     "identifie le capteur : en changer bascule sur une autre fiche."],
    ["Ligne d'échéance",
     "État de l'étalonnage : valide, échéance proche, ou dépassée.",
     "Alerte au-delà de <b>370 jours</b> depuis le dernier étalonnage, plafond "
     "imposé par le règlement technique mondial ONU n° 21 pour la mesure de "
     "couple aux essieux. Avertissement également à 30 jours de l'échéance."],
    ["Les trois tuiles d'usage",
     "Kilométrage d'essai cumulé, nombre d'essais, nombre d'essais à forte "
     "sollicitation.",
     "Un essai compte comme sévère au-delà de %s N·m de couple maximal."
     % nb(CFG["capteur"]["couple_forte_sollicitation_nm"])],
    ["<b>Ajouter un étalonnage…</b>",
     "Saisie d'une date, d'une incertitude élargie et d'une référence de "
     "certificat.",
     "C'est ce qui alimente le décompte d'échéance, ici et sur l'écran "
     "Surveillance."],
    ["<b>Ajouter un contrôle de shunt…</b>",
     "Saisie d'un contrôle par résistance de shunt.",
     "Vérification intermédiaire de la chaîne de mesure, entre deux étalonnages."],
    ["<b>Exporter la fiche PDF</b>",
     "Produit une fiche de synthèse d'une page.",
     "Contient le verdict courant, le graphique du résidu et le tableau des "
     "derniers relevés. Rien de plus : c'est une pièce à joindre à un dossier "
     "d'essai, pas un rapport."],
], [40, 55, 70])


# ===========================================================================
# 5. Configuration — 6. Limites — Annexe
# ===========================================================================
h1("5. Configuration")
p("Tout est dans <font face='%s'>vigie_couple/config.yaml</font>. Les seuils "
  "de traitement méritent d'être revus au moins une fois face à un profil "
  "d'essai réel : ceux livrés conviennent à un roulage sur piste avec paliers "
  "de vitesse et côtes, pas nécessairement au vôtre." % NORMALE)
table(["Clé", "Rôle", "Défaut"], [
    ["<b>signaux</b> (8 clés)", "Mappage des voies. Réglable par la fenêtre "
     "de mappage, sans éditer le fichier.", "voir § 4.3"],
    ["frequence_hz", "Base de temps commune du rééchantillonnage.",
     nb(TR["frequence_hz"])],
    ["duree_fenetre_s", "Longueur d'une fenêtre de mesure.",
     nb(TR["duree_fenetre_s"])],
    ["vitesse_min_kmh", "Vitesse en deçà de laquelle on n'exploite pas.",
     nb(TR["vitesse_min_kmh"])],
    ["acceleration_max_ms2", "Frontière du transitoire.",
     nb(TR["acceleration_max_ms2"])],
    ["couple_min_nm", "Couple en deçà duquel on n'exploite pas.",
     nb(TR["couple_min_nm"])],
    ["ecart_demande_max_nm", "Détection d'une intervention du contrôle de motricité.",
     nb(TR["ecart_demande_max_nm"])],
    ["lacet_max_degs", "Critère de ligne droite, si la voie existe.",
     nb(TR["lacet_max_degs"])],
    ["<b>detection</b> (9 clés)", "Valeurs de départ du panneau Réglages.",
     "voir § 4.5"],
    ["<b>capteur</b> (6 clés)", "Identification par défaut et seuil de forte "
     "sollicitation.", "—"],
], [42, 88, 35])
p("<b>Si rien ne se calcule sur vos essais</b> : ouvrez la visualisation d'un "
  "essai. Si l'en-tête annonce 0 fenêtre retenue, la cause est presque toujours "
  "dans le mappage (voies introuvables) ou dans ces seuils — un roulage urbain "
  "à faible charge peut ne jamais atteindre %s km/h et %s N·m simultanément "
  "hors transitoire." % (nb(TR["vitesse_min_kmh"]), nb(TR["couple_min_nm"])))

h1("6. Limites connues")
p("À dire plutôt qu'à taire : ces limites sont inhérentes à la méthode, pas "
  "des défauts d'implémentation.")
table(["Limite", "Conséquence pratique"], [
    ["<b>La référence sur %s essais est peu précise.</b>" % nb(DE["n_reference"]),
     "Un σ<sub>0</sub> estimé par MAD sur 10 valeurs a une dispersion d'environ "
     "30 %. Sur une campagne saine de 30 essais, la probabilité qu'une des deux "
     "cartes alarme à tort est de l'ordre de 40 %. <b>Porter « essais de "
     "référence » à 20 ou plus dès que la campagne le permet.</b>"],
    ["<b>Une carte à mémoire réagit à un essai aberrant.</b>",
     "Un seul essai très écarté fait franchir le seuil à la CUSUM : c'est son "
     "comportement normal, et voulu. Ce qui est demandé à l'estimateur robuste, "
     "c'est de ne pas laisser cet essai fausser la <b>référence</b>. Dans le jeu "
     "de démonstration, l'essai 18 déclenche la carte ; sans lui la dérive de "
     "zéro seule est détectée à l'essai 22, neuf essais après son apparition."],
    ["<b>La voie opposée suppose un essieu symétrique.</b>",
     "Hors ligne droite ou pendant une intervention du contrôle de motricité, "
     "la comparaison n'a pas de sens. Ces échantillons sont exclus, mais sans "
     "voie de lacet mappée le critère de ligne droite se réduit à la cohérence "
     "mesure/demande : un mappage complet améliore la sélection."],
    ["<b>Le couple estimé n'est pas une référence.</b>",
     "Son erreur de modèle dépasse souvent la dérive cherchée. Il ne sert qu'à "
     "désigner laquelle des deux voies dérive, une fois l'écart établi."],
    ["<b>Une dérive commune aux deux voies est invisible.</b>",
     "Si les deux capteurs dérivent identiquement, leur différence reste nulle. "
     "C'est la limite fondamentale de la source « voie opposée » ; seuls le "
     "relevé de zéro et l'étalonnage périodique la couvrent."],
    ["<b>L'outil ne dit pas de combien corriger.</b>",
     "Il détecte et qualifie une dérive ; il ne produit ni coefficient de "
     "correction ni mesure corrigée. La suite est un étalonnage."],
], [50, 115])

h1("Annexe — Repères")
h2("Organisation du code")
table(["Fichier", "Contenu"], [
    ["<font face='%s'>coeur/detection.py</font>" % NORMALE,
     "Référence robuste, CUSUM, EWMA, verdict, discrimination, statut de "
     "fenêtre. <b>N'importe rien de Qt</b> : c'est ce qui le rend testable seul."],
    ["<font face='%s'>coeur/lecture_mf4.py</font>" % NORMALE,
     "Lecture MF4, rééchantillonnage, segmentation, sélection des fenêtres, "
     "indicateurs, lecture de voies arbitraires."],
    ["<font face='%s'>coeur/stockage.py</font>" % NORMALE,
     "Fiche de vie : un unique fichier SQLite."],
    ["<font face='%s'>ui/</font>" % NORMALE,
     "Fenêtre principale, les trois écrans, la fenêtre de mappage, la fenêtre "
     "de visualisation, et le thème (palette, styles, widget de graphique)."],
    ["<font face='%s'>tests/test_detection.py</font>" % NORMALE,
     "18 tests sur le cœur de calcul uniquement, aucun test d'interface."],
    ["<font face='%s'>donnees_demo/generateur.py</font>" % NORMALE,
     "30 essais MF4 synthétiques : sains 1 à 12, dérive de zéro 13 à 22, dérive "
     "de sensibilité de 2 % 23 à 30, essai aberrant isolé au 18."],
], [52, 113])

h2("Ce que vérifient les tests")
puces([
    "La CUSUM détecte un décalage de 1 σ en moins de 15 observations.",
    "Elle ne déclenche pas sur la majorité des séries saines de 200 "
    "observations, ce qui correspond à l'ARL visée d'environ 465 essais.",
    "L'EWMA à λ = 0,10 et L = 2,7 a un comportement comparable.",
    "Les limites EWMA contiennent bien le terme transitoire : la limite à "
    "i = 1 vaut le dixième de sa valeur asymptotique.",
    "L'estimateur robuste de σ n'est pas affecté par une valeur aberrante "
    "isolée, alors que l'écart-type classique est multiplié par plusieurs.",
    "La séquence de discrimination rend la bonne conclusion sur des cas "
    "construits : dérive d'une voie, dérive de zéro, dérive thermique, dérive "
    "de sensibilité.",
    "Le verdict d'une fenêtre isolée utilise bien l'échelle combinée, et non "
    "σ<sub>0</sub> seul.",
])

h2("Déroulé attendu sur le jeu de démonstration")
p("Verdict <b>Vigilance</b>, dérive détectée à l'essai 18, avec la conclusion "
  "« Écart gauche/droite de +5,7 N·m : dérive de la voie gauche ». Dans la "
  "visualisation de l'essai 23, le résidu monte à 13 N·m pendant les côtes puis "
  "retombe à 3 N·m sur le plat : c'est la signature visuelle d'une dérive de "
  "<b>sensibilité</b>, l'erreur étant proportionnelle au couple et non "
  "constante. À comparer avec l'essai 01, presque entièrement gris.")


# ===========================================================================
# Construction du document
# ===========================================================================
def construire(sortie: Path):
    document = SimpleDocTemplate(
        str(sortie), pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=20 * mm,
        title="Vigie Couple — notice technique",
        author="Vigie Couple", subject="Détection de dérive des capteurs de couple")
    document.build(recit, onFirstPage=pied, onLaterPages=pied)
    return sortie


if __name__ == "__main__":
    cible = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        RACINE / "documentation" / "Vigie_Couple_notice_technique.pdf"
    cible.parent.mkdir(parents=True, exist_ok=True)
    construire(cible)
    print(f"Notice écrite : {cible}")
