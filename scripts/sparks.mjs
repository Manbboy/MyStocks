// Mini-graphiques des listes (nouvelle interface) : 30 dernières clôtures de chaque valeur → data/sparks.json (petit fichier, un seul téléchargement)
// Usage : node scripts/sparks.mjs   (depuis la racine du dépôt)
import fs from "fs";
const summary = JSON.parse(fs.readFileSync("data/summary.json", "utf8")), out = {};
for (const [sym, s] of Object.entries(summary.symbols)) {
  if (!s.file) continue;
  try { const rows = JSON.parse(fs.readFileSync("data/" + s.file, "utf8")).rows || [];
    out[sym] = rows.slice(-30).map(r => +(+r[4]).toPrecision(6)); } catch (e) {}
}
fs.writeFileSync("data/sparks.json", JSON.stringify({ updated: summary.updated, s: out }) + "\n");
console.log("sparks :", Object.keys(out).length, "valeurs");
