# Calibrage de l'indicateur « Tino »

- `gt.py` : zones lues sur les analyses mensuelles de Tino (Le Podcast de la Bourse, 19–26/11/2026), une entrée par valeur.
- `monthly.json` : bougies mensuelles Yahoo (cours non ajustés des dividendes) de ces valeurs, au 25/11/2026.
- `cal.py` : compare `scripts/tino.py` à ces zones — `python3 tools/tino_cal/cal.py`.
  - *near* : notre 1re zone de soutien correspond à la zone de soutien la plus proche tracée par Tino ;
  - *recall* : part des zones de Tino retrouvées ; *prec* : part de nos zones qui correspondent à une zone de Tino.
  - « correspond » = centres proches (3 %) et largeur au plus 2 × celle de Tino (ou 10 %).

Résultat : ancien réglage near 8 %, recall 22 %, prec 16 % → réglage du 26/11/2026 near 40 %, recall 51 %, prec 37 %.
Écarts restants : Alstom et Nexity (ProRealTime ajuste l'historique des dividendes et opérations sur capital, Yahoo non),
et les zones de congestion récentes (Nvidia) faites de peu de sommets / creux marqués.
