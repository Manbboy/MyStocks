// Backtest Manu : votes de tous les indicateurs (code d'index.html) à des dates passées, sans données futures
import fs from "fs";
const ROOT = new URL("../../", import.meta.url).pathname;   // racine du dépôt
const html = fs.readFileSync(ROOT + "index.html", "utf8");
function grab(tok) {
  const i = html.indexOf(tok); if (i < 0) throw new Error("introuvable " + tok);
  let k = html.indexOf("{", i), d = 0;
  for (; k < html.length; k++) { if (html[k] === "{") d++; else if (html[k] === "}" && --d === 0) break; }
  return html.slice(i, k + 1) + (tok.startsWith("const") ? ";" : "");
}
let manu = grab("function manuCompute(").replace("  // regroupement : votes", "  globalThis.__votes = votes; if (globalThis.__onlyVotes) return null;\n  // regroupement : votes");
const src = [
  "const prefs = {}; const NUM_LOC='de-DE'; const CUR={}; const summary={symbols:{}};",
  grab("function fmt("), grab("function fmtPct("),
  grab("function dOf("), grab("function keyOf("), grab("function aggregate("), "const barsCache = {};", grab("function barsFor("),
  'const LV_ORDER = ["D","W","M","Q"];', grab("const TF_PARAMS = {"), grab("function computeLevels("),
  "const tolPct = () => 2;",
  grab("const FLIP_PARAMS = {"), "const FLIP_MAX = 6;", grab("function flipLevels("),
  grab("const GEO_PARAMS = {"), grab("function geoPivots("), grab("function trendLines("), grab("function channels("),
  grab("const TREND = {"), grab("function rsiValues("), grab("function trendStates("),
  "const MANU_H = 20;", grab("const MANU_W = {"), grab("function smaLast("), manu,
  "return { manuCompute, barsCache };"].join("\n");
const { manuCompute, barsCache } = new Function(src)();
globalThis.__onlyVotes = true;

const syms = process.argv.slice(2);
const STEP = 15, SPAN = 1000;              // une date toutes les 10 séances sur les ~5 dernières années
const out = [];
for (const sym of syms) {
  const f = ROOT + "data/series/" + sym.replace(/[.^=]/g, "_") + ".json";
  if (!fs.existsSync(f)) { console.error("absent", sym); continue; }
  const d = JSON.parse(fs.readFileSync(f, "utf8")), rows = d.rows;
  const t0 = Math.max(800, rows.length - SPAN);
  for (let t = t0; t < rows.length - 30; t += STEP) {
    for (const k in barsCache) delete barsCache[k];
    const data = { symbol: sym + "@" + t, rows: rows.slice(0, t + 1), long: [] };   // mensuel / trimestriel rebâtis depuis le journalier : pas de futur
    globalThis.__votes = null;
    try { manuCompute(data, {}, sym); } catch (e) { console.error(sym, t, e.message); continue; }
    const C = rows[t][4];
    out.push({ sym, t, date: rows[t][0], C, votes: (globalThis.__votes || []).filter(v => v.mid > C * 0.82 && v.mid < C * 1.10).map(v => [+v.lo.toFixed(4), +v.hi.toFixed(4), +v.w.toFixed(3), v.fam, v.txt]) });
  }
  console.error(sym, "ok");
}
process.stdout.write(JSON.stringify(out));
