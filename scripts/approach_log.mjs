// Journal des « approches » pour la page Aujourd'hui : chaque soir, les valeurs proches d'une de vos zones,
// d'un support ou d'une résistance journaliers, ou juste sous la résistance Biarritz, sont notées avec la date de la séance.
// La page garde ainsi ces cartes 10 séances au lieu de les perdre le lendemain.
// Mêmes règles que la page : zone à 3 % ou moins ; support / résistance journaliers d'au moins 2 contacts à 1,5 % ou moins ;
// Biarritz à 1,5 % ou moins de la résistance.
// Usage : node scripts/approach_log.mjs   (depuis la racine du dépôt)
import fs from "node:fs";

const rd = (f, d) => { try { return JSON.parse(fs.readFileSync(f, "utf8")); } catch (e) { return d; } };
const summary = rd("data/summary.json", { symbols: {} });
const pf = rd("portfolios.json", { portfolios: [] });
const alerts = rd("alerts.json", { alerts: [] });
const zones = rd("zones.json", { zones: [] });
const bia = rd("data/biarritz.json", { wait: [] });
const OUT = "data/approaches.json";
const log = rd(OUT, { items: [] });

const S = summary.symbols || {};
const dates = Object.values(S).filter(v => v && v.date && v.type !== "CRYPTOCURRENCY").map(v => v.date).sort();
const day = dates[dates.length - 1];
if (!day) { console.log("Pas de date de séance."); process.exit(0); }

const mine = new Map();
(pf.portfolios || []).filter(p => p.name !== "Market").forEach(p => p.items.forEach(it => { if (!mine.has(it.yahoo)) mine.set(it.yahoo, it.name); }));

const today = [];
// vos zones (alertes de zone)
((alerts.alerts) || (Array.isArray(alerts) ? alerts : [])).filter(a => a.zone).forEach(a => {
  const i = S[a.sym]; if (!i || !i.last) return;
  const dist = Math.abs(a.price / i.last - 1); if (dist > 0.03) return;
  const z = (zones.zones || []).find(z => z.id === a.zone);
  today.push({ date: day, k: "zone", sym: a.sym, name: a.name || a.sym, cur: i.currency, close: i.last, lv: a.price, dist: +dist.toFixed(4),
    lo: z ? z.lo : a.price * 0.99, hi: z ? z.hi : a.price, note: a.note || "" });
});
// supports / résistances journaliers proches (au moins 2 contacts)
mine.forEach((name, sym) => {
  const i = S[sym]; if (!i || !i.levels || !i.levels.D || !i.last) return;
  const c = i.last, L = i.levels.D;
  const s = (L.supports || []).find(x => x.touches >= 2 && x.price < c && c / x.price - 1 <= 0.015);
  if (s) today.push({ date: day, k: "srn", side: "S", sym, name, cur: i.currency, close: c, lv: s.price, n: s.touches, dist: +(c / s.price - 1).toFixed(4) });
  const r = (L.resistances || []).find(x => x.touches >= 2 && x.price > c && x.price / c - 1 <= 0.015);
  if (r) today.push({ date: day, k: "srn", side: "R", sym, name, cur: i.currency, close: c, lv: r.price, n: r.touches, dist: +(r.price / c - 1).toFixed(4) });
});
// juste sous la résistance Biarritz
(bia.wait || []).filter(w => w.dist <= 0.015 && mine.has(w.sym)).forEach(w => today.push({ date: day, k: "biaw", sym: w.sym, name: w.name, cur: w.cur, close: w.C, lv: w.hi, lo: w.lo, n: w.n, dist: w.dist }));

// remplace la séance du jour, garde les 10 dernières séances
const items = (log.items || []).filter(x => x.date !== day).concat(today);
const keep = [...new Set(items.map(x => x.date))].sort().reverse().slice(0, 10);
const out = { updated: new Date().toISOString(), items: items.filter(x => keep.includes(x.date)) };
fs.writeFileSync(OUT, JSON.stringify(out));
console.log("Approches du " + day + " : " + today.length + " (journal : " + out.items.length + " sur " + keep.length + " séances)");
