# Mes actions

Page personnelle de suivi d'actions avec supports et résistances calculés automatiquement.

- `portfolios.json` : tes portefeuilles et tes actions (à modifier pour ajouter/retirer des valeurs)
- `index.html` : la page
- `scripts/update.py` : récupère les cours (Yahoo Finance) et calcule les niveaux
- `.github/workflows/update.yml` : lance la mise à jour automatiquement chaque jour de bourse
- `data/` : données générées automatiquement (ne pas modifier à la main)

## Ajouter une action

Ouvre `portfolios.json` sur GitHub, clique sur le crayon, ajoute une ligne comme :

```json
{ "yahoo": "AI.PA", "tv": "EURONEXT:AI", "name": "Air Liquide" },
```

`yahoo` = symbole Yahoo Finance (suffixe `.PA` Paris, `.BR` Bruxelles, `.AS` Amsterdam, `.DE` Xetra, `.MI` Milan, rien pour les US).
`tv` = symbole TradingView (pour le lien « Voir en direct »).

Enregistre (« Commit changes ») : la mise à jour se relance toute seule et la page est à jour quelques minutes plus tard.
