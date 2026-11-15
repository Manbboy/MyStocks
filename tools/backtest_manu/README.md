# Backtest de l'indicateur Manu

1. `node tools/backtest_manu/votes.mjs SU.PA TDG … > votes.json` : votes de tous les indicateurs (code d'index.html)
   à une date toutes les 15 séances sur ~4 ans, avec seulement les données connues à chaque date (mensuel rebâti depuis le journalier, Tino exclu).
2. `python3 tools/backtest_manu/evalm.py votes.json` : regroupement en zones (même règle que l'appli) et résultat 20 séances plus tard,
   comparé à des zones prises au hasard à la même distance du cours.

Résultats de novembre 2026 : voir la rubrique « Manu » de help.html.
3. `python3 tools/backtest_manu/filters.py` puis `robust.py` : filtres d'entrée (tendance, RSI, bougie, volume) et leur stabilité (votes dans va.json / vb.json à côté des scripts).
