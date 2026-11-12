// Relais "cours-live" pour la page MyStocks (Cloudflare Worker, offre gratuite).
// Il va chercher les cours chez Yahoo Finance et les renvoie à votre page, qui ne peut pas les demander directement.
//
//   /quote?s=MC.PA,^FCHI,ES=F             -> dernier cours de chaque symbole
//   /chart?s=MC.PA&range=1d&interval=5m   -> bougies intraday d'un symbole
//   /tg/status | /tg/link | /tg/test      -> alertes Telegram : état, liaison avec votre conversation, message d'essai
//   /alerts/sent                          -> alertes déjà envoyées (pour les afficher dans la page)
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
