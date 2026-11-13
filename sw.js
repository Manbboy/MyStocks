// Service worker minimal : rend l'appli installable (écran d'accueil, plein écran). Pas de cache : tout vient du réseau.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
