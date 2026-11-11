
/* ===== Cours en séance (relais Cloudflare « cours-live », retard ≈ 15 min selon la bourse) ===== */
const LIVE_URL = "https://cours-live.manbboy.workers.dev";
const liveQuotes = {};      // sym -> { price, prevClose, time, day, state }
let liveTimer = null, liveLast = 0;
function liveOn() { return prefs.live !== false; }
function withLive(sym, info) {
  const q = liveQuotes[sym];
  if (!liveOn() || !q || !info || info.pending || info.error) return info;
  if (info.date && q.day < info.date) return info;   // la clôture connue est plus récente
  const pct = q.prevClose ? (q.price / q.prevClose - 1) * 100 : info.changePct;
  return Object.assign({}, info, { last:q.price, changePct:pct, date:q.day, live:q });
}
function liveDot(info) {
  const q = info.live, t = new Date(q.time * 1000).toLocaleTimeString("fr-FR", { hour:"2-digit", minute:"2-digit" });
  return '<span class="live-dot ' + (q.state === "ouvert" ? "on" : "off") + '" title="' + (q.state === "ouvert" ? "Séance en cours" : "Marché fermé") + " · cours de " + t + '"></span>';
}
async function pollLive(force) {
  if (!liveOn() || document.hidden) return;
  if (!force && Date.now() - liveLast < 55000) return;
  liveLast = Date.now();
  const pf = cfg.portfolios[prefs.active] || cfg.portfolios[0];
  const syms = new Set(pf.items.map(i => i.yahoo));
  if ($("ov").classList.contains("show") && cfg.portfolios[ovPos.pi]) { const it = cfg.portfolios[ovPos.pi].items[ovPos.idx]; if (it) syms.add(it.yahoo); }
  const list = [...syms];
  try {
    for (let k = 0; k < list.length; k += 40) {
      const r = await fetch(LIVE_URL + "/quote?s=" + encodeURIComponent(list.slice(k, k + 40).join(",")));
      if (!r.ok) throw new Error(r.status);
      const d = await r.json();
      (d.quotes || []).forEach(q => {
        if (q.error || q.price == null || !q.time) return;
        const day = new Date(q.time * 1000).toLocaleDateString("sv-SE", { timeZone: q.tz || "Europe/Paris" });
        liveQuotes[q.sym] = { price:q.price, prevClose:q.prevClose, time:q.time, day, state:q.state };
      });
    }
    setLiveStatus(true);
    refreshLiveCards();
    refreshDetailLive();
  } catch (e) { setLiveStatus(false); }
}
function setLiveStatus(ok) {
  const el = $("liveStatus"); if (!el) return;
  el.textContent = ok ? "● En séance · maj " + new Date().toLocaleTimeString("fr-FR", { hour:"2-digit", minute:"2-digit" }) : "○ Cours en séance indisponibles";
  el.className = "live-status " + (ok ? "ok" : "ko");
}
function refreshLiveCards() {
  document.querySelectorAll("#grid .card[data-sym]").forEach(card => {
    const sym = card.dataset.sym;
    const info = withLive(sym, summary.symbols[sym]); if (!info || !info.live) return;
    const pct = info.changePct;
    card.querySelector(".px").textContent = fmt(info.last, prefs.cols >= 4 ? null : info.currency);
    card.querySelector(".px2").textContent = fmt(info.last, null);
    const ch = card.querySelector(".chg"); ch.textContent = fmtPct(pct); ch.className = "chg " + (pct >= 0 ? "up" : "down");
    const nm = card.querySelector(".nm"); const old = nm.querySelector(".live-dot"); if (old) old.remove();
    nm.insertAdjacentHTML("afterbegin", liveDot(info));
  });
}
function startLive() {
  clearInterval(liveTimer);
  if (!liveOn()) return;
  pollLive(true);
  liveTimer = setInterval(() => pollLive(false), 60000);
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) pollLive(false); });

/* ----- Détail : chandeliers de 15 min et bougie du jour (à partir du relais) ----- */
// Les dates sont « AAAA-MM-JJ » ; les chandeliers 15 min ont un horodatage (secondes, heure de Bruxelles)
function dOf(d) { return typeof d === "number" ? new Date(d * 1000) : new Date(d + "T00:00:00Z"); }
function hasIntraday() { return !!(ovData && ovData.intraday && ovData.intraday.length > 5); }
function tzShift(t, tz) {             // décalage (s) entre UTC et le fuseau, à l'instant t
  const p = new Intl.DateTimeFormat("en-US", { timeZone:tz, hourCycle:"h23", year:"numeric", month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", second:"2-digit" })
    .formatToParts(new Date(t * 1000)).reduce((o, x) => (o[x.type] = x.value, o), {});
  return (Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second) / 1000) - t;
}
async function fetchIntraday(sym) {
  const ctl = new AbortController(); const to = setTimeout(() => ctl.abort(), 8000);
  try {
    const r = await fetch(LIVE_URL + "/chart?s=" + encodeURIComponent(sym) + "&range=5d&interval=15m", { signal:ctl.signal });
    if (!r.ok) return null;
    const d = await r.json();
    return d && d.bars && d.bars.length ? d : null;
  } catch (e) { return null; } finally { clearTimeout(to); }
}
async function withLiveData(sym, data) {
  if (!liveOn() || !data || !data.rows || !data.rows.length) return data;
  const c = await fetchIntraday(sym);
  if (!c) return data;
  const tz = c.tz || "Europe/Paris";
  const dayOf = t => new Date(t * 1000).toLocaleDateString("sv-SE", { timeZone:tz });
  const bars = c.bars.filter(b => b[1] != null && b[2] != null && b[3] != null);
  const intraday = bars.map(b => [b[0] + tzShift(b[0], "Europe/Brussels"), b[1], b[2], b[3], b[4], b[5] || 0]);
  // bougie du jour : séance la plus récente des chandeliers 15 min
  const lastDay = dayOf(bars[bars.length - 1][0]);
  const today = bars.filter(b => dayOf(b[0]) === lastDay);
  const out = Object.assign({}, data, { intraday, symbol:(data.symbol || sym) + "@" + bars[bars.length - 1][0] });
  if (today.length) {
    const cdl = [lastDay, today[0][1], Math.max(...today.map(b => b[2])), Math.min(...today.map(b => b[3])),
                 c.price != null ? c.price : today[today.length - 1][4], today.reduce((a, b) => a + (b[5] || 0), 0)];
    cdl[2] = Math.max(cdl[2], cdl[4]); cdl[3] = Math.min(cdl[3], cdl[4]);
    const rows = data.rows.slice(), lr = rows[rows.length - 1];
    if (lastDay > lr[0]) rows.push(cdl);
    else if (lastDay === lr[0]) rows[rows.length - 1] = [lr[0], lr[1], Math.max(lr[2], cdl[2]), Math.min(lr[3], cdl[3]), cdl[4], Math.max(lr[5] || 0, cdl[5])];
    out.rows = rows;
    if (data.long && data.long.length) {           // historique mensuel : met à jour le mois en cours
      const long = data.long.slice(), lm = long[long.length - 1], d = rows[rows.length - 1];
      if (d[0].slice(0, 7) === String(lm[0]).slice(0, 7)) long[long.length - 1] = [lm[0], lm[1], Math.max(lm[2], d[2]), Math.min(lm[3], d[3]), d[4], lm[5]];
      else if (d[0] > lm[0]) long.push(d.slice());
      out.long = long;
    }
  }
  return out;
}
// détail ouvert : met à jour la dernière bougie sans changer le cadrage
async function refreshDetailLive() {
  if (!$("ov").classList.contains("show") || !ovData || !ovSym || !ovCandles) return;
  if (typeof splitN === "function" && splitN() > 1) return;
  const base = await getSeries(summary.symbols[ovSym] || ovItem);
  const nd = await withLiveData(ovSym, base);
  if (!nd || nd === base || !ovCandles) return;
  const iv = prefs.iv || "D";
  const oldLen = barsFor(ovData, iv).length;
  ovData = nd;
  const rows = barsFor(ovData, iv);
  if (!rows.length || rows.length < oldLen) return;
  const cd = candleData(rows.slice(-Math.min(rows.length, 60)), false);
  try { ovCandles.update(cd[cd.length - 1]); } catch (e) {}
}
