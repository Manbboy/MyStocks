// Relais "cours-live" pour la page MyStocks (Cloudflare Worker, offre gratuite).
// Il va chercher les cours chez Yahoo Finance et les renvoie à votre page, qui ne peut pas les demander directement.
//
//   /quote?s=MC.PA,^FCHI,ES=F             -> dernier cours de chaque symbole
//   /chart?s=MC.PA&range=1d&interval=5m   -> bougies intraday d'un symbole
//   /tg/status | /tg/link | /tg/test      -> alertes Telegram : état, liaison avec votre conversation, message d'essai
//   /alerts/sent                          -> alertes déjà envoyées (pour les afficher dans la page)
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
    ctx.waitUntil(checkAlerts(env));
  },
};

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
  const [fr, en] = await Promise.all([q ? gnews(q).catch(() => []) : [], sym ? ynews(sym).catch(() => []) : []]);
  const pick = list => list.filter(n => n.time >= since && n.title).sort((a, b) => b.time - a.time).slice(0, 8);
  const res = json({ q, sym, fr: pick(fr), en: pick(en) }, 200, Object.assign({ "Cache-Control": "public, max-age=900" }, cors));   // 15 min
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
    const u = await tg(env, "getUpdates", { limit: 20 });
    if (!u.ok) return { error: u.error_code === 401 ? "Telegram refuse le jeton (TG_TOKEN) : il est sans doute ancien ou mal copié. Recopiez le jeton actuel de BotFather dans le secret TG_TOKEN." :
      u.error_code === 409 ? "Le bot a un webhook actif : envoyez /deleteWebhook n'est pas possible ici, dites-le à Claude." : "Telegram a refusé : " + (u.description || "erreur") };
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
  for (const sym of [...new Set(todo.map(a => a.sym))]) {
    const c = await chart(sym, "1d", "5m");
    if (c.error || !c.price) continue;
    for (const a of todo.filter(x => x.sym === sym)) {
      // franchi par le dernier cours, ou touché par une bougie de 5 min depuis la création de l'alerte (mèche entre deux vérifications)
      const after = (c.bars || []).filter(b => b[0] * 1000 >= (a.created || 0));
      const hit = a.op === "above" ? c.price >= a.price || after.some(b => b[2] >= a.price)
                                   : c.price <= a.price || after.some(b => b[3] <= a.price);
      if (!hit) continue;
      const chg = c.prevClose ? (c.price / c.prevClose - 1) * 100 : null;
      const text = "🔔 " + (a.name || sym) + " (" + sym + ")\n" +
        (a.op === "above" ? "▲ a franchi " : "▼ est passé sous ") + fmtN(a.price, c.currency) + (a.label ? " — " + a.label : "") + "\n" +
        "Cours : " + fmtN(c.price, c.currency) + (chg != null ? " (" + (chg >= 0 ? "+" : "") + chg.toFixed(2).replace(".", ",") + " % aujourd'hui)" : "") +
        (a.note ? "\n📝 " + a.note : "") + "\n" + SITE + "#sym=" + encodeURIComponent(sym);
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

function marketState(m) {
  const now = Date.now() / 1000, p = m.currentTradingPeriod.regular;
  return now >= p.start && now < p.end ? "ouvert" : "fermé";
}

function json(obj, status, headers) {
  return new Response(JSON.stringify(obj), { status, headers: Object.assign({ "Content-Type": "application/json; charset=utf-8" }, headers) });
}
