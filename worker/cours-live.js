// Relais "cours-live" pour la page MyStocks (Cloudflare Worker, offre gratuite).
// Il va chercher les cours chez Yahoo Finance et les renvoie à votre page, qui ne peut pas les demander directement.
//
//   /quote?s=MC.PA,^FCHI,ES=F             -> dernier cours de chaque symbole
//   /chart?s=MC.PA&range=1d&interval=5m   -> bougies intraday d'un symbole
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
};

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
