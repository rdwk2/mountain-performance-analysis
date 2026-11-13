"""Les outils d'inférence de la piste analyse (AN3-1, ``docs/decisions/0021``) :
moindres carrés ordinaires et généralisés, REML d'une covariance à trois composantes,
intervalles de Student, Holm et Bonferroni, les trois lectures de la charte,
autocorrélation des résidus par classe d'écart, CR2 et bootstrap sauvage par grappes,
bootstraps paramétrique et des résidus, bande simultanée max-t, régression de Huber,
spline cubique naturelle, simulation de puissance et seuil calibré.

Génériques : ils prennent des tableaux et des fonctions, et ne savent rien des montées
ni des journées. Seul importeur de numpy et de scipy dans ``src/`` (extra ``analyse``,
``docs/decisions/0011``)."""
