# Ajoute à index.html : cours en séance, bougie du jour et unité 15 min (relais Cloudflare « cours-live »).
# Usage unique : python3 scripts/patch_live.py  (beta.html = index.html + étiquette ESSAI)
import re, sys
p = "index.html"
s = open(p).read()
if "LIVE_URL" in s:
    sys.exit("déjà appliqué")

def rep(a, b, cnt=1):
    global s
    assert a in s, "introuvable : " + a[:80]
    s = s.replace(a, b, cnt)

# ---- cartes : cours en séance ----
rep('    const info = summary.symbols[item.yahoo] || { pending:true };\n    const card = document.createElement("div"); card.className = "card";',
    '    const info = withLive(item.yahoo, summary.symbols[item.yahoo] || { pending:true });\n    const card = document.createElement("div"); card.className = "card"; card.dataset.sym = item.yahoo;')
rep('      card.querySelector(".chg").textContent = fmtPct(pct);\n',
    '      card.querySelector(".chg").textContent = fmtPct(pct);\n      if (info.live) card.querySelector(".nm").insertAdjacentHTML("afterbegin", liveDot(info));\n')
rep('  s.setData(rows.map(r => ({ time:r[0], value:r[4] })));\n  addLevels(s, info, prefs.cols <= 2);',
'''  const pts = rows.map(r => ({ time:r[0], value:r[4] }));
  const lq = liveOn() && liveQuotes[el.dataset.sym];
  if (lq && pts.length) { if (lq.day > pts[pts.length - 1].time) pts.push({ time:lq.day, value:lq.price }); else if (lq.day === pts[pts.length - 1].time) pts[pts.length - 1].value = lq.price; }
  s.setData(pts);
  addLevels(s, info, prefs.cols <= 2);''')

# ---- détail : en-tête, bougie du jour, données 15 min ----
rep('async function openDetail(item, info, pos) {\n', 'async function openDetail(item, info, pos) {\n  info = withLive(item.yahoo, info);\n')
rep('''  const data = await getSeries(info);
  if (seq !== openSeq) return;          // une autre action a été ouverte entre-temps
  ovItem = info;
  ovData = data;''', '''  const data = await withLiveData(item.yahoo, await getSeries(info));
  if (seq !== openSeq) return;          // une autre action a été ouverte entre-temps
  ovItem = info;
  ovData = data; ovSym = item.yahoo;''')
rep('let ovItem = null, ovData = null, ovItemName = "";', 'let ovItem = null, ovData = null, ovItemName = "", ovSym = null;')
rep('const INTERVALS = [["D","Jour","journaliers"],', 'const INTERVALS = [["I","15 min","de 15 minutes"],["D","Jour","journaliers"],')
rep('''  renderSeg("ivSeg", INTERVALS, iv, v => { const keep = captureView(); prefs.iv = v; savePrefs(); drawDetail(keep); });
  [...$("ivSeg").children].forEach((b, k) => {
    b.textContent = { D:"J", W:"S", M:"M", Q:"T" }[INTERVALS[k][0]];
    b.title = "Chandeliers " + INTERVALS[k][2];
  });''', '''  const ivs = hasIntraday() ? INTERVALS : INTERVALS.filter(x => x[0] !== "I");
  renderSeg("ivSeg", ivs, iv, v => { const keep = captureView(); prefs.iv = v; savePrefs(); drawDetail(keep); });
  [...$("ivSeg").children].forEach((b, k) => {
    b.textContent = { I:"15'", D:"J", W:"S", M:"M", Q:"T" }[ivs[k][0]];
    b.title = "Chandeliers " + ivs[k][2];
  });''')
rep('''function drawDetail(keep) {
  fitPrev = null; if ($("fitBtn")) setFitLabel();
  const info = ovItem, iv = prefs.iv || "D";''', '''function drawDetail(keep) {
  fitPrev = null; if ($("fitBtn")) setFitLabel();
  if (prefs.iv === "I" && !hasIntraday()) prefs.iv = "D";     // 15 min indisponible pour cette valeur : retour au jour
  const info = ovItem, iv = prefs.iv || "D";''')
# unité 15 min : regroupements et paramètres
rep('  if (iv === "D") return d;\n  if (iv === "W")', '  if (iv === "D" || iv === "I") return d;\n  if (iv === "W")')
rep('function aggregate(rows, iv) {\n  if (iv === "D") return rows;', 'function aggregate(rows, iv) {\n  if (iv === "D" || iv === "I") return rows;')
rep('''  const k = data.symbol + "|" + iv;
  if (!barsCache[k]) {''', '''  if (iv === "I") return data.intraday || [];
  const k = data.symbol + "|" + iv;
  if (!barsCache[k]) {''')
rep('  const show = { D: RANGES.find(r => r[0] === prefs.range)[2], W: 104, M: 60, Q: 9999 }[iv];',
    '  const show = { I: 9999, D: RANGES.find(r => r[0] === prefs.range)[2], W: 104, M: 60, Q: 9999 }[iv];')
rep('const MA_LOOKBACK = { D:250, W:156, M:120, Q:40 };', 'const MA_LOOKBACK = { I:300, D:250, W:156, M:120, Q:40 };')
s = s.replace('{ D:"jours", W:"semaines", M:"mois", Q:"trimestres" }[iv]', '{ I:"chandeliers de 15 min", D:"jours", W:"semaines", M:"mois", Q:"trimestres" }[iv]')
# dates : les chandeliers 15 min ont une heure (horodatage numérique)
s = re.sub(r'new Date\(([^()]+?) \+ "T00:00:00Z"\)', r'dOf(\1)', s)
rep('''    const d = dOf(row[0]).toLocaleDateString("fr-FR", { day:"2-digit", month:"short", year:"numeric", timeZone:"UTC" });''',
    '''    const d = dOf(row[0]).toLocaleDateString("fr-FR", { day:"2-digit", month:"short", year:"numeric", timeZone:"UTC" })
      + (typeof row[0] === "number" ? " " + dOf(row[0]).toLocaleTimeString("fr-FR", { hour:"2-digit", minute:"2-digit", timeZone:"UTC" }) : "");''')
rep('''    const row = param && param.time ? bySeries.get(typeof param.time === "string" ? param.time :''',
    '''    const row = param && param.time ? bySeries.get(typeof param.time !== "object" ? param.time :''')

# ---- en-tête de page et démarrage ----
rep('  $("updated").textContent = "Mis à jour le " + new Date(summary.updated).toLocaleString("fr-FR", { dateStyle:"short", timeStyle:"short" }) + " · cours de clôture (Yahoo Finance)";',
'''  $("updated").textContent = "Clôtures du " + new Date(summary.updated).toLocaleString("fr-FR", { dateStyle:"short", timeStyle:"short" }) + " (Yahoo Finance)";
  $("updated").insertAdjacentHTML("beforeend", ' <span id="liveStatus" class="live-status" title="Toucher pour activer / désactiver les cours en séance"></span>');
  $("liveStatus").onclick = () => { prefs.live = !liveOn(); savePrefs(); render(); startLive(); if (!liveOn()) { $("liveStatus").textContent = "○ En séance : désactivé"; $("liveStatus").className = "live-status ko"; } };''')
rep('  render();\n})();', '  render();\n  startLive();\n})();')

live = open("scripts/live_module.js").read()
i = s.rindex("</script>"); s = s[:i] + live + "\n" + s[i:]
css = open("scripts/live_module.css").read()
j = s.index("</style>"); s = s[:j] + css + s[j:]
open(p, "w").write(s)
print("ok")
