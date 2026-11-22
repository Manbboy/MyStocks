// Situations R⇄S pour l'onglet « À regarder » (data/flips.json), recalculées chaque soir après la mise à jour des cours.
//
// Les niveaux sont ceux de l'appli : fonctions extraites d'index.html (bascules de rôle, précision 2 %, unités J et S).
// On prend les niveaux connus juste avant la fenêtre récente (5 séances en J, 2 semaines en S), puis on regarde ce que
// le cours a fait depuis :
//   R→S (ancienne résistance devenue support, sous le cours) :
//       rs_contact  : le cours est venu au contact du support (plus bas dans la zone) et a tenu à la clôture — réaction à surveiller
//       rs_reaction : après ce contact, une clôture au-dessus du plus haut de la bougie de contact — le support a réagi
//   S→R (ancien support devenu résistance, au-dessus du cours) :
//       sr_test     : le cours vient tester la résistance par le dessous (plus haut dans la zone) sans clôturer au-delà
//       sr_franchie : clôture nettement au-dessus de la résistance — elle est passée
// Usage : node scripts/flip_signals.mjs   (depuis la racine du dépôt)
import fs from "fs";

const html = fs.readFileSync("index.html", "utf8");
function grab(startToken) {                       // fonction ou constante d'index.html (accolades équilibrées)
  const i = html.indexOf(startToken);
  if (i < 0) throw new Error("introuvable dans index.html : " + startToken);
  let k = html.indexOf("{", i), depth = 0;
  for (; k < html.length; k++) { if (html[k] === "{") depth++; else if (html[k] === "}" && --depth === 0) break; }
  return html.slice(i, k + 1) + (startToken.startsWith("const") ? ";" : "");
}
const { aggregate, flipLevels } = new Function([
  grab("function dOf("), grab("function keyOf("), grab("function aggregate("),
  grab("const FLIP_PARAMS = {"), "const FLIP_MAX = 6;", grab("function flipLevels("),
  "return { aggregate, flipLevels };"].join("\n"))();

const PCT = 2, TOL = PCT / 100;                    // précision des contacts par défaut de l'appli
const WIN = { D: 5, W: 2 };                        // fenêtre récente (chandeliers)
const MAX_AGE = { rs_reaction: 9, sr_franchie: 9, rs_contact: 1, sr_test: 1 };   // confirmations : 10 séances (Signaux en montre 5, Aujourd'hui 10) ; à surveiller : 2
const r4 = v => Math.round(v * 10000) / 10000;

const summary = JSON.parse(fs.readFileSync("data/summary.json", "utf8"));
const pf = JSON.parse(fs.readFileSync("portfolios.json", "utf8")).portfolios;
const syms = new Set();
pf.filter(p => !/market/i.test(p.name)).forEach(p => p.items.forEach(it => syms.add(it.yahoo)));

const items = [];
for (const sym of syms) {
  const s = summary.symbols[sym];
  if (!s || !s.file) continue;
  let data;
  try { data = JSON.parse(fs.readFileSync("data/" + s.file, "utf8")); } catch (e) { continue; }
  const day = data.rows || [];
  if (day.length < 80) continue;
  const last = day[day.length - 1][4];
  const found = [];
  for (const tf of ["W", "D"]) {
    const rows = aggregate(day, tf), n = rows.length, m = WIN[tf];
    if (n < 60 + m) continue;
    // âge en séances (et date de la séance) d'un chandelier : dernière séance de la semaine pour S
    const sess = k => {
      if (tf === "D") return { age: n - 1 - k, date: rows[k][0] };
      const next = k + 1 < n ? rows[k + 1][0] : "9999";
      let i = day.length - 1; while (i > 0 && day[i][0] >= next) i--;
      return { age: day.length - 1 - i, date: day[i][0] };
    };
    const base = rows.slice(0, n - m), C0 = base[base.length - 1][4];
    const flips = flipLevels(base, tf, PCT);
    const tfn = tf === "D" ? "J" : "S";
    // R→S le plus proche sous le cours
    const sup = flips.filter(f => f.type === "RS" && f.price < C0).sort((a, b) => b.price - a.price)[0];
    if (sup) {
      const P = sup.price, zone = P * (1 + TOL), floor = P * (1 - TOL);
      let kc = -1, failed = false, kr = -1;
      for (let k = n - m; k < n; k++) {
        const [, , H, L, Cl] = rows[k];
        if (Cl < floor) { failed = true; break; }
        if (L <= zone) { kc = k; kr = -1; continue; }                   // (nouveau) contact
        if (kc >= 0 && kr < 0 && Cl > rows[kc][2]) kr = k;               // réaction : clôture au-dessus du plus haut du contact
      }
      if (!failed && kc >= 0) {
        const at = sess(kr >= 0 ? kr : kc);
        found.push({ k: kr >= 0 ? "rs_reaction" : "rs_contact", tf: tfn, lv: r4(P), n: sup.retests.length, hi: r4(rows[kc][2]), ...at });
      }
    }
    // S→R le plus proche au-dessus du cours
    const res = flips.filter(f => f.type === "SR" && f.price > C0).sort((a, b) => a.price - b.price)[0];
    if (res) {
      const P = res.price, lo = P * (1 - TOL), hi = P * (1 + TOL);
      let kb = -1, kt = -1;
      for (let k = n - m; k < n; k++) {
        if (rows[k][4] > hi) { kb = k; break; }
        if (rows[k][2] >= lo) kt = k;
      }
      if (kb >= 0) found.push({ k: "sr_franchie", tf: tfn, lv: r4(P), n: res.retests.length, ...sess(kb) });
      else if (kt >= 0) found.push({ k: "sr_test", tf: tfn, lv: r4(P), n: res.retests.length, ...sess(kt) });
    }
  }
  // même niveau en J et en S : on garde l'hebdo (plus solide)
  const kept = [];
  found.forEach(f => { if (!kept.some(g => g.k.slice(0, 2) === f.k.slice(0, 2) && Math.abs(g.lv / f.lv - 1) <= 2 * TOL)) kept.push(f); });
  kept.filter(f => f.age <= MAX_AGE[f.k]).forEach(f => {
    const close = day[day.length - 1 - f.age][4];
    items.push({ sym, date: f.date, age: f.age, close, last, sig: [{ k: f.k, tf: f.tf, lv: f.lv, n: f.n, hi: f.hi }] });
  });
}
items.sort((a, b) => a.age - b.age);
fs.writeFileSync("data/flips.json", JSON.stringify({ updated: new Date().toISOString().slice(0, 16) + "+00:00", items }) + "\n");
console.log("situations R⇄S :", items.length);
items.forEach(e => console.log("  ", e.sym, e.sig[0].k, e.sig[0].tf, e.sig[0].lv, e.date, "âge", e.age));
