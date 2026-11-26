// Relais "cours-live" pour la page MyStocks (Cloudflare Worker, offre gratuite).
// Il va chercher les cours chez Yahoo Finance et les renvoie à votre page, qui ne peut pas les demander directement.
//
//   /quote?s=MC.PA,^FCHI,ES=F             -> dernier cours de chaque symbole
//   /chart?s=MC.PA&range=1d&interval=5m   -> bougies intraday d'un symbole
//   /tg/status | /tg/link | /tg/test      -> alertes Telegram : état, liaison avec votre conversation, message d'essai
//   /alerts/sent                          -> alertes déjà envoyées (pour les afficher dans la page)
//   /find?q=airbus                        -> recherche de valeurs par nom ou ticker (moteur de Yahoo Finance)
//   /news?q=Renault&s=RNO.PA              -> actualités des 3 derniers jours : Google Actualités en français, puis Yahoo Finance (anglais)
//
// Alertes de prix : toutes les 5 minutes en semaine (déclencheur « crons » de wrangler.toml), le relais lit
// alerts.json dans le dépôt, vérifie les cours et envoie un message Telegram quand un niveau est franchi (une seule fois).
// Il faut : le secret TG_TOKEN (jeton du bot Telegram) et l'espace de stockage KV « ALERTS » (voir wrangler.toml).
//
// Seule votre page (manbboy.github.io) est autorisée à l'utiliser.

const ALLOWED = ["https://manbboy.github.io"];
const RANGES = ["1d", "5d", "1mo"];
const INTERVALS = ["1m", "2m", "5m", "15m", "30m", "60m"];

export default {
  async fetch(request, env, ctx) {
    const origin = request.headers.get("Origin") || "";
    const cors = {
      "Access-Control-Allow-Origin": ALLOWED.includes(origin) ? origin : ALLOWED[0],
      "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Vary": "Origin",
    };
    if (request.method === "OPTIONS") return new Response(null, { headers: cors });
    if (origin && !ALLOWED.includes(origin)) return new Response("Accès refusé", { status: 403, headers: cors });

    const url = new URL(request.url);
    if (url.pathname.startsWith("/tg/") || url.pathname === "/alerts/sent") return json(await tgRoute(url.pathname, env), 200, cors);
    if (url.pathname === "/news") return news(url, ctx, cors);
    if (url.pathname === "/find") return find(url, ctx, cors);
    const syms = (url.searchParams.get("s") || "").split(",").map(s => s.trim()).filter(Boolean).slice(0, 60);
    if (!syms.length) return json({ error: "paramètre s manquant" }, 400, cors);

    // petit cache de 60 s chez Cloudflare : plusieurs ouvertures de la page ne multiplient pas les appels à Yahoo
    const cache = caches.default;
    const key = new Request(url.toString(), { method: "GET" });
    const hit = await cache.match(key);
    if (hit) { const r = new Response(hit.body, hit); Object.entries(cors).forEach(([k, v]) => r.headers.set(k, v)); return r; }

    let body;
    if (url.pathname === "/chart") {
      const range = RANGES.includes(url.searchParams.get("range")) ? url.searchParams.get("range") : "1d";
      const interval = INTERVALS.includes(url.searchParams.get("interval")) ? url.searchParams.get("interval") : "5m";
      body = await chart(syms[0], range, interval);
    } else {
      const out = await Promise.all(syms.map(s => chart(s, "1d", "5m").then(c => c.error ? c : {
        sym: s, price: c.price, prevClose: c.prevClose, time: c.time, currency: c.currency, state: c.state,
      })));
      body = { quotes: out };
    }
    const res = json(body, 200, Object.assign({ "Cache-Control": "public, max-age=60" }, cors));
    ctx.waitUntil(cache.put(key, res.clone()));
    return res;
  },

  // vérification périodique des alertes
  async scheduled(event, env, ctx) {
    // 8 h 30 (Bruxelles) : résumé pré-ouverture Europe ; 9 h 00 (New York) : pré-ouverture Wall Street — à la place des alertes ce tour-là (budget de requêtes)
    const pre = await preOpen(env);
    if (!pre) ctx.waitUntil(checkAlerts(env));
  },
};

/* ===== Recherche de valeurs (moteur de Yahoo Finance) ===== */
async function find(url, ctx, cors) {
  const q = (url.searchParams.get("q") || "").trim().slice(0, 60);
  if (q.length < 2) return json({ quotes: [] }, 200, cors);
  const cache = caches.default, key = new Request("https://find.local/?q=" + encodeURIComponent(q.toLowerCase()));
  const hit = await cache.match(key);
  if (hit) { const r = new Response(hit.body, hit); Object.entries(cors).forEach(([k, v]) => r.headers.set(k, v)); return r; }
  let quotes = [];
  try {
    const r = await fetch("https://query2.finance.yahoo.com/v1/finance/search?q=" + encodeURIComponent(q) + "&quotesCount=12&newsCount=0&enableFuzzyQuery=true&lang=fr-FR&region=FR", { headers: UA });
    if (r.ok) {
      const j = await r.json();
      quotes = (j.quotes || []).filter(x => x.symbol && ["EQUITY", "ETF", "INDEX", "CRYPTOCURRENCY", "FUTURE", "MUTUALFUND"].includes(x.quoteType))
        .map(x => ({ s: x.symbol, n: x.longname || x.shortname || x.symbol, x: x.exchDisp || x.exchange || "", t: x.typeDisp || x.quoteType || "" }));
    }
  } catch (e) {}
  const res = json({ quotes }, 200, Object.assign({ "Cache-Control": "public, max-age=3600" }, cors));
  if (quotes.length) ctx.waitUntil(cache.put(key, res.clone()));
  return res;
}

/* ===== Actualités d'une valeur ===== */
const UA = { "User-Agent": "Mozilla/5.0 (compatible; MyStocks/1.0)" };
async function news(url, ctx, cors) {
  const q = (url.searchParams.get("q") || "").replace(/\s*\(.*?\)\s*/g, " ").trim().slice(0, 80);
  const sym = (url.searchParams.get("s") || "").trim().slice(0, 20);
  if (!q && !sym) return json({ error: "paramètre q ou s manquant" }, 400, cors);
  const cache = caches.default, key = new Request("https://cache.local/news?q=" + encodeURIComponent(q) + "&s=" + encodeURIComponent(sym));
  const hit = await cache.match(key);
  if (hit) { const r = new Response(hit.body, hit); Object.entries(cors).forEach(([k, v]) => r.headers.set(k, v)); return r; }
  const since = Date.now() - 3 * 864e5;
  // français : flux Yahoo Finance France du symbole (le plus fiable depuis le relais) + Google Actualités ; anglais : recherche Yahoo
  const [yfr, gfr, en] = await Promise.all([sym ? yrss(sym).catch(() => []) : [], q ? gnews(q).catch(() => []) : [], sym ? ynews(sym).catch(() => []) : []]);
  const seen = new Set(), fr = [];
  for (const n of yfr.concat(gfr)) { const k = n.title.toLowerCase().replace(/[^a-z0-9à-ÿ]+/g, " ").trim().slice(0, 60); if (!seen.has(k)) { seen.add(k); fr.push(n); } }
  const pick = list => list.filter(n => n.time >= since && n.title).sort((a, b) => b.time - a.time).slice(0, 8);
  const out = { q, sym, fr: pick(fr), en: pick(en) }, found = out.fr.length + out.en.length > 0;
  const res = json(out, 200, Object.assign({ "Cache-Control": "public, max-age=" + (found ? 900 : 120) }, cors));   // 15 min ; 2 min si rien (nouvel essai rapide)
  ctx.waitUntil(cache.put(key, res.clone()));
  return res;
}
function unxml(t) {
  return (t || "").replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1").replace(/<[^>]+>/g, "")
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;|&apos;/g, "'")
    .replace(/&#(\d+);/g, (_, n) => String.fromCharCode(+n)).replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").trim();
}
// Google Actualités (flux RSS), en français : le nom de la valeur, avec des mots de bourse pour éviter les homonymes
async function gnews(q) {
  const query = '"' + q + '" (bourse OR action OR titre OR cours OR résultats) when:3d';
  const r = await fetch("https://news.google.com/rss/search?q=" + encodeURIComponent(query) + "&hl=fr&gl=FR&ceid=FR:fr", { headers: UA });
  if (!r.ok) return [];
  const xml = await r.text(), out = [];
  for (const m of xml.matchAll(/<item>([\s\S]*?)<\/item>/g)) {
    const it = m[1], g = tag => { const x = it.match(new RegExp("<" + tag + "[^>]*>([\\s\\S]*?)</" + tag + ">")); return x ? unxml(x[1]) : ""; };
    const source = g("source");
    let title = g("title");
    if (source && title.endsWith(" - " + source)) title = title.slice(0, -(source.length + 3));
    out.push({ title, link: g("link"), source, time: Date.parse(g("pubDate")) || 0, lang: "fr" });
  }
  return out;
}
// Yahoo Finance France : flux RSS des actualités du symbole, en français (celles de la page « Actualités » de la valeur)
async function yrss(sym) {
  const r = await fetch("https://feeds.finance.yahoo.com/rss/2.0/headline?s=" + encodeURIComponent(sym) + "&region=FR&lang=fr-FR", { headers: UA });
  if (!r.ok) return [];
  const xml = await r.text(), out = [];
  for (const m of xml.matchAll(/<item>([\s\S]*?)<\/item>/g)) {
    const it = m[1], g = tag => { const x = it.match(new RegExp("<" + tag + "[^>]*>([\\s\\S]*?)</" + tag + ">")); return x ? unxml(x[1]) : ""; };
    const link = g("link"); let source = "Yahoo Finance";
    try { const h = new URL(link).hostname.replace(/^www\./, ""); if (!/yahoo\./.test(h)) source = h; } catch (e) {}
    out.push({ title: g("title"), link, source, time: Date.parse(g("pubDate")) || 0, lang: "fr" });
  }
  return out;
}
// Yahoo Finance : actualités liées au symbole (surtout en anglais)
async function ynews(sym) {
  const r = await fetch("https://query2.finance.yahoo.com/v1/finance/search?q=" + encodeURIComponent(sym) + "&quotesCount=0&newsCount=12&enableFuzzyQuery=false", { headers: UA });
  if (!r.ok) return [];
  const j = await r.json();
  return (j.news || []).filter(n => !n.relatedTickers || !n.relatedTickers.length || n.relatedTickers.includes(sym))
    .map(n => ({ title: n.title, link: n.link, source: n.publisher, time: (n.providerPublishTime || 0) * 1000, lang: "en" }));
}

/* ===== Alertes Telegram ===== */
const ALERTS_URL = "https://raw.githubusercontent.com/Manbboy/MyStocks/main/alerts.json";
const SITE = "https://manbboy.github.io/MyStocks/";

async function tg(env, method, body) {
  const r = await fetch(`https://api.telegram.org/bot${env.TG_TOKEN}/${method}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  return r.json();
}

async function tgRoute(path, env) {
  const ready = { token: !!env.TG_TOKEN, kv: !!env.ALERTS };
  const chat = env.ALERTS ? await env.ALERTS.get("tg:chat") : null;
  if (path === "/alerts/sent") return { sent: env.ALERTS ? JSON.parse(await env.ALERTS.get("sent") || "{}") : {} };
  if (path === "/tg/status") return Object.assign(ready, { chat: !!chat });
  if (!ready.token) return { error: "Le secret TG_TOKEN n'est pas encore configuré dans Cloudflare." };
  if (!ready.kv) return { error: "L'espace de stockage ALERTS n'est pas encore relié au relais." };
  if (path === "/tg/link") {
    // la conversation du dernier message reçu par le bot (après avoir touché « Démarrer » dans Telegram)
    let u = await tg(env, "getUpdates", { limit: 20 });
    if (!u.ok && u.error_code === 409) { await tg(env, "deleteWebhook", {}); u = await tg(env, "getUpdates", { limit: 20 }); }   // webhook actif : on le retire
    if (!u.ok) return { error: u.error_code === 401 ? "Telegram refuse le jeton (TG_TOKEN) : il est sans doute ancien ou mal copié. Recopiez le jeton actuel de BotFather dans le secret TG_TOKEN."
      : "Telegram a refusé : " + (u.description || "erreur") };
    const msgs = (u.result || []).map(x => x.message || x.edited_message).filter(Boolean);
    const last = msgs[msgs.length - 1];
    if (!last) return { error: "Aucun message reçu par le bot : ouvrez-le dans Telegram, touchez « Démarrer » (ou envoyez-lui « bonjour »), puis réessayez." };
    await env.ALERTS.put("tg:chat", String(last.chat.id));
    await tg(env, "sendMessage", { chat_id: last.chat.id, text: "✅ Mes actions est relié à cette conversation. Les alertes de prix arriveront ici." });
    return { ok: true, name: last.chat.first_name || last.chat.title || "" };
  }
  if (path === "/tg/test") {
    if (!chat) return { error: "Telegram n'est pas encore relié (bouton « Relier »)." };
    const r = await tg(env, "sendMessage", { chat_id: chat, text: "🔔 Message d'essai de Mes actions : les alertes fonctionnent." });
    return r.ok ? { ok: true } : { error: "Telegram a refusé : " + (r.description || "erreur") };
  }
  return { error: "inconnu" };
}

const fmtN = (v, cur) => v.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: v < 10 ? 4 : 2 }) + (cur === "EUR" ? " €" : cur === "USD" ? " $" : "");

async function checkAlerts(env) {
  if (!env.TG_TOKEN || !env.ALERTS) return;
  const chat = await env.ALERTS.get("tg:chat"); if (!chat) return;
  let list;
  try { list = (await (await fetch(ALERTS_URL + "?t=" + Date.now(), { cf: { cacheTtl: 0 } })).json()).alerts || []; } catch (e) { return; }
  const sent = JSON.parse(await env.ALERTS.get("sent") || "{}");
  const todo = list.filter(a => a && a.id && !sent[a.id] && a.sym && a.price > 0);
  if (!todo.length) return;
  let changed = false;
  // budget du plan gratuit : ~50 requêtes par vérification (1 pour la liste, 1 par valeur, 1 par message envoyé).
  // Priorité : 1) alertes manuelles  2) mes zones  3) Biarritz  4) R⇄S automatiques ; au-delà, vérifiées au tour suivant.
  const rank = a => a.bia ? 2 : a.auto ? 3 : a.zone ? 1 : 0;   // 0 manuelles, 1 zones, 2 Biarritz, 3 R⇄S auto
  const best = {};
  todo.forEach(a => { best[a.sym] = Math.min(best[a.sym] ?? 9, rank(a)); });
  const syms = Object.keys(best).sort((x, y) => best[x] - best[y]);
  let used = 1;                                       // lecture de alerts.json
  for (const sym of syms) {
    if (used >= 46) break;                            // garder de la place pour les messages Telegram
    used++;
    const c = await chart(sym, "1d", "5m");
    if (c.error || !c.price) continue;
    for (const a of todo.filter(x => x.sym === sym)) {
      // franchi par le dernier cours, ou touché par une bougie de 5 min depuis la création de l'alerte (mèche entre deux vérifications)
      const after = (c.bars || []).filter(b => b[0] * 1000 >= (a.created || 0));
      const hit = a.op === "above" ? c.price >= a.price || after.some(b => b[2] >= a.price)
                                   : c.price <= a.price || after.some(b => b[3] <= a.price);
      if (!hit) continue;
      const chg = c.prevClose ? (c.price / c.prevClose - 1) * 100 : null;
      // une ligne vide entre chaque information : plus lisible sur le téléphone
      // 1) nom · cours · variation du jour  2) le motif (Biarritz, R→S, zone…)  3) ce qui s'est passé (franchi / passé sous)
      const text = [
        (a.zone ? "🟨 " : a.bia ? "🏄 " : "🔔 ") + (a.name || sym) + " · " + fmtN(c.price, c.currency) +
          (chg != null ? " · " + (chg >= 0 ? "+" : "") + chg.toFixed(2).replace(".", ",") + " % auj." : ""),
        a.label || null,
        (a.op === "above" ? "▲ a franchi " : "▼ est passé sous ") + fmtN(a.price, c.currency),
        a.note ? "📝 " + a.note : null,
        SITE + "#sym=" + encodeURIComponent(sym),
      ].filter(Boolean).join("\n\n");
      if (used >= 49) break;                          // plus de place : ce message partira au tour suivant
      used++;
      const r = await tg(env, "sendMessage", { chat_id: chat, text, disable_web_page_preview: true });
      if (r.ok) { sent[a.id] = Date.now(); changed = true; }
    }
  }
  if (changed) await env.ALERTS.put("sent", JSON.stringify(sent));
}

async function chart(sym, range, interval) {
  try {
    const r = await fetch(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?range=${range}&interval=${interval}&includePrePost=false`,
      { headers: { "User-Agent": "Mozilla/5.0" } });
    if (!r.ok) return { sym, error: "Yahoo " + r.status };
    const d = await r.json();
    const res = d.chart && d.chart.result && d.chart.result[0];
    if (!res) return { sym, error: "aucune donnée" };
    const m = res.meta, q = (res.indicators.quote || [])[0] || {};
    const bars = (res.timestamp || []).map((t, i) => [t, q.open[i], q.high[i], q.low[i], q.close[i], q.volume[i]])
      .filter(b => b[4] != null);
    return {
      sym, price: m.regularMarketPrice, prevClose: m.chartPreviousClose ?? m.previousClose,
      time: m.regularMarketTime, currency: m.currency, tz: m.exchangeTimezoneName,
      state: m.currentTradingPeriod ? marketState(m) : null, bars,
    };
  } catch (e) {
    return { sym, error: String(e) };
  }
}

/* ===== Résumés de pré-ouverture (Telegram), une fois par jour de semaine ===== */
const HOLD_URL = "https://raw.githubusercontent.com/Manbboy/MyStocks/main/portfolios.json";
function zoned(tz) {
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-GB", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", weekday: "short", hour12: false })
    .formatToParts(new Date()).map(x => [x.type, x.value]));
  return { day: p.year + "-" + p.month + "-" + p.day, h: +p.hour % 24, m: +p.minute, wd: p.weekday };
}
const pct = v => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2).replace(".", ",") + " %";
const num = v => v.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const esc = t => String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const cut = (t, n) => (t.length > n ? t.slice(0, n - 1) + "." : t).padEnd(n);
async function preOpen(env) {
  if (!env.TG_TOKEN || !env.ALERTS) return false;
  const bx = zoned("Europe/Brussels"), ny = zoned("America/New_York");
  if (["Sat", "Sun"].includes(bx.wd)) return false;
  const force = await env.ALERTS.get("pre:force");                 // essai manuel : "eu" ou "us"
  let kind = null;
  if (bx.h === 8 && bx.m >= 30 && bx.m < 45) kind = "eu";
  else if (ny.h === 9 && ny.m < 15) kind = "us";
  if (force) { kind = force; await env.ALERTS.delete("pre:force"); }
  if (!kind) return false;
  const flag = "pre:" + kind + ":" + bx.day;
  if (!force && await env.ALERTS.get(flag)) return false;
  const chat = await env.ALERTS.get("tg:chat"); if (!chat) return false;
  let hold = [];
  try { hold = ((await (await fetch(HOLD_URL + "?t=" + Date.now())).json()).portfolios || []).find(p => p.name === "Hold").items || []; } catch (e) { return false; }
  const text = kind === "eu" ? await preEU(env, hold, bx) : await preUS(hold, bx, ny);
  const r = await tg(env, "sendMessage", { chat_id: chat, text, parse_mode: "HTML", disable_web_page_preview: true });
  if (r.ok) await env.ALERTS.put(flag, "1", { expirationTtl: 3 * 86400 });
  return true;
}
const DAYS = { Mon: "lun.", Tue: "mar.", Wed: "mer.", Thu: "jeu.", Fri: "ven." };
const dLbl = bx => DAYS[bx.wd] + " " + bx.day.slice(8) + "/" + bx.day.slice(5, 7);
// ticker allemand (Stuttgart, sinon Francfort) d'une action européenne, trouvé une fois via la recherche Yahoo puis gardé
async function deTicker(env, it) {
  if (/\.(SG|F|DE|MU|DU|BE|HM)$/.test(it.yahoo) && !/\.DE$/.test(it.yahoo)) return it.yahoo;
  const k = "de:" + it.yahoo, got = await env.ALERTS.get(k);
  if (got !== null) return got || null;
  let best = "";
  try {
    const j = await (await fetch("https://query2.finance.yahoo.com/v1/finance/search?q=" + encodeURIComponent(it.name) + "&quotesCount=20&newsCount=0", { headers: UA })).json();
    const q = (j.quotes || []).filter(x => x.quoteType === "EQUITY" || x.quoteType === "ETF");
    best = (q.find(x => x.exchange === "STU") || q.find(x => x.exchange === "FRA") || {}).symbol || "";
  } catch (e) {}
  await env.ALERTS.put(k, best, { expirationTtl: 30 * 86400 });
  return best || null;
}
async function preEU(env, hold, bx) {
  const eu = hold.filter(i => /\.(PA|AS|BR|DE|MI|MC|SG|F)$/.test(i.yahoo));
  const rows = []; let sum = 0, n = 0;
  for (const it of eu) {
    const de = await deTicker(env, it);
    const [ref, q] = await Promise.all([chart(it.yahoo, "5d", "1d"), de ? chart(de, "1d", "5m") : null]);
    // clôture de référence : dernière bougie journalière d'avant aujourd'hui (Paris, ou la place suivie)
    const pb = ref && !ref.error ? ref.bars.filter(b => zonedTs(b[0]) < bx.day) : [];
    const close = pb.length ? pb[pb.length - 1][4] : null;
    const today = q && !q.error && q.time && zonedTs(q.time) === bx.day;
    if (today && close) {
      const v = (q.price / close - 1) * 100; sum += v; n++;
      rows.push(cut(it.name, 12) + " " + num(q.price).padStart(8) + " " + pct(v).padStart(8) + "  " + new Date(q.time * 1000).toLocaleTimeString("fr-BE", { timeZone: "Europe/Brussels", hour: "2-digit", minute: "2-digit" }));
    } else rows.push(cut(it.name, 12) + "        —  pas d'échange");
  }
  return "☀️ <b>PRÉ-OUVERTURE EUROPE</b>\n" + dLbl(bx) + " · 08:30 · Paris ouvre à 9 h\n" +
    "<pre>" + esc(["━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", ...rows, "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"].join("\n")) + "</pre>" +
    eu.length + " valeurs · " + n + " échangées" + (n ? " · tendance " + pct(sum / n) : "") +
    "\n<i>Cours allemands (Stuttgart / Francfort) vs clôture de la veille, indicatifs : peu de volume avant 9 h.</i>";
}
function zonedTs(t) { const p = Object.fromEntries(new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Brussels", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date(t * 1000)).map(x => [x.type, x.value])); return p.year + "-" + p.month + "-" + p.day; }
async function prePost(sym) {        // dernier cours du pré-marché américain (bougies 1 min, heures étendues comprises)
  try {
    const d = await (await fetch(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?range=1d&interval=1m&includePrePost=true`, { headers: UA })).json();
    const r = d.chart.result[0], m = r.meta, ts = r.timestamp || [], cl = (r.indicators.quote[0] || {}).close || [];
    let i = cl.length - 1; while (i >= 0 && cl[i] == null) i--;
    const reg = m.currentTradingPeriod && m.currentTradingPeriod.regular;
    const fresh = i >= 0 && (!reg || ts[i] < reg.start) && ts[i] > Date.now() / 1000 - 6 * 3600;
    return { price: fresh ? cl[i] : null, prev: m.regularMarketPrice ?? m.chartPreviousClose, fut: null };
  } catch (e) { return { price: null }; }
}
async function preUS(hold, bx, ny) {
  const fut = [["S&P 500 fut.", "ES=F"], ["Nasdaq fut.", "NQ=F"], ["Dow Jones fut.", "YM=F"]];
  const top = [];
  for (const [n, s] of fut) { const c = await chart(s, "5d", "1d");
    top.push(cut(n, 14) + (c && !c.error && c.price ? num(c.price).padStart(10) + " " + pct((c.price / (c.bars.length > 1 ? c.bars[c.bars.length - 2][4] : c.prevClose) - 1) * 100).padStart(8) : "         —")); }
  const us = hold.filter(i => !/[.\-=^]/.test(i.yahoo));
  const rows = [];
  for (const it of us) { const q = await prePost(it.yahoo);
    rows.push(cut(it.name, 14) + (q.price && q.prev ? num(q.price).padStart(10) + " " + pct((q.price / q.prev - 1) * 100).padStart(8) : "         —  pas d'échange")); }
  return "🌎 <b>PRÉ-OUVERTURE WALL STREET</b>\n" + dLbl(bx) + " · ouverture dans 30 min\n" +
    "<pre>" + esc(["━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", ...top, "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", ...rows, "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"].join("\n")) + "</pre>" +
    "<i>Pré-marché (et contrats à terme), variation vs clôture d'hier.</i>";
}

function marketState(m) {
  const now = Date.now() / 1000, p = m.currentTradingPeriod.regular;
  return now >= p.start && now < p.end ? "ouvert" : "fermé";
}

function json(obj, status, headers) {
  return new Response(JSON.stringify(obj), { status, headers: Object.assign({ "Content-Type": "application/json; charset=utf-8" }, headers) });
}
// relance du déploiement
