# Vigie Couple

Application de bureau pour la **détection précoce de dérive des capteurs de couple
embarqués** sur véhicules d'essais : transmissions instrumentées, télémétrie
Manner PCM16, étendue ±1 500 N·m.

Livrable logiciel d'un stage d'ingénieur chez FEV France (centre technique de
Belchamp, pour le compte de Stellantis). L'application répond à une seule
question, essai après essai : **ce capteur a-t-il commencé à dériver ?**

---

## Principe

Il n'existe pas d'étalon à bord. On analyse donc un **résidu**, en comparant le
capteur à trois sources imparfaites, par fiabilité décroissante :

| Rang | Source | Nature |
|---|---|---|
| 1 | **Voie opposée** (arbre gauche − arbre droit) | ne dépend d'aucun modèle — **source par défaut** |
| 2 | **Zéro à couple nul**, avant et après essai | contrôle direct du décalage de zéro |
| 3 | **Couple estimé par le calculateur** | dernier recours : le modèle a sa propre erreur |

Le résidu est suivi essai après essai par deux cartes de contrôle à mémoire
(CUSUM et EWMA), dont la référence μ₀ et σ₀ est estimée de façon **robuste**
(médiane et MAD mis à l'échelle, σ ≈ 1,4826 × MAD) sur les N premiers essais.

---

## Installation (Windows, Visual Studio Code)

Python 3.11 ou supérieur.

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Démarrage

```bat
python donnees_demo\generateur.py      :: 30 essais synthétiques, une seule fois
python -m vigie_couple.main            :: lance l'application
python -m vigie_couple.main --sombre   :: démarrage en mode sombre
```

Dans l'application : écran **Campagne** → bouton **Jeu de démonstration** →
l'écran **Surveillance** s'ouvre avec le verdict.

---

## Les trois écrans

**1. Campagne** — en haut, le **capteur suivi** : liste des capteurs
enregistrés, boutons *Nouveau capteur* et *Modifier*. Aucun import n'est
possible sans capteur sélectionné, et chaque essai est rattaché définitivement
au capteur actif au moment de l'import. Changer de capteur filtre la liste, la
Surveillance et la fiche de vie ; rien n'est perdu, seulement masqué. Le choix
est mémorisé d'un lancement à l'autre.

En dessous, l'ajout de fichiers `.mf4` (sélection multiple) ou d'un dossier
entier. La lecture se fait en tâche de fond avec barre de progression :
l'interface ne se fige jamais. **Chaque import complète la liste, il ne la
remplace jamais** : les essais déjà chargés restent en place, les doublons sont
reconnus à l'empreinte de leur contenu — un même fichier importé depuis deux
dossiers ne compte qu'une fois — et la liste est retriée par date croissante,
car c'est l'ordre chronologique qui donne leur sens aux cartes de contrôle. Le
compte rendu indique le total et le nombre effectivement ajouté.

Le tableau donne, par essai, une case à cocher, date, nom, durée, couple
maximal, biais et écart-type du résidu, et un verdict. *Retirer la sélection*
enlève les essais cochés, *Vider la liste* les enlève tous après confirmation.

**Visualiser un essai** — double-clic sur une ligne du tableau (ou bouton
*Visualiser l'essai…*) : une fenêtre montre les signaux de l'essai, un seul
graphique à la fois, en quatre onglets — Couple, Résidu, Vitesse, **Tracé
libre**. Les plages retenues pour le calcul sont surlignées en gris, et **les
zones où le résidu sort de la bande d'accord en orange**, au-delà de l'écart
admissible en rouge — toujours avec un libellé texte, jamais la couleur seule.
L'en-tête donne la part exploitable de l'essai et la répartition des phases :
c'est le premier endroit où regarder quand un essai ne produit aucun
indicateur.

L'onglet *Couple* trace **les deux voies simultanément** sur un axe unique —
elles sont toutes deux en N·m, il n'y a donc jamais de second axe des
ordonnées. Une case à cocher par série permet d'ajouter le couple estimé et la
somme des deux voies, décochés par défaut. Sous le graphique, une **courbe de
l'écart gauche − droite** partage la même base de temps : c'est le signal où
une voie qui part se voit avant que les couples eux-mêmes ne bougent. L'écart
brut à 20 Hz étant dominé par le bruit d'échantillon (± 20 N·m), c'est sa
moyenne glissante sur 2 s qui est mise en avant, le brut restant en fond.

*Tracé libre* : deux listes **éditables** donnent accès à toutes les voies du
fichier, mappées ou non — on peut aussi taper librement un nom de signal, avec
complétion insensible à la casse. Un nom absent du fichier est signalé sans
bloquer ni vider le champ, et les saisies manuelles sont mémorisées d'un essai
et d'un lancement à l'autre. Un champ *Étiquette* par voie donne à la courbe un
nom lisible dans la légende. Une troisième liste choisit l'opération — voie
seule, `A + B`, `A − B`, ou moyenne des deux.

Molette pour zoomer, glisser pour déplacer, bouton *Vue d'ensemble* pour
revenir aux échelles complètes — utile pour séparer deux voies quasi
confondues, l'écart gauche/droite ne faisant que quelques N·m sur une étendue
de 1 500.

Traitement par essai : lecture `asammdf` → rééchantillonnage sur une base de
temps commune (20 Hz) → segmentation en phases (arrêt, traction, freinage
récupératif, transitoire) → sélection des fenêtres exploitables (vitesse
stabilisée, ligne droite, hors transitoire) → une valeur de résidu par fenêtre
de 2 s → indicateurs de l'essai. **Les transitoires sont exclus** : un défaut de
synchronisation entre les deux voies y produit un élargissement de dispersion
qu'on confondrait avec du bruit.

**2. Surveillance** — l'écran principal. Un verdict unique (pastille, icône,
mot, une phrase), un seul graphique choisi par trois onglets discrets (Résidu,
CUSUM, EWMA), trois tuiles de statistiques. Les paramètres de réglage (λ, L, k,
h, source, écart maximal admissible, essais de référence) sont dans un panneau
latéral **fermé par défaut** ; toute modification recalcule immédiatement.

| Verdict | Condition |
|---|---|
| **Conforme** (vert) | aucune carte n'a franchi son seuil |
| **Vigilance** (orange) | une carte a franchi son seuil |
| **Non conforme** (rouge) | écart supérieur à l'écart maximal admissible, ou dérive de zéro majeure |

Un quatrième état, **En attente** (gris), s'affiche sous trois essais chargés :
la référence n'est pas estimable.

**Réinitialiser le suivi** (écran Fiche de vie) — après un réétalonnage ou une
réparation, l'ancienne référence n'est plus valable. Le bouton demande un motif
et **n'efface rien** : il pose une **rupture de série**. Les cartes repartent de
zéro, une nouvelle référence μ₀ et σ₀ est estimée sur les essais suivants, et
les essais antérieurs restent affichés avec un trait vertical marquant la
rupture et son motif. Tant que le segment en cours compte moins d'essais que la
période de référence, la Surveillance annonce « Référence en cours de
constitution — N essais sur M » au lieu d'un verdict. La suppression réelle des
données d'un capteur existe séparément, dans le menu **Capteur**, avec double
confirmation et saisie du numéro de série.

**3. Fiche de vie** — historique persistant par capteur dans un unique fichier
SQLite (`vigie_couple/vigie_couple.db`, créé au premier lancement) :
identification, relevés de zéro (alimentés automatiquement par chaque campagne)
et contrôles par résistance de shunt, étalonnages, usage cumulé, échéance de
réétalonnage avec **alerte au-delà de 370 jours** (plafond du règlement
technique mondial ONU n° 21 pour la mesure de couple aux essieux), et export
d'une fiche de synthèse d'une page en PDF.

---

## Cartes de contrôle

**CUSUM** — `C⁺ᵢ = max(0, xᵢ − (μ₀ + K) + C⁺ᵢ₋₁)` et
`C⁻ᵢ = max(0, (μ₀ − K) − xᵢ + C⁻ᵢ₋₁)`, avec `K = k·σ₀` et alarme au-delà de
`H = h·σ₀`. Réglage par défaut k = 0,5 et h = 5.

**EWMA** — `zᵢ = λ·xᵢ + (1 − λ)·zᵢ₋₁` avec `z₀ = μ₀`, limites
`μ₀ ± L·σ₀·√[(λ/(2−λ))·(1 − (1−λ)^(2i))]`. Réglage par défaut λ = 0,10 et
L = 2,7. Le **terme transitoire** est indispensable : sans lui les limites sont
trop larges en début de série et la détection précoce est manquée précisément là
où elle compte.

Longueurs moyennes de série sans défaut mesurées par les tests (μ₀ et σ₀
connus) : **CUSUM ≈ 450 essais**, **EWMA ≈ 315 essais**. Les deux cartes
détectent un décalage de 1 σ en une dizaine d'essais.

**Échelle d'une fenêtre isolée.** Le surlignage ne compare pas une fenêtre à
σ₀ : σ₀ mesure la dispersion d'un essai à l'autre, alors qu'une fenêtre porte
en plus la dispersion interne à l'essai. L'échelle correcte est
√(σ₀² + σ_fenêtre²), soit un intervalle de prédiction pour une fenêtre. Sur le
jeu de démonstration, σ₀ = 0,82 et σ_fenêtre = 0,93 N·m : comparer à σ₀ seul
signalerait la moitié des fenêtres d'un essai parfaitement sain.

## Discrimination

Quand une carte alarme, l'application exécute une séquence ordonnée du plus
indépendant du modèle au plus dépendant, et affiche **la première conclusion
atteinte**, en une phrase sous le verdict :

1. écart gauche/droite présent → dérive d'une des deux voies, laquelle ;
2. zéro déplacé au-delà du seuil de vigilance → dérive de zéro confirmée ;
3. écart corrélé à la température → dérive thermique ;
4. écart proportionnel au niveau de couple → dérive de sensibilité ;
5. aucun des précédents → écart non expliqué, étalonnage de vérification.

---

## Configuration

Tout est dans `vigie_couple/config.yaml` : mappage des voies (aucun nom de
signal en dur dans le code), paramètres de traitement, réglages de détection,
identification du capteur. Les voies `temperature` et `vitesse_lacet` sont
facultatives : laissées vides, la sélection des fenêtres se rabat sur le critère
de vitesse stabilisée et le test thermique est simplement sauté.

Le **jeu de démonstration ne dépend pas de ce mappage** : ses fichiers sont
produits par le générateur, leurs noms de voies sont donc connus et utilisés
tels quels. Adapter `config.yaml` à vos acquisitions ne le casse pas.

**Mappage des voies sans éditer le YAML** — bouton **« Configurer les
voies… »**, premier de l'écran Campagne : choisis un essai `.mf4` d'exemple,
les voies qu'il contient apparaissent dans des listes déroulantes en face de
chaque grandeur attendue (couple gauche/droite obligatoires, le reste
facultatif). *Enregistrer* réécrit uniquement les lignes de voies dans
`config.yaml`, sans toucher aux commentaires ni aux autres réglages. C'est le
premier réflexe à avoir avant de charger des acquisitions réelles : sans cette
étape, une voie au nom différent du jeu de démonstration fait échouer
silencieusement la lecture de l'essai (message discret dans la ligne d'état,
sous les boutons).

## Jeu de démonstration

`donnees_demo/generateur.py` produit 30 essais MF4 sur une boucle d'essai
réaliste (paliers de vitesse et côtes, pour obtenir des fenêtres exploitables
jusqu'à ~500 N·m) :

* essais 1 à 12 : capteur sain, résidu centré ;
* essais 13 à 22 : dérive de zéro lente sur la voie gauche, amplitude finale
  ≈ 1,5 σ ;
* essais 23 à 30 : dérive de sensibilité de 2 % sur la même voie, cumulée ;
* essai 18 : valeur aberrante isolée (≈ 9 σ).

La campagne est calée sur la date du jour et le générateur inscrit, s'il n'y en
a aucun, un étalonnage de démonstration dans la fiche de vie — sinon la tuile
« jours avant échéance » resterait vide.

Ce qu'on observe : verdict **Vigilance**, dérive détectée à l'essai 18,
« Écart gauche/droite de +5,7 N·m : dérive de la voie gauche ».

## Notice technique

`documentation/Vigie_Couple_notice_technique.pdf` — 13 pages : le principe, la
logique de calcul détaillée (chaîne de traitement, référence robuste, CUSUM,
EWMA, verdict, discrimination), et le rôle exact de chaque bouton de
l'interface. Régénérable par `python documentation/notice.py` ; les seuils
cités y sont lus dans `config.yaml` à l'exécution, ils ne peuvent pas se
désynchroniser du code.

## Tests

```bat
python -m pytest tests -q
```

24 tests sur le cœur de calcul uniquement (aucun test d'interface) : délai de
détection d'un décalage de 1 σ, absence de fausse alarme sur série saine,
comportement comparable de l'EWMA, présence du terme transitoire, insensibilité
de σ₀ à une valeur aberrante, les cinq branches de la discrimination, et le
verdict d'une fenêtre isolée avec son échelle propre, la fusion des imports
successifs sans doublon ni perte, et la remise à zéro des cartes à une rupture.

---

## Ce que l'application ne fait pas

Pas d'apprentissage automatique, pas de serveur ni d'API, pas de multi-
utilisateur, pas d'export PowerPoint, pas de système de plugins, pas plus de
trois écrans. Toute fonction qui n'aide pas à répondre à « ce capteur dérive-t-il ? »
est hors périmètre.

## Limites connues, à dire en soutenance

* **La référence sur 10 essais est peu précise.** σ₀ estimé par MAD sur 10
  valeurs a une dispersion d'environ 30 % ; sur une campagne saine de 30 essais,
  la probabilité qu'une des deux cartes alarme à tort est de l'ordre de 40 %.
  Porter « essais de référence » à 20 ou plus dès que la campagne le permet.
* **Une carte à mémoire réagit à un essai aberrant** : dans le jeu de
  démonstration, l'essai 18 (≈ 9 σ) déclenche la CUSUM à lui seul. C'est le
  comportement normal, et voulu, d'une CUSUM. Ce qui est demandé à l'estimateur
  robuste, c'est de ne pas laisser cet essai fausser μ₀ et σ₀ : porté à 20
  essais de référence, il ne les déplace que marginalement. Sans cet essai, la
  dérive de zéro seule est détectée à l'essai 22, soit neuf essais après son
  apparition — conforme à la longueur de série attendue.
* **La voie opposée suppose un essieu symétrique** : hors ligne droite ou en
  intervention du contrôle de motricité, la comparaison n'a pas de sens. Ces
  échantillons sont exclus ; sans voie de lacet mappée, le critère de ligne
  droite se réduit à la vitesse stabilisée et à la cohérence mesure/demande.
* **Le couple estimé n'est pas une référence.** Il ne sert qu'à désigner la voie
  suspecte lorsque l'écart gauche/droite est établi.
* La fiche de vie cumule les essais : rejouer le générateur ajoute une nouvelle
  campagne au même capteur (les essais sont identifiés par leur nom de fichier).

## Architecture

```
vigie_couple/
  main.py              point d'entrée
  config.yaml          mappage des voies et réglages
  ui/
    fenetre.py         fenêtre principale, navigation, état partagé
    ecran_campagne.py  écran 1
    ecran_surveillance.py  écran 2
    ecran_fiche.py     écran 3 et export PDF
    dialogue_mappage.py  fenêtre de mappage des voies (config.yaml)
    fenetre_essai.py   visualisation d'un essai et zones de dérive
    theme.py           palette, styles, clair/sombre, widget de graphique
  coeur/
    lecture_mf4.py     lecture, rééchantillonnage, segmentation, résidus
    detection.py       référence robuste, CUSUM, EWMA, discrimination — sans Qt
    stockage.py        SQLite
tests/test_detection.py
donnees_demo/generateur.py
```

Onze modules d'application, environ 2 460 lignes dont l'essentiel de code
effectif : le reste est constitué des commentaires et docstrings en français.
Le périmètre a dépassé les 1 500 lignes visées au départ, par ajouts demandés
après la première livraison (mappage des voies, visualisation d'essai).
`detection.py` n'importe rien de Qt, ce qui le rend testable seul.
