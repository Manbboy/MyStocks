// Indicateur Biarritz sur toutes les valeurs suivies (sauf Market), calculé chaque soir avec le code même de l'appli :
// cassures récentes (5 dernières séances) et valeurs « au repos » sous leur résistance. → data/biarritz.json
// Usage : node scripts/bia_list.mjs   (depuis la racine du dépôt)
import fs from "fs";
const html = fs.readFileSync("index.html", "utf8");
function grab(tok) { const a = html.indexOf(tok); if (a < 0) throw new Error(tok); let i = html.indexOf("{", a), d = 0;
  for (; i < html.length; i++) { if (html[i] === "{") d++; else if (html[i] === "}") { d--; if (!d) break; } } return html.slice(a, i + 1) + (tok.startsWith("const") ? ";" : ""); }
const { biaCompute, BIA } = new Function([grab("function dOf("), grab("const BIA = {"), grab("function biaCompute("), "return { biaCompute, BIA };"].join("\n"))();
const summary = JSON.parse(fs.readFileSync("data/summary.json", "utf8"));
const pf = JSON.parse(fs.readFileSync("portfolios.json", "utf8")).portfolios;
const seen = new Set(), go = [], wait = [];
const r4 = v => Math.round(v * 10000) / 10000;
pf.filter(p => !/market/i.test(p.name)).forEach(p => p.items.forEach(it => {
  if (seen.has(it.yahoo)) return; seen.add(it.yahoo);
  const s = summary.symbols[it.yahoo]; if (!s || !s.file) return;
  let rows; try { rows = JSON.parse(fs.readFileSync("data/" + s.file, "utf8")).rows || []; } catch (e) { return; }
  const B = biaCompute(rows); if (!B) return;
  const n = B.n, up = B.mid[n - 1] + BIA.K * B.sd[n - 1], base = { sym: it.yahoo, name: it.name || it.yahoo, cur: s.currency, C: r4(B.C), mid: r4(B.mid[n - 1]), up: r4(up) };
  if (B.st.k === "go") { const g = B.sig[B.sig.length - 1]; go.push(Object.assign(base, { date: g.t, price: r4(g.price), res: r4(g.R.hi), n: g.R.n })); }
  else if (B.st.k === "wait" && B.R) wait.push(Object.assign(base, { lo: r4(B.R.lo), hi: r4(B.R.hi), n: B.R.n, dist: r4(B.R.hi / B.C - 1) }));
}));
go.sort((a, b) => b.date.localeCompare(a.date)); wait.sort((a, b) => a.dist - b.dist);
fs.writeFileSync("data/biarritz.json", JSON.stringify({ updated: summary.updated, go, wait }) + "\n");
console.log(`Biarritz : ${go.length} cassures récentes, ${wait.length} au repos`);
