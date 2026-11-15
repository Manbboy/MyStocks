// Liste des meilleures confluences Manu (onglet « À regarder ») : data/confluences.json, recalculée chaque soir.
// Même calcul que le bouton M de l'appli (fonctions extraites d'index.html), Tino compris (data/summary.json).
// Usage : node scripts/manu_list.mjs   (depuis la racine du dépôt)
import fs from "fs";
const html = fs.readFileSync("index.html", "utf8");
function grab(tok) {
  const i = html.indexOf(tok); if (i < 0) throw new Error("introuvable dans index.html : " + tok);
  let k = html.indexOf("{", i), d = 0;
  for (; k < html.length; k++) { if (html[k] === "{") d++; else if (html[k] === "}" && --d === 0) break; }
  return html.slice(i, k + 1) + (tok.startsWith("const") ? ";" : "");
}
const summary = JSON.parse(fs.readFileSync("data/summary.json", "utf8"));
const src = [
  "const prefs = {}; const NUM_LOC = 'de-DE';", grab("const CUR = {"),
  grab("function fmt("), grab("function fmtPct("),
  grab("function dOf("), grab("function keyOf("), grab("function aggregate("), "const barsCache = {};", grab("function barsFor("),
  'const LV_ORDER = ["D","W","M","Q"];', grab("const TF_PARAMS = {"), grab("function computeLevels("), "const tolPct = () => 2;",
  grab("const FLIP_PARAMS = {"), "const FLIP_MAX = 6;", grab("function flipLevels("),
  grab("const GEO_PARAMS = {"), grab("function geoPivots("), grab("function trendLines("), grab("function channels("),
  grab("const TREND = {"), grab("function rsiValues("), grab("function trendStates("),
  "const MANU_H = 20;", grab("const MANU_W = {"), grab("function smaLast("), grab("function manuCompute("),
  "return { manuCompute };"].join("\n");
const { manuCompute } = new Function("summary", src)(summary);

const pf = JSON.parse(fs.readFileSync("portfolios.json", "utf8")).portfolios;
const items = new Map();
pf.filter(p => !/market/i.test(p.name)).forEach(p => p.items.forEach(it => { if (!items.has(it.yahoo)) items.set(it.yahoo, it); }));
const out = [];
for (const [sym, it] of items) {
  const s = summary.symbols[sym]; if (!s || !s.file) continue;
  let data; try { data = JSON.parse(fs.readFileSync("data/" + s.file, "utf8")); } catch (e) { continue; }
  let M; try { M = manuCompute(Object.assign({ symbol: sym }, data), { currency: s.currency }, sym); } catch (e) { console.error(sym, e.message); continue; }
  if (!M) continue;
  const trend = M.m200 != null && M.C > M.m200 && M.m50 > M.m200;
  M.zones.forEach(z => out.push({ sym, name: it.name || sym, cur: s.currency, C: M.C, lo: +z.lo.toFixed(4), hi: +z.hi.toFixed(4), score: +z.score.toFixed(2),
    side: z.side, dist: +(((z.lo + z.hi) / 2) / M.C - 1).toFixed(4), n: z.v.length, fams: z.fams, trend, rsi: Math.round(M.rsi),
    why: z.v.slice().sort((a, b) => b.w - a.w).slice(0, 4).map(v => [v.tf || "", v.txt]) }));
}
out.sort((a, b) => b.score - a.score);
fs.writeFileSync("data/confluences.json", JSON.stringify({ updated: new Date().toISOString().slice(0, 16) + "+00:00", zones: out }) + "\n");
console.log("confluences :", out.length, "zones ;", out.slice(0, 5).map(z => z.name + " " + z.score).join(" · "));
