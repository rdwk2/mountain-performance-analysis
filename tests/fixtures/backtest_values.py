"""Valeurs du monde synthétique de ``mperf backtest`` (brief M4b-5, § 7) — données
seules, recopiées telles quelles.

Calculées en conception avant écriture par le prototype, sur
``fixtures/backtest_world.py`` (registre et instants fixés). Nombres écrits comme en
Python ; tolérance relative ``1e−9``, absolue ``1e−12`` (les valeurs nulles au bruit
de l'arrondi près) ; motifs, effectifs, chaînes et booléens exacts.

Utilisées par ``tests/test_backtest_execution.py`` et ``tests/test_backtest_report.py``.
"""

# ruff: noqa: E501
# fmt: off

DOMAINS = (
    ('a-2026-05-28', 54.34663536776351, 'prepare.gpx', None),
    ('velo-2026-05-30', None, None, 'sortie non tracée, sans référence'),
    ('trail-2026-05-31', None, None, 'sortie non tracée, sans référence'),
    ('a-2026-06-03', 54.34663536776351, 'prepare.gpx', None),
    ('b-2026-06-04', 47.19158920055501, 'b08.gpx', None),
    ('a-2026-06-06', 54.34663536776351, 'prepare.gpx', None),
    ('velo-2026-06-06', None, None, 'sortie non tracée, sans référence'),
    ('b-2026-06-08', 47.19158920055501, 'b08.gpx', None),
    ('velo-2026-06-09', None, None, 'sortie non tracée, sans référence'),
    ('a-2026-06-10', 54.34663536776351, 'prepare.gpx', None),
    ('plat-2026-06-11', 4.819175763409964, 'plat11.gpx', None),
    ('a-2026-06-12', 54.34663536776351, 'prepare.gpx', None),
    ('b-2026-06-12', 47.19158920055501, 'b08.gpx', None),
    ('libre-2026-06-12', 50.19132384687405, 'libre12.gpx', None),
    ('a-2026-06-14', 54.34663536776351, 'prepare.gpx', None),
    ('libre-2026-06-15', 47.77699379856031, 'libre15_1.gpx, libre15_2.gpx', None),
    ('c-2026-06-16', 51.497449187327845, 'c16.gpx', None),
    ('x-2026-06-18', None, 'x18.gpx', 'profil de domaine illisible (x18.gpx) : Aucun <trkpt> dans le fichier GPX.'),
    ('a-2026-06-20', 54.34663536776351, 'prepare.gpx', None),
    ('b-2026-06-25', 47.19158920055501, 'b08.gpx', None),
    ('a-2026-06-27', 54.34663536776351, 'prepare.gpx', None),
)
"""Le domaine de chaque sortie du manifeste, dans son ordre (``0010`` D2.1 et sa
précision de M4b-5) : identifiant, D+/km, fichiers du profil de domaine, motif."""


EXCLUSIONS = (
    ('a-2026-05-28', 'hors domaine : partie le 2026-05-28, avant le début du domaine (2026-06-01)'),
    ('velo-2026-05-30', 'hors domaine : sport mtb, pas du trail à pied'),
    ('trail-2026-05-31', 'hors domaine : partie le 2026-05-31, avant le début du domaine (2026-06-01)'),
    ('velo-2026-06-06', 'non retenue : écoulé cumulé du jour 18825 s, 4 h ou plus (0010 D0)'),
    ('velo-2026-06-09', 'hors domaine : sport mtb, pas du trail à pied'),
    ('plat-2026-06-11', 'hors domaine : D+/km 4.8, sous 40'),
    ('x-2026-06-18', 'hors domaine : D+/km inconnu (profil de domaine illisible (x18.gpx) : Aucun <trkpt> dans le fichier GPX.)'),
    ('autre-2026-06-05', "refusée : athlete_ref différent de celui du manifeste : ce n'est pas une sortie de l'athlète (0010 D2.6)."),
)
"""Les exclusions de la déclaration, dans l'ordre : par jour et par rang, puis les
sorties d'un autre athlète."""


PERFORMANCES = (
    ('2026-06-03', ('a-2026-06-03',), '2026-05-26T22:00:00+00:00'),
    ('2026-06-04', ('b-2026-06-04',), '2026-05-27T22:00:00+00:00'),
    ('2026-06-06', ('a-2026-06-06',), '2026-05-29T22:00:00+00:00'),
    ('2026-06-08', ('b-2026-06-08',), '2026-05-31T22:00:00+00:00'),
    ('2026-06-10', ('a-2026-06-10',), '2026-06-02T22:00:00+00:00'),
    ('2026-06-12', ('a-2026-06-12', 'b-2026-06-12', 'libre-2026-06-12'), '2026-06-04T22:00:00+00:00'),
    ('2026-06-14', ('a-2026-06-14',), '2026-06-06T22:00:00+00:00'),
    ('2026-06-15', ('libre-2026-06-15',), '2026-06-07T22:00:00+00:00'),
    ('2026-06-16', ('c-2026-06-16',), '2026-06-08T22:00:00+00:00'),
    ('2026-06-20', ('a-2026-06-20',), '2026-06-12T22:00:00+00:00'),
    ('2026-06-25', ('b-2026-06-25',), '2026-06-17T22:00:00+00:00'),
    ('2026-06-27', ('a-2026-06-27',), '2026-06-19T22:00:00+00:00'),
)
"""Les performances déclarées : jour, sorties, origine ``o_j`` (D2.5)."""


SCORED = ('a-2026-06-03', 'b-2026-06-04', 'a-2026-06-06', 'b-2026-06-08', 'a-2026-06-10', 'a-2026-06-12', 'b-2026-06-12', 'libre-2026-06-12', 'a-2026-06-14', 'libre-2026-06-15', 'b-2026-06-25', 'a-2026-06-27')
"""Les sorties scorées, dans l'ordre de la déclaration."""


UNSCORED = (
    ('c-2026-06-16', 'trace refusée (c16.gpx) : c16.gpx, trkpt[0].time : instant manquant.'),
    ('a-2026-06-20', 'sortie non tracée'),
)
"""Les sorties déclarées non scorées, et leur motif."""


ENTRIES = (
    ('2026-06-03', ('repeatability',), ('a',), None, 0),
    ('2026-06-04', ('repeatability',), ('b',), None, 0),
    ('2026-06-06', ('repeatability',), ('a',), None, 1),
    ('2026-06-08', ('repeatability',), ('b',), None, 0),
    ('2026-06-10', ('repeatability',), ('a',), None, 0),
    ('2026-06-12', ('repeatability', 'development'), ('a', 'b'), 'multi_outing_day', None),
    ('2026-06-14', ('development',), (), None, 0),
    ('2026-06-15', ('development',), (), None, 0),
    ('2026-06-16', ('development',), (), 'not_scored', None),
    ('2026-06-20', ('development',), (), 'not_scored', None),
    ('2026-06-25', ('confirmation',), (), None, 0),
    ('2026-06-27', ('confirmation',), (), None, 0),
)
"""Par performance : jour, jeux de ses sorties, parcours de ses sorties de répétabilité,
motif, et ``c`` de son ``θ_bas`` (``M θ<c + 1>``) ; ``None`` sans scores."""


USAGE_ELAPSED = (
    ('level', None, ((0.025017750906179293, 5, (('multi_outing_day', 1),)), (0.1322825785895822, 1, (('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.08539178759813744, 2, ()))),
    ('abs_level', None, ((0.05757064241421285, 5, (('multi_outing_day', 1),)), (0.1322825785895822, 1, (('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.08539178759813744, 2, ()))),
    ('dispersion', None, ((0.06372796875664852, 5, (('multi_outing_day', 1),)), (0.049651705455974464, 1, (('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.04599119168420636, 2, ()))),
    ('within', None, ((0.05448056522919955, 5, (('multi_outing_day', 1),)), (0.04173323391830258, 1, (('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.03573071458227753, 2, ()))),
    ('between', None, ((0.04621943597165134, 5, (('multi_outing_day', 1),)), (0.033660121913756294, 1, (('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.03357008485004917, 2, ()))),
    ('compensation', None, ((0.03697203244420237, 5, (('multi_outing_day', 1),)), (0.02574165037608441, 1, (('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.023309607748120333, 2, ()))),
    ('shape', 'ascent', ((0.04470680363503955, 5, (('multi_outing_day', 1),)), (0.034017884789303204, 1, (('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.03377537627136691, 2, ()))),
    ('abs_class_level', 'ascent', ((0.06972455454121884, 5, (('multi_outing_day', 1),)), (0.1663004633788854, 1, (('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.11916716386950435, 2, ()))),
    ('class_dispersion', 'ascent', ((0.02705993331512916, 5, (('multi_outing_day', 1),)), (0.03155231120268593, 1, (('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.028521515362789435, 2, ()))),
    ('shape', 'flat', ((-0.025438152059338193, 2, (('multi_outing_day', 1), ('underrepresented', 3))), (None, 0, (('multi_outing_day', 1), ('underrepresented', 1), ('not_scored', 2), ('no_reference', 1))), (-0.026020076469079265, 1, (('underrepresented', 1),)))),
    ('abs_class_level', 'flat', ((0.03992115825840154, 2, (('multi_outing_day', 1), ('underrepresented', 3))), (None, 0, (('multi_outing_day', 1), ('underrepresented', 1), ('not_scored', 2), ('no_reference', 1))), (0.07863959038868981, 1, (('underrepresented', 1),)))),
    ('class_dispersion', 'flat', ((0.01495066807083342, 2, (('multi_outing_day', 1), ('underrepresented', 3))), (None, 0, (('multi_outing_day', 1), ('underrepresented', 1), ('not_scored', 2), ('no_reference', 1))), (0.014982111832748082, 1, (('underrepresented', 1),)))),
    ('shape', 'descent', ((-0.05660916533725633, 5, (('multi_outing_day', 1),)), (-0.03229149682342018, 1, (('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (-0.037189973687985725, 2, ()))),
    ('abs_class_level', 'descent', ((0.06156695552282403, 5, (('multi_outing_day', 1),)), (0.09999108176616202, 1, (('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.048201813910151714, 2, ()))),
    ('class_dispersion', 'descent', ((0.0918090441503483, 5, (('multi_outing_day', 1),)), (0.038735059897168626, 1, (('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.04332626034196414, 2, ()))),
    ('shape', 'mixed', ((-0.022759242311002206, 3, (('multi_outing_day', 1), ('underrepresented', 2))), (-0.039835360202102044, 1, (('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (-0.038215211088662056, 1, (('underrepresented', 1),)))),
    ('abs_class_level', 'mixed', ((0.03042075456048146, 3, (('multi_outing_day', 1), ('underrepresented', 2))), (0.09244721838748016, 1, (('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.027908697249843746, 1, (('underrepresented', 1),)))),
    ('class_dispersion', 'mixed', ((0.08801684652627699, 3, (('multi_outing_day', 1), ('underrepresented', 2))), (0.08801684652629505, 1, (('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.08801684652623536, 1, (('underrepresented', 1),)))),
    ('max_abs_passage_error_s', None, ((132.42039876399468, 5, (('multi_outing_day', 1),)), (301.64078928252866, 1, (('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (177.424516412127, 2, ()))),
    ('q_usage', None, ((0.05998405215116126, 4, (('insufficient_support', 1), ('multi_outing_day', 1))), (0.13621945495335813, 1, (('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.08873550370442729, 2, ()))),
)
"""Agrégats d'usage sous l'écoulé : métrique, classe, puis par jeu (répétabilité,
développement, confirmation) la moyenne, l'effectif et les motifs."""


CONTROL_ELAPSED = (
    ('level', None, ((0.034874184178335155, 5, (('multi_outing_day', 1),)), (0.07642761469981363, 2, (('multi_outing_day', 1), ('not_scored', 2))), (0.09229457726357951, 2, ()))),
    ('abs_level', None, ((0.05968326018822059, 5, (('multi_outing_day', 1),)), (0.07642761469981363, 2, (('multi_outing_day', 1), ('not_scored', 2))), (0.09229457726357951, 2, ()))),
    ('dispersion', None, ((0.06410706801080135, 5, (('multi_outing_day', 1),)), (0.06158089050008424, 2, (('multi_outing_day', 1), ('not_scored', 2))), (0.04563378851113102, 2, ()))),
    ('within', None, ((0.053555918386679294, 5, (('multi_outing_day', 1),)), (0.03342259615002205, 2, (('multi_outing_day', 1), ('not_scored', 2))), (0.03490096537817613, 2, ()))),
    ('between', None, ((0.04802295836206788, 5, (('multi_outing_day', 1),)), (0.055333461847792906, 2, (('multi_outing_day', 1), ('not_scored', 2))), (0.034514040454709766, 2, ()))),
    ('compensation', None, ((0.037471808737945825, 5, (('multi_outing_day', 1),)), (0.027175167497730725, 2, (('multi_outing_day', 1), ('not_scored', 2))), (0.023781217321754873, 2, ()))),
    ('shape', 'ascent', ((0.04690138516186952, 5, (('multi_outing_day', 1),)), (0.053847698448783426, 2, (('multi_outing_day', 1), ('not_scored', 2))), (0.034981459719283466, 2, ()))),
    ('abs_class_level', 'ascent', ((0.08177556934020468, 5, (('multi_outing_day', 1),)), (0.13027531314859706, 2, (('multi_outing_day', 1), ('not_scored', 2))), (0.12727603698286297, 2, ()))),
    ('class_dispersion', 'ascent', ((0.025565422233538887, 5, (('multi_outing_day', 1),)), (0.024362950084019473, 2, (('multi_outing_day', 1), ('not_scored', 2))), (0.02757020516271337, 2, ()))),
    ('shape', 'flat', ((-0.02460969570972287, 2, (('multi_outing_day', 1), ('underrepresented', 3))), (None, 0, (('multi_outing_day', 1), ('underrepresented', 2), ('not_scored', 2))), (-0.024811969779399076, 1, (('underrepresented', 1),)))),
    ('abs_class_level', 'flat', ((0.041144361550355696, 2, (('multi_outing_day', 1), ('underrepresented', 3))), (None, 0, (('multi_outing_day', 1), ('underrepresented', 2), ('not_scored', 2))), (0.07969686346440845, 1, (('underrepresented', 1),)))),
    ('class_dispersion', 'flat', ((0.01580525457193998, 2, (('multi_outing_day', 1), ('underrepresented', 3))), (None, 0, (('multi_outing_day', 1), ('underrepresented', 2), ('not_scored', 2))), (0.01652572416852143, 1, (('underrepresented', 1),)))),
    ('shape', 'descent', ((-0.059470693541821384, 5, (('multi_outing_day', 1),)), (-0.07002710943729454, 2, (('multi_outing_day', 1), ('not_scored', 2))), (-0.03843439939488032, 2, ()))),
    ('abs_class_level', 'descent', ((0.05865955924204861, 5, (('multi_outing_day', 1),)), (0.10285875663259272, 2, (('multi_outing_day', 1), ('not_scored', 2))), (0.05386017786869918, 2, ()))),
    ('class_dispersion', 'descent', ((0.09170986798187608, 5, (('multi_outing_day', 1),)), (0.04117427207385441, 2, (('multi_outing_day', 1), ('not_scored', 2))), (0.042120009274287315, 2, ()))),
    ('shape', 'mixed', ((-0.024013277180717146, 3, (('multi_outing_day', 1), ('underrepresented', 2))), (-0.04363928401028554, 1, (('multi_outing_day', 1), ('underrepresented', 1), ('not_scored', 2))), (-0.040003156353066484, 1, (('underrepresented', 1),)))),
    ('abs_class_level', 'mixed', ((0.023933328242858643, 3, (('multi_outing_day', 1), ('underrepresented', 2))), (0.10148327771775943, 1, (('multi_outing_day', 1), ('underrepresented', 1), ('not_scored', 2))), (0.04007716493028499, 1, (('underrepresented', 1),)))),
    ('class_dispersion', 'mixed', ((0.08485224948756724, 3, (('multi_outing_day', 1), ('underrepresented', 2))), (0.08908982001444157, 1, (('multi_outing_day', 1), ('underrepresented', 1), ('not_scored', 2))), (0.08678878943771047, 1, (('underrepresented', 1),)))),
)
"""Agrégats de contrôle sous l'écoulé."""


USAGE_LOW = (
    ('level', None, ((0.05809538202048127, 5, (('multi_outing_day', 1),)), (0.15615005999622558, 1, (('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.11125990792023327, 2, ()))),
    ('abs_level', None, ((0.06549263810894136, 5, (('multi_outing_day', 1),)), (0.15615005999622558, 1, (('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.11125990792023327, 2, ()))),
    ('dispersion', None, ((0.04966091040590194, 2, (('zero_time', 3), ('multi_outing_day', 1))), (None, 0, (('zero_time', 1), ('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.05111123750681433, 1, (('zero_time', 1),)))),
    ('within', None, ((0.03286461175621057, 2, (('zero_time', 3), ('multi_outing_day', 1))), (None, 0, (('zero_time', 1), ('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.03449660295490617, 1, (('zero_time', 1),)))),
    ('between', None, ((0.036466003369376, 2, (('zero_time', 3), ('multi_outing_day', 1))), (None, 0, (('zero_time', 1), ('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.035852538472315565, 1, (('zero_time', 1),)))),
    ('compensation', None, ((0.019669704719684614, 2, (('zero_time', 3), ('multi_outing_day', 1))), (None, 0, (('zero_time', 1), ('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.019237903920407397, 1, (('zero_time', 1),)))),
    ('shape', 'ascent', ((0.03678675026394571, 2, (('zero_time', 3), ('multi_outing_day', 1))), (None, 0, (('zero_time', 1), ('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.0361347796742188, 1, (('zero_time', 1),)))),
    ('abs_class_level', 'ascent', ((0.13040758112409928, 2, (('zero_time', 3), ('multi_outing_day', 1))), (None, 0, (('zero_time', 1), ('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.17020833173828115, 1, (('zero_time', 1),)))),
    ('class_dispersion', 'ascent', ((0.028207900671290267, 2, (('zero_time', 3), ('multi_outing_day', 1))), (None, 0, (('zero_time', 1), ('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.030053908398741825, 1, (('zero_time', 1),)))),
    ('shape', 'flat', ((-0.05369967260175204, 2, (('zero_time', 3), ('multi_outing_day', 1))), (None, 0, (('zero_time', 1), ('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (-0.05543396167537254, 1, (('zero_time', 1),)))),
    ('abs_class_level', 'flat', ((0.03992115825840154, 2, (('zero_time', 3), ('multi_outing_day', 1))), (None, 0, (('zero_time', 1), ('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.07863959038868981, 1, (('zero_time', 1),)))),
    ('class_dispersion', 'flat', ((0.01495066807083342, 2, (('zero_time', 3), ('multi_outing_day', 1))), (None, 0, (('zero_time', 1), ('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.014982111832748082, 1, (('zero_time', 1),)))),
    ('shape', 'descent', ((-0.02858082734813786, 2, (('zero_time', 3), ('multi_outing_day', 1))), (None, 0, (('zero_time', 1), ('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (-0.026471352458091096, 1, (('zero_time', 1),)))),
    ('abs_class_level', 'descent', ((0.06504000351201572, 2, (('zero_time', 3), ('multi_outing_day', 1))), (None, 0, (('zero_time', 1), ('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.10760219960597125, 1, (('zero_time', 1),)))),
    ('class_dispersion', 'descent', ((0.05394927397323021, 2, (('zero_time', 3), ('multi_outing_day', 1))), (None, 0, (('zero_time', 1), ('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.05637507394247866, 1, (('zero_time', 1),)))),
    ('shape', 'mixed', ((None, 0, (('zero_time', 3), ('multi_outing_day', 1), ('underrepresented', 2))), (None, 0, (('zero_time', 1), ('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (None, 0, (('zero_time', 1), ('underrepresented', 1))))),
    ('abs_class_level', 'mixed', ((None, 0, (('zero_time', 3), ('multi_outing_day', 1), ('underrepresented', 2))), (None, 0, (('zero_time', 1), ('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (None, 0, (('zero_time', 1), ('underrepresented', 1))))),
    ('class_dispersion', 'mixed', ((None, 0, (('zero_time', 3), ('multi_outing_day', 1), ('underrepresented', 2))), (None, 0, (('zero_time', 1), ('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (None, 0, (('zero_time', 1), ('underrepresented', 1))))),
    ('max_abs_passage_error_s', None, ((129.97772237812788, 5, (('multi_outing_day', 1),)), (349.8333333333517, 1, (('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (222.57858853972834, 2, ()))),
    ('q_usage', None, ((0.06281421771348705, 4, (('insufficient_support', 1), ('multi_outing_day', 1))), (0.1552972755031385, 1, (('multi_outing_day', 1), ('not_scored', 2), ('no_reference', 1))), (0.11132703695043, 2, ()))),
)
"""Agrégats d'usage sous ``M θ_bas`` de chaque performance."""


COMPARISONS = {
    'a': (3, False, (('abs_level', None, 0.0705017847460813, 3, (0.05237819714519492, 3, (('multi_outing_day', 1),))), ('abs_class_level', 'ascent', 0.03789801007325403, 3, (0.048638353074802555, 3, (('multi_outing_day', 1),))), ('class_dispersion', 'ascent', 0.0016531507281355104, 3, (0.032631477684955085, 3, (('multi_outing_day', 1),))), ('abs_class_level', 'flat', None, 0, (None, 0, (('multi_outing_day', 1), ('underrepresented', 3)))), ('class_dispersion', 'flat', None, 0, (None, 0, (('multi_outing_day', 1), ('underrepresented', 3)))), ('abs_class_level', 'descent', 0.13901442293430175, 3, (0.08906308806943547, 3, (('multi_outing_day', 1),))), ('class_dispersion', 'descent', 0.18491874997454993, 3, (0.1197465994140568, 3, (('multi_outing_day', 1),))), ('abs_class_level', 'mixed', 0.037067597094050705, 3, (0.03042075456048146, 3, (('multi_outing_day', 1),))), ('class_dispersion', 'mixed', 4.2397753982944236e-14, 3, (0.08801684652627699, 3, (('multi_outing_day', 1),))))),
    'b': (2, True, (('abs_level', None, 0.0390021578032692, 2, (0.06535931031773974, 2, (('multi_outing_day', 1),))), ('abs_class_level', 'ascent', 0.03924303187184367, 2, (0.10135385674084328, 2, (('multi_outing_day', 1),))), ('class_dispersion', 'ascent', 4.8465316481644884e-05, 2, (0.018702616760390266, 2, (('multi_outing_day', 1),))), ('abs_class_level', 'flat', 0.03913987682902778, 2, (0.03992115825840154, 2, (('multi_outing_day', 1),))), ('class_dispersion', 'flat', 0.00011767834227564276, 2, (0.01495066807083342, 2, (('multi_outing_day', 1),))), ('abs_class_level', 'descent', 0.038541913985415455, 2, (0.020322756702906883, 2, (('multi_outing_day', 1),))), ('class_dispersion', 'descent', 0.00122963797059317, 2, (0.04990271125478554, 2, (('multi_outing_day', 1),))), ('abs_class_level', 'mixed', None, 0, (None, 0, (('multi_outing_day', 1), ('underrepresented', 2)))), ('class_dispersion', 'mixed', None, 0, (None, 0, (('multi_outing_day', 1), ('underrepresented', 2)))))),
}
"""Par parcours : jours, « un seul contraste », puis par ligne la métrique, la classe,
``F`` et son effectif ``m``, et l'agrégat de v0 sur les jours du parcours."""


REFERENCES = {
    'a': (('2026-06-03', '2026-06-06', '2026-06-10'), ('2026-06-12',), False, 'prepare.gpx'),
    'b': (('2026-06-04', '2026-06-08'), ('2026-06-12',), True, 'b08.gpx'),
}
"""Par parcours : jours, jours multi-sorties écartés, « un seul contraste », fichier."""


SUBCLASSES = {
    'a-2026-06-03': ('.......rrrusss....', '.......rrrssss....'),
    'b-2026-06-04': ('.........rrrusu', '.........rrrsss'),
    'a-2026-06-06': ('.......rrrusss....', '.......rrrssss....'),
    'b-2026-06-08': ('.........rrrusu', '.........rrrsss'),
    'a-2026-06-10': ('.......rrrus....', '.......rrrss....'),
    'a-2026-06-12': ('.......rrrusss....', '.......rrrssss....'),
    'b-2026-06-12': ('.........rrrusu', '.........rrrsss'),
    'libre-2026-06-12': ('....rrrr...', '....rrrr...'),
    'a-2026-06-14': ('.......rrrusss....', '.......rrrssss....'),
    'libre-2026-06-15': ('....rrrr...', '....rrrr...'),
    'b-2026-06-25': ('.........rrrusu', '.........rrrsss'),
    'a-2026-06-27': ('.......rrrusss....', '.......rrrssss....'),
}
"""Sous-classe de chaque segment admis, au seuil 0,80 puis 0,60 : ``r`` roulant, ``s``
raide, ``u`` non départagé, ``.`` hors de la classe descente."""


FRACTIONS_A03 = (
    (0.0, 0.0),
    (0.0, 0.0),
    (0.0, 0.0),
    (0.0, 0.0),
    (0.0, 0.0),
    (0.0, 0.0),
    (0.6, 0.0),
    (1.0, 0.0),
    (1.0, 0.0),
    (1.0, 0.0),
    (0.4, 0.6),
    (0.0, 1.0),
    (0.0, 1.0),
    (0.0, 1.0),
    (0.2, 0.2),
    (0.0, 0.0),
    (0.0, 0.0),
    (0.0, 0.0),
)
"""Fractions roulante et raide des segments admis de ``a-2026-06-03``, à 1e−12 près."""


SUBCLASS_METRICS_A03 = {
    0: (('rolling', 3, False, 0.039220713153053095, 2.6321537542154767e-15, 0.02051948336615443), ('steep', 3, False, -0.05129329438768638, 1.9475162223632944e-15, -0.06999452417458504)),
    1: (('rolling', 3, False, 0.039220713153053095, 2.6321537542154767e-15, -0.0007579150811304544), ('steep', 3, False, -0.05129329438768638, 1.9475162223632944e-15, -0.09127192262186992)),
    6: (('rolling', 3, False, 0.039220713153053095, 2.6321537542154767e-15, 0.02051948336615443), ('steep', 3, False, -0.05129329438768638, 1.9475162223632944e-15, -0.06999452417458504)),
}
"""Métriques des descentes roulantes puis raides de ``a-2026-06-03`` (usage, seuil
0,80), par rang de l'horloge dans ``CLOCKS`` : sous-classe, segments, trop peu
représentée, ``E_R``, ``D_R``, ``E_R − L``."""


SUBCLASS_METRICS_A06 = {
    0: (('rolling', 3, False, -0.40653291386913143, 0.4414969002259812, -0.32515068509904754), ('steep', 3, False, -0.09211528890781512, 6.009544713710723e-14, -0.010733060137731246)),
    2: (('rolling', 3, False, -0.12657617130855686, 0.13166218550439085, -0.10808303108740663), ('steep', 3, False, -0.09211528890781512, 6.009544713710723e-14, -0.07362214868666489)),
    6: (('rolling', 3, False, -0.14115450631016924, 0.1497785423890225, -0.10059427206034058), ('steep', 3, False, -0.09211528890781512, 6.009544713710723e-14, -0.05155505465798647)),
}
"""Métriques des descentes roulantes puis raides de ``a-2026-06-06`` (usage, seuil
0,80), par rang de l'horloge dans ``CLOCKS`` : sous-classe, segments, trop peu
représentée, ``E_R``, ``D_R``, ``E_R − L``."""


GEOMETRY = {
    'a-2026-06-03': ((-0.0145946089348079, 18), ((-0.01697048172341181, None, 7), (-0.008282996501864526, None, 1), (-0.011609336746652741, None, 7), (-0.014774859685512802, None, 3))),
    'b-2026-06-04': ((-0.0007894938846776329, 15), ((-0.0009337958804584386, None, 5), (-0.002446406583908682, None, 3), (9.815382806844879e-05, None, 6), (-3.819805921630553e-06, None, 1))),
    'a-2026-06-06': ((-0.01935953874537028, 18), ((-0.024835528175039878, None, 7), (-0.008968809695669275, None, 1), (-0.013146416624262839, None, 7), (-0.01732156372439983, None, 3))),
    'b-2026-06-08': ((0.0, 15), ((-1.1102230246251565e-16, None, 5), (4.440892098500625e-16, None, 3), (0.0, None, 6), (0.0, None, 1))),
    'a-2026-06-10': ((-0.014538524795923526, 16), ((-0.01751526821601935, None, 7), (-0.0078021483810334176, None, 1), (-0.010316925795106851, None, 5), (-0.012634144457044073, None, 3))),
    'a-2026-06-12': ((-0.01890316589833267, 18), ((-0.025065678746922424, None, 7), (-0.008617251698872957, None, 1), (-0.012080376345028673, None, 7), (-0.015908840977489673, None, 3))),
    'b-2026-06-12': ((-0.0017377242494399931, 15), ((-0.0016689475336249865, None, 5), (-0.004601980686745733, None, 3), (-0.0007774052322477359, None, 6), (-7.577045507538555e-05, None, 1))),
    'libre-2026-06-12': None,
    'a-2026-06-14': ((-0.012839983138462753, 18), ((-0.016819435087093586, None, 7), (-0.006592713890362026, None, 1), (-0.009268180128949808, None, 7), (-0.009036059330279213, None, 3))),
    'libre-2026-06-15': None,
    'b-2026-06-25': ((0.00015083361396151348, 15), ((0.0010091448006108383, None, 5), (-0.001057273075718617, None, 3), (-0.0007690957168191895, None, 6), (0.000543880059306644, None, 1))),
    'a-2026-06-27': ((-0.013956412944845667, 18), ((-0.01722689102732824, None, 7), (-0.00749426794807758, None, 1), (-0.010547632200275858, None, 7), (-0.012168467680441358, None, 3))),
}
"""Diagnostic de géométrie de chaque sortie scorée : ``G`` et son effectif, puis par
classe (valeur, motif, effectif) ; ``None`` sans usage."""


THIRD_CLOCK_NOT_ELAPSED = ('a-2026-06-06',)
"""Les sorties dont la troisième horloge n'est pas l'écoulé (un arrêt confirmé)."""
