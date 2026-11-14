// Alertes automatiques R⇄S (bascules de rôle), recalculées chaque soir après la mise à jour des cours.
//
// Les niveaux sont calculés avec le code même de l'appli (fonctions extraites d'index.html) : ce sont exactement
// les R→S et S→R affichés sur les graphiques (précision 2 %, unités J et S).
//
// Pour chaque valeur suivie (toutes les listes sauf Market), on écrit dans alerts.json des alertes « auto »
// que le relais Cloudflare vérifie toutes les 5 minutes comme les autres :
//   R→S sous le cours (ex. OVH)       : ① le cours arrive au contact du support   ② il réagit : repasse au-dessus du plus haut de la bougie de contact
//   S→R au-dessus du cours (ex. Essilor) : ① le cours arrive sous la résistance      ② il la franchit (clôture ou mèche au-delà de la zone)
// Chaque alerte a un identifiant stable (niveau + date du dernier passage loin du niveau) : envoyée une seule fois,
// elle se réarme quand le cours s'est éloigné puis revient.
//
// Usage : node scripts/flip_alerts.mjs   (depuis la racine du dépôt)
import fs from "fs";

const html = fs.readFileSync("index.html", "utf8");
function grab(startToken) {                       // extrait une fonction ou une constante d'index.html (accolades équilibrées)
  const i = html.indexOf(startToken);
  if (i < 0) throw new Error("introuvable dans index.html : " + startToken);
  let k = html.indexOf("{", i), depth = 0;
  for (; k < html.length; k++) { if (html[k] === "{") depth++; else if (html[k] === "}" && --depth === 0) break; }
  return html.slice(i, k + 1) + (startToken.startsWith("const") ? ";" : "");
}
const src = [
  grab("function dOf("), grab("function keyOf("), grab("function aggregate("),
  grab("const FLIP_PARAMS = {"), "const FLIP_MAX = 6;", grab("function flipLevels("),
  "return { aggregate, flipLevels };",
].join("\n");
const { aggregate, flipLevels } = new Function(src)();

const PCT = 2, TOL = PCT / 100;                    // précision des contacts par défaut de l'appli
const NEAR = { D: 0.08, W: 0.12 };                 // niveau assez proche du cours pour être surveillé
const REACT = { D: 5, W: 2 };                      // contact récent (chandeliers) pour l'alerte « réaction »
const MAX_SYMS = 30;                               // le relais gratuit fait au plus ~50 requêtes par vérification
const TFN = { D: "jour", W: "hebdo" };

const fmt = v => v.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: v < 10 ? 4 : 2 });
const r4 = v => Math.round(v * 10000) / 10000;

const alertsPath = "alerts.json";
const file = fs.existsSync(alertsPath) ? JSON.parse(fs.readFileSync(alertsPath, "utf8")) : { alerts: [] };
const manual = (file.alerts || []).filter(a => !a.auto);
const enabled = !(file.autoFlips === false);

let cands = [];
if (enabled) {
  const summary = JSON.parse(fs.readFileSync("data/summary.json", "utf8"));
  const pf = JSON.parse(fs.readFileSync("portfolios.json", "utf8")).portfolios;
  const items = new Map();
  pf.filter(p => !/market/i.test(p.name)).forEach(p => p.items.forEach(it => { if (!items.has(it.yahoo)) items.set(it.yahoo, it.name || it.yahoo); }));
  for (const [sym, name] of items) {
    const s = summary.symbols[sym];
    if (!s || !s.file) continue;
    let data;
    try { data = JSON.parse(fs.readFileSync("data/" + s.file, "utf8")); } catch (e) { continue; }
    const per = [];
    for (const tf of ["W", "D"]) {
      const rows = aggregate(data.rows || [], tf);
      if (rows.length < 60) continue;
      const len = rows.length, C = rows[len - 1][4];
      const flips = flipLevels(rows, tf, PCT);
      // date du dernier chandelier resté loin d'une limite (réarmement de l'alerte)
      const lastAway = test => { for (let k = len - 1; k >= 0; k--) if (test(rows[k])) return rows[k][0]; return "0"; };
      const sup = flips.filter(f => f.type === "RS" && f.price < C).sort((a, b) => b.price - a.price)[0];
      if (sup && C / sup.price - 1 <= NEAR[tf]) {
        const P = sup.price, zone = P * (1 + TOL), lab = "R→S " + TFN[tf] + " " + fmt(P);
        // ① contact : le cours descend dans la zone du support (rien si il y est déjà : l'alerte « réaction » prend le relais)
        if (C > zone) per.push({ tf, dist: C / P - 1, a: { sym, name, op: "below", price: r4(zone),
          label: lab + " · contact", note: "Le cours touche le support R→S : surveiller la réaction.",
          id: `auto-${sym}-${tf}-RS-${r4(P)}-c-${lastAway(r => r[3] > zone)}` } });
        // ② réaction : contact récent (le support a tenu à la clôture) → alerte au-dessus du plus haut de la bougie de contact
        for (let k = len - 1; k >= Math.max(0, len - REACT[tf]); k--) {
          const b = rows[k];
          if (b[3] <= zone && b[4] >= P * (1 - TOL)) {
            if (C < b[2]) per.push({ tf, dist: C / P - 1, a: { sym, name, op: "above", price: r4(b[2]),
              label: lab + " · réaction", note: "Rebond sur le support R→S : le cours repasse au-dessus du plus haut de la bougie de contact.", id: `auto-${sym}-${tf}-RS-${r4(P)}-r-${b[0]}` } });
            break;
          }
        }
      }
      const res = flips.filter(f => f.type === "SR" && f.price > C).sort((a, b) => a.price - b.price)[0];
      if (res && res.price / C - 1 <= NEAR[tf]) {
        const P = res.price, lo = P * (1 - TOL), hi = P * (1 + TOL), lab = "S→R " + TFN[tf] + " " + fmt(P);
        // ① le cours arrive sous la résistance   ② il la franchit
        if (C < lo) per.push({ tf, dist: P / C - 1, a: { sym, name, op: "above", price: r4(lo),
          label: lab + " · approche", note: "Le cours vient tester par le dessous l'ancien support devenu résistance (S→R).", id: `auto-${sym}-${tf}-SR-${r4(P)}-a-${lastAway(r => r[2] < lo)}` } });
        per.push({ tf, dist: P / C - 1, a: { sym, name, op: "above", price: r4(hi),
          label: lab + " · franchie", note: "La résistance S→R est franchie : à confirmer à la clôture.", id: `auto-${sym}-${tf}-SR-${r4(P)}-b-${lastAway(r => r[2] < hi)}` } });
      }
    }
    // même niveau en J et en S : on garde l'hebdo (plus solide)
    const kept = [];
    per.forEach(x => { if (!kept.some(y => y.a.op === x.a.op && y.a.label.split(" · ")[1] === x.a.label.split(" · ")[1] && Math.abs(y.a.price / x.a.price - 1) <= TOL)) kept.push(x); });
    if (kept.length) cands.push({ sym, dist: Math.min(...kept.map(x => x.dist)), list: kept.map(x => x.a) });
  }
}
// les valeurs les plus proches de leur niveau d'abord, dans la limite du relais
cands.sort((a, b) => a.dist - b.dist);
const symsManual = new Set(manual.map(a => a.sym));
const room = Math.max(0, MAX_SYMS - symsManual.size);
const auto = [];
let used = 0;
for (const c of cands) {
  if (!symsManual.has(c.sym)) { if (used >= room) continue; used++; }
  c.list.forEach(a => auto.push(Object.assign(a, { auto: true, created: Date.now() })));
}
// garder la date de création des alertes déjà présentes
const prev = new Map((file.alerts || []).filter(a => a.auto).map(a => [a.id, a.created]));
auto.forEach(a => { if (prev.has(a.id)) a.created = prev.get(a.id); });

file.alerts = manual.concat(auto);
fs.writeFileSync(alertsPath, JSON.stringify(file, null, 2) + "\n");
console.log(`alertes R⇄S automatiques : ${auto.length} sur ${new Set(auto.map(a => a.sym)).size} valeurs` + (enabled ? "" : " (désactivées)"));
auto.forEach(a => console.log("  ", a.sym, a.op, a.price, a.label));
