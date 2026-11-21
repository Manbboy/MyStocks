# Règles du projet « Mes actions »

- **Page d'aide** : `help.html` (onglet Help / « ? ») explique chaque méthode, indicateur et calcul avec ses vrais paramètres.
  À chaque modification d'un indicateur, d'un calcul ou d'un paramètre (index.html, scripts/update.py, scripts/tino.py,
  scripts/signals.py, worker/cours-live.js), mettre `help.html` à jour dans le même commit.
- Augmenter la version (`id="appVer">vNNN<` dans index.html) à chaque publication et annoncer le lien
  https://manbboy.github.io/MyStocks/ à l'utilisateur.
  Toujours terminer la réponse par le lien, puis, juste en dessous et bien visible, la version en gras (ex. **v235**).
- Réponses en français ; l'appli s'utilise sur téléphone et tablette uniquement (pas d'infobulles au survol).
- Dépôt public : aucun secret dans le code (le jeton Telegram est un secret Cloudflare TG_TOKEN).
- Relais Cloudflare : tout changement dans `worker/` est déployé automatiquement par `.github/workflows/worker.yml`
  (secrets GitHub CLOUDFLARE_API_TOKEN et CLOUDFLARE_ACCOUNT_ID) ; ne plus demander de copier le code à la main.
