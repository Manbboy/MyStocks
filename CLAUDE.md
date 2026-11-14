# Règles du projet « Mes actions »

- **Page d'aide** : `help.html` (onglet Help / « ? ») explique chaque méthode, indicateur et calcul avec ses vrais paramètres.
  À chaque modification d'un indicateur, d'un calcul ou d'un paramètre (index.html, scripts/update.py, scripts/tino.py,
  scripts/signals.py, worker/cours-live.js), mettre `help.html` à jour dans le même commit.
- Augmenter la version (`id="appVer">vNNN<` dans index.html) à chaque publication et annoncer le lien
  https://manbboy.github.io/MyStocks/ à l'utilisateur.
- Réponses en français ; l'appli s'utilise sur téléphone et tablette uniquement (pas d'infobulles au survol).
- Dépôt public : aucun secret dans le code (le jeton Telegram est un secret Cloudflare TG_TOKEN).
