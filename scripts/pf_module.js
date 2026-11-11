
/* ===== Onglet « Portefeuille » : achats / ventes de M et D, chiffrés dans positions.enc.json sur GitHub ===== */
const PF_FILE = "positions.enc.json", PF_PASS = "mes-actions-pf-pass";
const PF_OWNERS = { M:{ col:"#0ea5e9" }, D:{ col:"#db2777" } };
let pfState = { loaded:false, exists:null, data:null, sha:null, err:"" };

/* --- chiffrement AES-GCM, clé dérivée du mot de passe (PBKDF2, 250 000 tours) --- */
const b64u = buf => btoa(String.fromCharCode(...new Uint8Array(buf)));
const unb64u = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
async function pfKey(pass, salt) {
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(pass), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey({ name:"PBKDF2", salt, iterations:250000, hash:"SHA-256" }, base, { name:"AES-GCM", length:256 }, false, ["encrypt", "decrypt"]);
}
async function pfEncrypt(obj, pass) {
  const salt = crypto.getRandomValues(new Uint8Array(16)), iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = await crypto.subtle.encrypt({ name:"AES-GCM", iv }, await pfKey(pass, salt), new TextEncoder().encode(JSON.stringify(obj)));
  return { v:1, alg:"AES-GCM/PBKDF2-SHA256-250k", salt:b64u(salt), iv:b64u(iv), data:b64u(ct) };
}
async function pfDecrypt(env, pass) {
  const pt = await crypto.subtle.decrypt({ name:"AES-GCM", iv:unb64u(env.iv) }, await pfKey(pass, unb64u(env.salt)), unb64u(env.data));
  return JSON.parse(new TextDecoder().decode(pt));
}
const pfPass = () => { try { return localStorage.getItem(PF_PASS) || ""; } catch (e) { return ""; } };
const setPfPass = v => { try { v ? localStorage.setItem(PF_PASS, v) : localStorage.removeItem(PF_PASS); } catch (e) {} };

/* --- lecture / écriture sur GitHub --- */
async function pfFetchEnv() {
  const tok = getTok();
  if (tok) {
    const r = await fetch("https://api.github.com/repos/" + REPO + "/contents/" + PF_FILE + "?ref=main&t=" + Date.now(),
      { headers:{ Authorization:"Bearer " + tok, Accept:"application/vnd.github+json" }, cache:"no-store" });
    if (r.status === 404) return { env:null, sha:null };
    if (r.ok) { const j = await r.json(); return { env:JSON.parse(b64dec(j.content)), sha:j.sha }; }
  }
  const r = await fetch(PF_FILE + "?t=" + Date.now(), { cache:"no-store" });      // sans jeton : copie publiée du site
  if (r.status === 404) return { env:null, sha:null };
  if (!r.ok) throw new Error("lecture impossible (" + r.status + ")");
  return { env:await r.json(), sha:null };
}
async function pfLoad() {
  pfState.err = "";
  try {
    const { env, sha } = await pfFetchEnv();
    pfState.exists = !!env; pfState.sha = sha; pfState.env = env;
    if (env && pfPass()) {
      try { pfState.data = await pfDecrypt(env, pfPass()); }
      catch (e) { pfState.data = null; setPfPass(""); pfState.err = "Mot de passe incorrect."; }
    }
  } catch (e) { pfState.err = "Impossible de lire le portefeuille : " + e.message; }
  pfState.loaded = true;
}
async function pfSave(mutate, message) {
  const tok = getTok();
  if (!tok) throw new Error("NOTOKEN");
  const pass = pfPass(); if (!pass) throw new Error("Portefeuille verrouillé.");
  for (let attempt = 0; attempt < 2; attempt++) {
    const { env, sha } = await pfFetchEnv();                       // version la plus récente (l'autre personne a pu enregistrer entre-temps)
    const cur = env ? await pfDecrypt(env, pass) : { M:{ tx:[] }, D:{ tx:[] } };
    mutate(cur);
    const body = { message, branch:"main", content:b64enc(JSON.stringify(await pfEncrypt(cur, pass)) + "\n") };
    if (sha) body.sha = sha;
    const put = await fetch("https://api.github.com/repos/" + REPO + "/contents/" + PF_FILE, { method:"PUT",
      headers:{ Authorization:"Bearer " + tok, Accept:"application/vnd.github+json" }, body:JSON.stringify(body) });
    if (put.status === 409 || put.status === 422) continue;        // conflit : on relit et on recommence une fois
    if (put.status === 401 || put.status === 403) throw new Error("BADTOKEN");
    if (!put.ok) throw new Error("Enregistrement refusé par GitHub (" + put.status + ")");
    const j = await put.json();
    pfState.data = cur; pfState.exists = true; pfState.sha = j.content && j.content.sha;
    return;
  }
  throw new Error("Conflit d'enregistrement, réessaie.");
}

/* --- calculs : PRU (coût moyen pondéré, frais inclus), plus-values latentes et réalisées --- */
function allSymbols() {
  const m = new Map();
  cfg.portfolios.forEach(p => p.items.forEach(it => { if (!m.has(it.yahoo)) m.set(it.yahoo, it); }));
  return m;
}
function pfPositions(tx) {
  const by = new Map();
  tx.slice().sort((a, b) => a.date < b.date ? -1 : a.date > b.date ? 1 : (a.t || 0) - (b.t || 0)).forEach(t => {
    const p = by.get(t.sym) || { sym:t.sym, qty:0, cost:0, realized:0, soldCost:0, bought:0, fees:0, first:t.date, tx:[] };
    const fees = +t.fees || 0;
    p.fees += fees; p.tx.push(t);
    if (t.type === "A") { p.qty += +t.qty; p.cost += t.qty * t.price + fees; p.bought += t.qty * t.price + fees; }
    else {
      const avg = p.qty > 0 ? p.cost / p.qty : 0, q = Math.min(+t.qty, p.qty);
      p.realized += q * t.price - fees - q * avg;
      p.soldCost += q * avg;                     // prix de revient des actions vendues : base du % réalisé
      p.cost -= q * avg; p.qty -= q;
      if (p.qty < 1e-9) { p.qty = 0; p.cost = 0; }
    }
    by.set(t.sym, p);
  });
  const syms = allSymbols();
  return [...by.values()].map(p => {
    const info = withLive(p.sym, summary.symbols[p.sym] || {});
    const it = syms.get(p.sym) || { name:p.sym };
    const price = info.last, pru = p.qty > 0 ? p.cost / p.qty : null;
    const value = p.qty > 0 && price != null ? p.qty * price : 0;
    const latent = p.qty > 0 && price != null ? value - p.cost : 0;
    return Object.assign(p, { name:it.name, item:it, cur:info.currency || "EUR", price, pru, value, latent,
      latentPct: p.cost > 0 ? latent / p.cost * 100 : null, dayPct:info.changePct,
      realizedPct: p.soldCost > 0 ? p.realized / p.soldCost * 100 : null });
  }).sort((a, b) => (b.qty > 0) - (a.qty > 0) || b.value - a.value || a.name.localeCompare(b.name));
}

/* --- affichage --- */
const pfView = () => prefs.view === "pf";
const pfOwner = () => prefs.pfOwner === "D" ? "D" : "M";
const money = (v, cur) => v == null || isNaN(v) ? "–" : (v > 0 ? "+" : "") +        // montants : toujours 2 décimales
  v.toLocaleString(NUM_LOC, { minimumFractionDigits:2, maximumFractionDigits:2 }) + (cur && CUR[cur] ? " " + CUR[cur] : "");
async function renderPf() {
  document.body.classList.add("pf-mode");
  const box = $("pfView"); box.hidden = false;
  if (!pfState.loaded) { box.innerHTML = '<div class="msg">Chargement du portefeuille…</div>'; await pfLoad(); }
  box.innerHTML = "";
  const head = document.createElement("div"); head.className = "pf-head";
  head.innerHTML = '<div class="seg" id="pfOwnerSeg"></div><span class="spacer"></span>';
  box.appendChild(head);
  renderSeg("pfOwnerSeg", [["M","M"],["D","D"]], pfOwner(), v => { prefs.pfOwner = v; savePrefs(); renderPf(); });

  if (!pfState.data) {                          // verrouillé, ou pas encore créé
    const f = document.createElement("form"); f.className = "pf-lock"; f.autocomplete = "off";
    const first = pfState.exists === false;
    f.innerHTML = (first
      ? '<h3>Créer le portefeuille</h3><p class="hint">Choisissez un mot de passe : il chiffre vos achats et ventes avant leur envoi sur GitHub (dépôt public). Sans lui, personne ne peut les lire — <b>notez-le bien</b>, il ne peut pas être récupéré. Votre femme utilisera le même mot de passe sur ses appareils.</p>'
      : '<h3>Portefeuille verrouillé</h3><p class="hint">Saisissez le mot de passe du portefeuille (une seule fois par appareil).</p>') +
      '<label>Mot de passe<input type="password" id="pfP1" required minlength="6"></label>' +
      (first ? '<label>Confirmer<input type="password" id="pfP2" required minlength="6"></label>' : '') +
      '<p class="err" id="pfErr"></p><div class="row"><button class="btn primary" type="submit">' + (first ? "Créer" : "Déverrouiller") + '</button></div>';
    box.appendChild(f);
    if (pfState.err) $("pfErr").textContent = pfState.err;
    f.onsubmit = async e => {
      e.preventDefault();
      const p1 = $("pfP1").value;
      if (first && p1 !== $("pfP2").value) { $("pfErr").textContent = "Les deux mots de passe diffèrent."; return; }
      if (first) {
        if (!getTok()) { $("pfErr").textContent = "Il faut d'abord enregistrer votre jeton GitHub (bouton « + Ajouter » d'un autre onglet)."; return; }
        setPfPass(p1);
        try { await pfSave(() => {}, "Portefeuille : création (chiffré)"); toast("Portefeuille créé."); renderPf(); }
        catch (err) { setPfPass(""); $("pfErr").textContent = err.message === "NOTOKEN" || err.message === "BADTOKEN" ? "Jeton GitHub manquant ou invalide." : err.message; }
      } else {
        try { pfState.data = await pfDecrypt(pfState.env, p1); setPfPass(p1); pfState.err = ""; renderPf(); }
        catch (err) { $("pfErr").textContent = "Mot de passe incorrect."; }
      }
    };
    return;
  }

  if (pfImportPending) { const raw = pfImportPending; pfImportPending = null; setTimeout(() => askImport(raw), 50); }
  const lockB = document.createElement("button"); lockB.className = "btn"; lockB.textContent = "🔒";
  lockB.title = "Verrouiller sur cet appareil (oublie le mot de passe)";
  lockB.onclick = () => { setPfPass(""); pfState.data = null; renderPf(); };
  const addB = document.createElement("button"); addB.className = "btn primary"; addB.textContent = "+ Opération";
  addB.onclick = () => openTxDlg();
  const cmpB = document.createElement("button"); cmpB.className = "btn" + (prefs.pfCompact ? " on" : "");
  cmpB.textContent = prefs.pfCompact ? "☰ Détaillé" : "≡ Compact";
  cmpB.title = prefs.pfCompact ? "Afficher les achats et ventes de chaque valeur" : "Une ligne par valeur, sans le détail des opérations";
  cmpB.onclick = () => { prefs.pfCompact = !prefs.pfCompact; savePrefs(); renderPf(); };
  head.append(cmpB, addB, lockB);

  const own = pfOwner(), tx = (pfState.data[own] && pfState.data[own].tx) || [];
  const pos = pfPositions(tx);
  const dayN = d => Date.parse(d + "T00:00:00Z") / 864e5;
  let nDup = 0;
  tx.forEach(t => { t._dup = tx.some(u => u !== t && u.sym === t.sym && u.type === t.type && Math.abs(u.qty - t.qty) < 1e-9 && Math.abs(dayN(u.date) - dayN(t.date)) <= 3); if (t._dup) nDup++; });
  if (nDup) box.insertAdjacentHTML("beforeend", '<div class="pf-warn">⚠ ' + nDup + ' opérations ressemblent à des doublons (même valeur, même quantité, à quelques jours d\'écart). Elles sont marquées « doublon ? » en vue Détaillée : supprimez celle qui est en trop avec ✕.</div>');
  if (!tx.length) {
    box.insertAdjacentHTML("beforeend", '<div class="msg">Aucune opération pour ' + own + '. Touchez « + Opération » pour saisir un achat ou une vente.</div>');
    return;
  }
  /* totaux par devise */
  const tot = {};
  pos.forEach(p => { const t = tot[p.cur] = tot[p.cur] || { cost:0, value:0, latent:0, realized:0, soldCost:0 };
    t.cost += p.cost; t.value += p.value; t.latent += p.latent; t.realized += p.realized; t.soldCost += p.soldCost; });
  const sum = document.createElement("div"); sum.className = "pf-sum" + (prefs.pfCompact ? " compact" : "");
  Object.entries(tot).forEach(([cur, t]) => {
    const pct = t.cost > 0 ? t.latent / t.cost * 100 : null;
    sum.insertAdjacentHTML("beforeend",
      '<div><span>Investi</span><b>' + fmt(t.cost, cur) + '</b></div>' +
      '<div><span>Valeur</span><b>' + fmt(t.value, cur) + '</b></div>' +
      '<div><span>Plus-value latente</span><b class="' + (t.latent >= 0 ? "up" : "down") + '">' + money(t.latent, cur) + (pct != null ? " (" + fmtPct(pct) + ")" : "") + '</b></div>' +
      '<div><span>Réalisé (ventes)</span><b class="' + (t.realized >= 0 ? "up" : "down") + '">' + money(t.realized, cur) + (t.soldCost > 0 ? " (" + fmtPct(t.realized / t.soldCost * 100) + ")" : "") + '</b></div>');
  });
  box.appendChild(sum);

  // deux groupes : positions ouvertes, puis positions soldées (tout vendu)
  const openL = document.createElement("div"), closedL = document.createElement("div");
  openL.className = closedL.className = "pf-list" + (prefs.pfCompact ? " compact" : "");
  const openB = [], closedB = [];                // cartes à répartir ensuite par groupe (Europe, États-Unis, trackers, cryptos)
  pos.forEach(p => {
    const list = p.qty > 0 ? openB : closedB;
    const c = document.createElement("div"); c.className = "pf-pos" + (p.qty > 0 ? "" : " closed");
    const open = p.qty > 0;
    c.innerHTML =
      '<div class="r1"><b class="nm"></b><span class="' + (open ? (p.latent >= 0 ? "up" : "down") : (p.realized >= 0 ? "up" : "down")) + '">' +
        (open ? money(p.latent, p.cur) + (p.latentPct != null ? " · " + fmtPct(p.latentPct) : "") : money(p.realized, p.cur) + (p.realizedPct != null ? " · " + fmtPct(p.realizedPct) : "")) + '</span></div>' +
      '<div class="r2">' + (open
        ? fmt(p.qty, null).replace(/,00$/, "") + " × PRU " + fmt(p.pru, p.cur) + " → cours " + fmt(p.price, p.cur) + (p.dayPct != null ? ' <span class="' + (p.dayPct >= 0 ? "up" : "down") + '">(' + fmtPct(p.dayPct) + " auj.)</span>" : "")
        : "Aucune action détenue") +
      (open && Math.abs(p.realized) > 0.005 ? ' · réalisé <span class="' + (p.realized >= 0 ? "up" : "down") + '">' + money(p.realized, p.cur) + (p.realizedPct != null ? " (" + fmtPct(p.realizedPct) + ")" : "") + '</span>' : "") + '</div>';
    c.querySelector(".nm").textContent = p.name;
    if (prefs.pfCompact) {
      const v = open ? p.latent : p.realized, pc = open ? p.latentPct : p.realizedPct, cl = v >= 0 ? "up" : "down";
      c.innerHTML = '<div class="cp"><b class="nm"></b><b class="pc ' + cl + '">' + (pc != null ? fmtPct(pc) : "") + '</b>' +
        '<span class="vl">' + (open ? fmt(p.value, p.cur) : "soldée") + '</span><span class="eu ' + cl + '">' + money(v, p.cur) + '</span></div>';
      c.querySelector(".nm").textContent = (p.tx.some(t => t._dup) ? "⚠ " : "") + p.name;
    }
    const tl = document.createElement("div"); tl.className = "pf-tx";
    p.tx.slice().reverse().forEach(t => {
      const row = document.createElement("div");
      row.innerHTML = '<span class="ty ' + (t.type === "A" ? "a" : "v") + '">' + (t.type === "A" ? "Achat" : "Vente") + '</span><span class="d"></span><span class="q"></span>' + (t._dup ? '<span class="dup" title="Opération semblable à quelques jours d\'écart">doublon ?</span>' : '') + '<button class="e" title="Modifier cette opération">✎</button><button class="x" title="Supprimer cette opération">✕</button>';
      row.querySelector(".d").textContent = new Date(t.date + "T00:00:00Z").toLocaleDateString("fr-FR", { timeZone:"UTC" });
      row.querySelector(".q").textContent = fmt(+t.qty, null).replace(/,00$/, "") + " × " + fmt(+t.price, p.cur) + (+t.fees ? " + frais " + fmt(+t.fees, p.cur).replace(" ", "\u00a0") : "");
      row.querySelector(".x").onclick = ev => { ev.stopPropagation(); delTx(own, t, p.name); };
      row.querySelector(".e").onclick = ev => { ev.stopPropagation(); openTxDlg(t); };
      tl.appendChild(row);
    });
    c.appendChild(tl);
    c.onclick = () => {                         // ouvre le graphique de la valeur, avec les repères d'achat / vente
      const pi = cfg.portfolios.findIndex(pf => pf.items.some(i => i.yahoo === p.sym));
      if (pi < 0 || !summary.symbols[p.sym]) { toast("Ajoutez d'abord cette valeur à un onglet pour voir son graphique.", 2200); return; }
      openDetail(p.item, summary.symbols[p.sym], { pi, idx:cfg.portfolios[pi].items.findIndex(i => i.yahoo === p.sym) });
    };
    c._cat = pfCat(p); list.push(c);
  });
  const fill = (L, B) => PF_CATS.forEach(([k, lab]) => {
    const g = B.filter(c => c._cat === k); if (!g.length) return;
    L.insertAdjacentHTML("beforeend", '<div class="pf-sub">' + lab + ' <span>' + g.length + '</span></div>');
    g.forEach(c => L.appendChild(c));
    if (prefs.pfCompact && g.length % 2) L.insertAdjacentHTML("beforeend", '<div class="pf-fill"></div>');   // case vide pour finir la ligne en 2 colonnes
  });
  fill(openL, openB); fill(closedL, closedB);
  const nOpen = openB.length, nClosed = closedB.length;
  if (nOpen) { box.insertAdjacentHTML("beforeend", '<h3 class="pf-grp">Positions ouvertes <span>' + nOpen + '</span></h3>'); box.appendChild(openL); }
  if (nClosed) {
    const rz = pos.filter(p => p.qty === 0).reduce((o, p) => { const r = o[p.cur] = o[p.cur] || { v:0, c:0 }; r.v += p.realized; r.c += p.soldCost; return o; }, {});
    const txt = Object.entries(rz).map(([cur, r]) => '<b class="' + (r.v >= 0 ? "up" : "down") + '">' + money(r.v, cur) + (r.c > 0 ? " · " + fmtPct(r.v / r.c * 100) : "") + "</b>").join(" · ");
    box.insertAdjacentHTML("beforeend", '<h3 class="pf-grp">Positions soldées <span>' + nClosed + '</span><em>' + txt + '</em></h3>'); box.appendChild(closedL);
  }
  box.insertAdjacentHTML("beforeend", '<p class="hint pf-note">PRU = coût moyen pondéré, frais d\'achat inclus ; une vente réalise (prix − PRU) × quantité − frais. Cours en séance si « Direct » est actif. Données chiffrées sur GitHub (' + PF_FILE + ').</p>');
}
/* Groupes de positions : Europe, États-Unis (autre fuseau horaire), trackers, cryptos */
const PF_CATS = [["eu", "Europe"], ["us", "États-Unis"], ["etf", "Trackers (ETF)"], ["crypto", "Cryptos"], ["other", "Autres"]];
const EU_SUFFIX = /\.(PA|AS|BR|DE|F|MI|MC|LS|L|IR|SW|VI|ST|HE|CO|OL|WA|PR|AT)$/;
function pfCat(p) {
  const info = summary.symbols[p.sym] || {}, ty = (info.type || "").toUpperCase(), nm = (p.name || "") + " " + p.sym;
  if (ty === "CRYPTOCURRENCY" || /-(USD|EUR|USDT)$/.test(p.sym)) return "crypto";
  if (ty === "ETF" || ty === "MUTUALFUND" || /\b(iShares|ETF|UCITS|Vanguard|Amundi|Lyxor|SPDR|Xtrackers|Tracker)\b/i.test(nm)) return "etf";
  if (EU_SUFFIX.test(p.sym)) return "eu";
  if (!/\./.test(p.sym) && !/^\^/.test(p.sym)) return "us";
  return "other";
}
/* ----- Import par lien : #pfimport=<base64url {owner, tx:[{type,sym,date,qty,price,fees}]}> ----- */
let pfImportPending = null;
window.addEventListener("hashchange", () => {        // lien ouvert alors que la page est déjà affichée
  if (/^#pfimport=/.test(location.hash) && cfg) { pfImportPending = location.hash.slice(10); prefs.view = "pf"; render(); }
});
function askImport(raw) {
  history.replaceState(null, "", location.pathname + location.search);       // on retire les données de l'adresse
  let pack;
  try { pack = JSON.parse(decodeURIComponent(escape(atob(raw.replace(/-/g, "+").replace(/_/g, "/"))))); } catch (e) { toast("Lien d'import illisible.", 2500); return; }
  const own = pack.owner === "D" ? "D" : "M", cur = ((pfState.data[own] || {}).tx || []);
  const same = (a, b) => a.sym === b.sym && a.date === b.date && a.type === b.type && Math.abs(a.qty - b.qty) < 1e-9 && Math.abs(a.price - b.price) < 1e-9 && Math.abs((+a.fees || 0) - (+b.fees || 0)) < 1e-9;
  const syms = allSymbols();
  const add = [], skip = [], unknown = [];
  (pack.tx || []).forEach(t => {
    t = { type:t.type === "V" ? "V" : "A", sym:t.sym, date:t.date, qty:+t.qty, price:+t.price, fees:+t.fees || 0 };
    if (!syms.has(t.sym)) unknown.push(t); else if (cur.some(x => same(x, t)) || add.some(x => same(x, t))) skip.push(t); else add.push(t);
  });
  const line = t => (t.type === "A" ? "Achat" : "Vente") + " · " + new Date(t.date + "T00:00:00Z").toLocaleDateString("fr-FR", { timeZone:"UTC" }) + " · " +
    (syms.get(t.sym) || { name:t.sym }).name + " · " + fmt(t.qty, null).replace(/,00$/, "") + " × " + fmt(t.price, null) + (t.fees ? " + frais " + fmt(t.fees, null) : "");
  const bad = checkTxList(cur.concat(add), "") || [...new Set(add.map(t => t.sym))].map(sy => checkTxList(cur.concat(add), sy)).find(x => x) || "";
  $("confText").innerHTML = "";
  $("confText").insertAdjacentHTML("beforeend", "<b>Importer dans le portefeuille " + own + " :</b>");
  const ul = document.createElement("ul"); ul.className = "imp-list";
  add.forEach(t => { const li = document.createElement("li"); li.textContent = line(t); ul.appendChild(li); });
  skip.forEach(t => { const li = document.createElement("li"); li.className = "skip"; li.textContent = line(t) + " — déjà présent, ignoré"; ul.appendChild(li); });
  unknown.forEach(t => { const li = document.createElement("li"); li.className = "skip"; li.textContent = t.sym + " — valeur absente des onglets, ignorée"; ul.appendChild(li); });
  $("confText").appendChild(ul);
  $("confErr").textContent = bad;
  $("confYes").textContent = add.length ? "Importer " + add.length + " opération" + (add.length > 1 ? "s" : "") : "Fermer";
  $("confYes").disabled = !!bad && add.length > 0;
  $("confDlg").classList.add("show");
  const close = () => { $("confDlg").classList.remove("show"); $("confYes").textContent = "Retirer"; $("confYes").disabled = false; };
  $("confNo").onclick = close;
  $("confYes").onclick = async () => {
    if (!add.length) { close(); return; }
    try {
      const stamp = Date.now();
      await pfSave(d => { d[own] = d[own] || { tx:[] };
        add.forEach((t, k) => { if (!d[own].tx.some(x => same(x, t))) d[own].tx.push(Object.assign({ id:(stamp + k).toString(36) + Math.random().toString(36).slice(2, 6), t:stamp + k }, t)); }); },
        "Portefeuille " + own + " : import de " + add.length + " opération(s)");
      close(); prefs.pfOwner = own; savePrefs(); renderPf(); toast(add.length + " opération" + (add.length > 1 ? "s importées" : " importée") + ".");
    } catch (err) { $("confErr").textContent = err.message === "NOTOKEN" || err.message === "BADTOKEN" ? "Jeton GitHub manquant ou invalide." : err.message; }
  };
}
function delTx(own, t, name) {
  $("confText").textContent = "Supprimer " + (t.type === "A" ? "l'achat" : "la vente") + " de " + name + " du " + new Date(t.date + "T00:00:00Z").toLocaleDateString("fr-FR", { timeZone:"UTC" }) + " (portefeuille " + own + ") ?";
  $("confErr").textContent = ""; $("confYes").textContent = "Supprimer";
  $("confDlg").classList.add("show");
  $("confNo").onclick = () => { $("confDlg").classList.remove("show"); $("confYes").textContent = "Retirer"; };
  $("confYes").onclick = async () => {
    const bad = checkTxList(((pfState.data[own] || {}).tx || []).filter(x => x.id !== t.id), t.sym);
    if (bad) { $("confErr").textContent = "Impossible : " + bad.charAt(0).toLowerCase() + bad.slice(1) + " Supprimez ou modifiez d'abord cette vente."; return; }
    try {
      await pfSave(d => { d[own].tx = d[own].tx.filter(x => x.id !== t.id); }, "Portefeuille " + own + " : suppression d'une opération");
      $("confDlg").classList.remove("show"); $("confYes").textContent = "Retirer"; renderPf(); toast("Opération supprimée.");
    } catch (err) { $("confErr").textContent = err.message === "NOTOKEN" || err.message === "BADTOKEN" ? "Jeton GitHub manquant ou invalide." : err.message; }
  };
}
/* « 1.234,50 », « 1234,5 » ou « 1234.5 » -> 1234.5 */
function numIn(v) {
  v = String(v).replace(/[\s\u202f\u00a0]/g, "");
  if (v.includes(",")) v = v.replace(/\./g, "").replace(",", ".");
  else if (/^\d{1,3}(\.\d{3})+$/.test(v)) v = v.replace(/\./g, "");
  return +v;
}
let txEdit = null;              // opération en cours de modification (null = nouvelle)
/* Vérifie qu'aucune vente ne dépasse la quantité détenue à sa date ; renvoie un message d'erreur ou "" */
function checkTxList(list, sym) {
  let q = 0;
  for (const t of list.filter(x => x.sym === sym).sort((a, b) => a.date < b.date ? -1 : a.date > b.date ? 1 : (a.type === "A" ? -1 : 1))) {
    if (t.type === "A") q += +t.qty;
    else { if (+t.qty > q + 1e-9) return "Vente du " + new Date(t.date + "T00:00:00Z").toLocaleDateString("fr-FR", { timeZone:"UTC" }) + " supérieure à la quantité détenue à cette date (" + fmt(q, null).replace(/,00$/, "") + ")."; q -= +t.qty; }
  }
  return "";
}
function openTxDlg(edit) {
  txEdit = edit || null;
  const own = pfOwner(), sel = $("txSym"); sel.innerHTML = "";
  [...allSymbols().values()].sort((a, b) => a.name.localeCompare(b.name)).forEach(it => {
    const o = document.createElement("option"); o.value = it.yahoo; o.textContent = it.name + " (" + it.yahoo + ")"; sel.appendChild(o);
  });
  if (ovItemName && $("ov").classList.contains("show")) { const cur = [...allSymbols().values()].find(i => i.name === ovItemName); if (cur) sel.value = cur.yahoo; }
  $("txOwner").textContent = own;
  $("txTitle").textContent = txEdit ? "Modifier l'opération" : "Nouvelle opération";
  $("txOk").textContent = txEdit ? "Enregistrer les modifications" : "Enregistrer";
  $("txErr").textContent = "";
  const n2 = v => v == null || v === "" ? "" : (+v).toLocaleString(NUM_LOC, { maximumFractionDigits:6 });
  if (txEdit) {
    sel.value = txEdit.sym; $("txDate").value = txEdit.date;
    $("txQty").value = n2(txEdit.qty); $("txPrice").value = n2(txEdit.price); $("txFees").value = +txEdit.fees ? n2(txEdit.fees) : "";
    document.querySelector('input[name="txType"][value="' + txEdit.type + '"]').checked = true;
  } else {
    $("txDate").value = new Date().toISOString().slice(0, 10);
    $("txQty").value = ""; $("txPrice").value = ""; $("txFees").value = "";
    document.querySelector('input[name="txType"][value="A"]').checked = true;
  }
  $("txDlg").classList.add("show");
}
async function submitTx(e) {
  e.preventDefault();
  const own = pfOwner();
  const edit = txEdit;
  const t = { id:edit ? edit.id : Date.now().toString(36) + Math.random().toString(36).slice(2, 6), t:edit ? edit.t : Date.now(),
    type:document.querySelector('input[name="txType"]:checked').value, sym:$("txSym").value, date:$("txDate").value,
    qty:numIn($("txQty").value), price:numIn($("txPrice").value), fees:numIn($("txFees").value || "0") };
  if (!t.sym || !t.date || !(t.qty > 0) || !(t.price > 0) || !(t.fees >= 0)) { $("txErr").textContent = "Vérifiez la date, la quantité, le prix et les frais."; return; }
  const after = ((pfState.data[own] || {}).tx || []).filter(x => !edit || x.id !== edit.id).concat([t]);
  const bad = checkTxList(after, t.sym) || (edit && edit.sym !== t.sym ? checkTxList(after, edit.sym) : "");
  if (bad) { $("txErr").textContent = bad; return; }
  $("txOk").disabled = true;
  try {
    await pfSave(d => { d[own] = d[own] || { tx:[] };
      if (edit) { const i = d[own].tx.findIndex(x => x.id === edit.id); if (i >= 0) d[own].tx[i] = t; else d[own].tx.push(t); }
      else d[own].tx.push(t); },
      "Portefeuille " + own + " : " + (edit ? "opération modifiée" : t.type === "A" ? "achat ajouté" : "vente ajoutée"));
    $("txDlg").classList.remove("show"); toast(edit ? "Opération modifiée." : t.type === "A" ? "Achat enregistré." : "Vente enregistrée.");
    txEdit = null;
    if (pfView()) renderPf(); else if ($("ov").classList.contains("show")) drawTxMarks();
  } catch (err) { $("txErr").textContent = err.message === "NOTOKEN" || err.message === "BADTOKEN" ? "Jeton GitHub manquant ou invalide (bouton « + Ajouter » d'un autre onglet pour l'enregistrer)." : err.message; }
  $("txOk").disabled = false;
}
$("txForm").addEventListener("submit", submitTx);
$("txCancel").onclick = () => { $("txDlg").classList.remove("show"); txEdit = null; };

/* --- repères d'achat / vente et PRU sur le graphique du détail --- */
let txSeries = null, txSeries2 = null, txLines = [], txZones = [];
/* Début de la détention actuelle : dernière date où la quantité est repassée de 0 à plus de 0 */
/* La valeur affichée a-t-elle au moins une opération (M ou D) ? */
function posAvail() {
  return !!(pfState.data && ovSym && ["M", "D"].some(o => ((pfState.data[o] || {}).tx || []).some(t => t.sym === ovSym)));
}
function holdStart(tx) {
  let q = 0, start = null;
  tx.slice().sort((a, b) => a.date < b.date ? -1 : a.date > b.date ? 1 : (a.type === "A" ? -1 : 1)).forEach(t => {
    if (t.type === "A") { if (q < 1e-9) start = t.date; q += +t.qty; } else q -= +t.qty;
  });
  return q > 1e-9 ? start : null;
}
function drawTxMarks() {
  [txSeries, txSeries2, ...txZones].forEach(x => { if (x && ovChart) { try { ovChart.removeSeries(x); } catch (e) {} } });
  txSeries = txSeries2 = null; txZones = [];
  if (ovCandles) txLines.forEach(l => { try { ovCandles.removePriceLine(l); } catch (e) {} });
  txLines = [];
  const infoEl = $("ovPosInfo"); if (infoEl) infoEl.innerHTML = "";
  if ($("posBtn")) { const av = posAvail(); $("posBtn").hidden = !av; $("posBtn").classList.toggle("on", av && prefs.pos !== false); }
  if (!ovChart || !ovCandles || !ovData || !pfState.data || !ovSym || prefs.pos === false) return;
  const iv = prefs.iv || "D", rows = barsFor(ovData, iv);
  if (!rows.length || typeof rows[0][0] !== "string") return;          // pas de repères en 15 min
  const byKey = new Map(rows.map(r => [keyOf(iv, r[0]), r[0]]));
  const marks = [];
  ["M", "D"].forEach(own => {
    const tx = ((pfState.data[own] || {}).tx || []).filter(t => t.sym === ovSym);
    tx.forEach(t => {
      const time = byKey.get(keyOf(iv, t.date)) || (iv === "D" ? (rows.find(r => r[0] >= t.date) || [])[0] : null);
      if (!time) return;
      marks.push({ time, position:t.type === "A" ? "belowBar" : "aboveBar", shape:t.type === "A" ? "arrowUp" : "arrowDown",
        color:PF_OWNERS[own].col, text:(t.type === "A" ? "A·" : "V·") + own });
    });
    const p = pfPositions(tx).find(x => x.sym === ovSym);
    if (p && (p.qty > 0 || p.realized)) {          // résumé sous le nom : quantité, PRU, gain/perte
      const open = p.qty > 0, v = open ? p.latent : p.realized, pc = open ? p.latentPct : p.realizedPct;
      infoEl.insertAdjacentHTML("beforeend", '<span class="pi"><i style="background:' + PF_OWNERS[own].col + '"></i><b>' + own + '</b> ' +
        (open ? fmt(p.qty, null).replace(/,00$/, "") + " × PRU " + fmt(p.pru, p.cur) + " " : "soldée ") +
        '<span class="' + (v >= 0 ? "up" : "down") + '">' + money(v, p.cur) + (pc != null ? " (" + fmtPct(pc) + ")" : "") + "</span></span>");
    }
    if (p && p.qty > 0) {
      txLines.push(ovCandles.createPriceLine({ price:p.pru, color:PF_OWNERS[own].col, lineWidth:1,
        lineStyle:LW.LineStyle.Dashed, axisLabelVisible:true, title:"" }));       // étiquette réduite au prix sur l'axe (le détail est sous le nom)
      // zone entre le PRU et le cours depuis l'achat : verte au-dessus (gain), rouge en dessous (perte)
      const st = holdStart(tx);
      const from = st ? (byKey.get(keyOf(iv, st)) || (rows.find(r => r[0] >= st) || [])[0]) : null;
      if (from) {
        const z = ovChart.addBaselineSeries({ baseValue:{ type:"price", price:p.pru }, lineWidth:1,
          topLineColor:"rgba(22,163,74,0.55)", topFillColor1:"rgba(22,163,74,0.22)", topFillColor2:"rgba(22,163,74,0.04)",
          bottomLineColor:"rgba(220,38,38,0.55)", bottomFillColor1:"rgba(220,38,38,0.04)", bottomFillColor2:"rgba(220,38,38,0.22)",
          priceLineVisible:false, lastValueVisible:false, crosshairMarkerVisible:false, autoscaleInfoProvider:() => null });
        z.setData(rows.filter(r => r[0] >= from).map(r => ({ time:r[0], value:r[4] })));
        txZones.push(z);
      }
    }
  });
  if (!marks.length) return;
  marks.sort((a, b) => a.time < b.time ? -1 : a.time > b.time ? 1 : 0);
  // deux séries invisibles : les achats sous les plus bas, les ventes au-dessus des plus hauts
  const hidden = () => ovChart.addLineSeries({ color:"rgba(0,0,0,0)", lineVisible:false, lineWidth:1, priceLineVisible:false, lastValueVisible:false,
    crosshairMarkerVisible:false, autoscaleInfoProvider:() => null });
  txSeries = hidden(); txSeries.setData(rows.map(r => ({ time:r[0], value:r[3] })));
  txSeries.setMarkers(marks.filter(m => m.position === "belowBar"));
  txSeries2 = hidden(); txSeries2.setData(rows.map(r => ({ time:r[0], value:r[2] })));
  txSeries2.setMarkers(marks.filter(m => m.position === "aboveBar"));
}
// le portefeuille est lu au démarrage (s'il est déverrouillé) pour afficher les repères dans les autres onglets
setTimeout(() => { if (!pfState.loaded && pfPass()) pfLoad().then(() => {
  if ($("ov").classList.contains("show")) drawTxMarks();
  const a = cfg.portfolios[prefs.active]; if (a && a.name === "Hold" && prefs.view !== "pf") render();      // onglet Hold : maintenant qu'on connaît les positions
}); }, 1500);

