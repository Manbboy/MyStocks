"""
Détection des situations « À regarder » (analyse technique, aucune garantie).

Entrée : les séances d'une valeur, lignes [date, ouverture, haut, bas, clôture, volume].
Tout est calculé avec les seules données connues à la date analysée (pas de regard vers le futur),
ce qui permet d'utiliser exactement le même code pour la mesure sur l'historique et pour le calcul du soir.

Situations retenues après mesure sur l'historique (voir backtest_signals.py) :
  cassure : tendance haussière (cours > MM200 et MM50 > MM200), clôture nettement au-dessus
            d'une résistance (au moins 2 contacts) avec un volume d'au moins 1,5 fois la moyenne de 20 séances
  rebond  : tendance haussière, le cours revient sur un support (à moins de 2 %, ou mèche dessus),
            à condition que ce soit un support hebdo, ou que le RSI Trends journalier soit vert
  (écartées car sans avantage mesurable : retest d'une cassure, RSI Trends vert seul, rebond sur la MM50)
Alertes (pour une position ouverte ; elles ne prédisent pas de baisse sur l'historique, ce sont des repères) :
  sup_casse : clôture nettement sous un support (au moins 2 contacts)
  sous_mm200: le cours repasse sous la MM200
  rt_rouge  : le RSI Trends journalier passe au rouge
"""
import numpy as np

RSI_N, OB, OS = 14, 60, 40
NEAR = 0.02          # « sur l'appui » : à moins de 2 %
BREAK = 0.01         # cassure nette : 1 % au-delà du niveau
VOL_K = 1.5
LV = {"D": (250, 5), "W": (156, 3)}   # (lookback, fenêtre) comme le script quotidien

BULL = {"rebond", "cassure"}
LABEL = {
    "cassure": "Cassure avec volume", "rebond": "Rebond sur support",
    "sup_casse": "Support cassé", "sous_mm200": "Passage sous la MM200", "rt_rouge": "RSI Trends au rouge",
}


def sma(x, n):
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        c = np.cumsum(np.insert(x, 0, 0.0))
        out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def rsi(c, n=RSI_N):
    out = np.full(len(c), np.nan)
    if len(c) <= n:
        return out
    d = np.diff(c)
    g = np.maximum(d, 0); l = np.maximum(-d, 0)
    ag, al = g[:n].mean(), l[:n].mean()
    out[n] = 100 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(c)):
        ag = (ag * (n - 1) + g[i - 1]) / n
        al = (al * (n - 1) + l[i - 1]) / n
        out[i] = 100 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def rt_state(v):
    return np.where(np.isnan(v), 0, np.where(v >= OB, 1, np.where(v <= OS, -1, 0)))


def levels(h, l, ref, lookback, w, pct=0.02):
    """Même règle que support_resistance() du script quotidien, en numpy :
    supports = creux répétés sous `ref`, résistances = sommets répétés au-dessus (au moins 2 contacts)."""
    h = h[-lookback:]; l = l[-lookback:]
    n = len(h)
    if n < 2 * w + 3:
        return [], []
    tol = pct * ref
    hp, lp = [], []
    for i in range(w, n - w):
        if h[i] == h[i - w:i + w + 1].max():
            hp.append(h[i])
        if l[i] == l[i - w:i + w + 1].min():
            lp.append(l[i])

    def cluster(ps):
        out, cur = [], []
        for p in sorted(ps):
            if cur and abs(p - np.mean(cur)) <= tol:
                cur.append(p)
            else:
                if len(cur) >= 2:
                    out.append((float(np.mean(cur)), len(cur)))
                cur = [p]
        if len(cur) >= 2:
            out.append((float(np.mean(cur)), len(cur)))
        return out
    sup = sorted([x for x in cluster(lp) if x[0] < ref], key=lambda x: -x[0])
    res = sorted([x for x in cluster(hp) if x[0] > ref], key=lambda x: x[0])
    return sup, res


class Series:
    """Indicateurs précalculés d'une valeur ; `at(t)` donne les situations du jour t."""

    def __init__(self, rows):
        self.dates = [r[0] for r in rows]
        a = np.array([r[1:6] for r in rows], dtype=float)
        self.o, self.h, self.l, self.c, self.v = a.T
        self.ma20, self.ma50, self.ma200 = sma(self.c, 20), sma(self.c, 50), sma(self.c, 200)
        self.vavg = sma(self.v, 20)
        self.rt = rt_state(rsi(self.c))
        # semaines (lundi) : indices de début de chaque semaine, pour les niveaux hebdo sur semaines terminées
        wk = np.array([np.datetime64(d, "W") for d in self.dates])
        self.wk = wk
        self.wstart = np.r_[0, np.nonzero(wk[1:] != wk[:-1])[0] + 1]

    def weekly(self, t):
        """Chandeliers hebdo des semaines terminées avant la séance t (plus haut, plus bas)."""
        st = self.wstart[self.wstart <= t]            # débuts de semaine ; le dernier = semaine en cours
        if len(st) < 3:
            return None, None
        hh = np.array([self.h[a:b].max() for a, b in zip(st[:-1], st[1:])])
        ll = np.array([self.l[a:b].min() for a, b in zip(st[:-1], st[1:])])
        return hh, ll

    def lv(self, t, ref):
        """Supports / résistances journaliers et hebdo connus à la séance t, autour du prix ref."""
        sup, res = [], []
        s, r = levels(self.h[:t + 1], self.l[:t + 1], ref, *LV["D"])
        sup += [(p, k, "J") for p, k in s]; res += [(p, k, "J") for p, k in r]
        hh, ll = self._wcache(t)
        if hh is not None:
            s, r = levels(hh, ll, ref, *LV["W"])
            sup += [(p, k, "S") for p, k in s]; res += [(p, k, "S") for p, k in r]
        sup.sort(key=lambda x: -x[0]); res.sort(key=lambda x: x[0])
        return sup, res

    def _wcache(self, t):
        key = self.wk[t]
        if getattr(self, "_wk_key", None) != key:
            self._wk_key = key
            self._wk_val = self.weekly(t)
        return self._wk_val

    def at(self, t):
        """Situations de la séance t (avec les seules données jusqu'à t)."""
        c, l = self.c[t], self.l[t]
        if t < 210 or np.isnan(self.ma200[t]):
            return []
        out = []
        ma50, ma200 = self.ma50[t], self.ma200[t]
        up = c > ma200 and ma50 > ma200                  # tendance haussière
        sup, res = self.lv(t, c)                         # niveaux autour de la clôture du jour
        psup, pres = self.lv(t - 1, self.c[t - 1])       # niveaux connus la veille
        tgt = next((p for p, k, tf in res if p > c * 1.01), None)
        ctx = {"res": round(tgt, 4) if tgt else None}
        # cassure : clôture nettement au-dessus d'une résistance de la veille, avec du volume, en tendance haussière
        vr = self.v[t] / self.vavg[t] if self.vavg[t] > 0 else 0
        br = [x for x in pres if c > x[0] * (1 + BREAK) and self.c[t - 1] <= x[0]]
        if br and vr >= VOL_K and up:
            x = max(br, key=lambda y: y[0])
            out.append(dict(ctx, k="cassure", lv=round(x[0], 4), tf=x[2], n=x[1], vol=round(float(vr), 1),
                            fort=bool(x[2] == "S" or vr >= 2)))
        # rebond : en tendance, le cours revient sur un support ; support hebdo, ou RSI Trends vert
        if up and self.rt[t] != -1:
            s_ = next((x for x in sup if (c - x[0]) / c <= NEAR or l <= x[0] * 1.005), None)
            if s_ and (s_[2] == "S" or self.rt[t] == 1):
                out.append(dict(ctx, k="rebond", lv=round(s_[0], 4), tf=s_[2], n=s_[1], rt=bool(self.rt[t] == 1),
                                fort=bool(s_[2] == "S" and self.rt[t] == 1)))
        # alertes (pour une position ouverte)
        bs = [x for x in psup if c < x[0] * (1 - BREAK) and self.c[t - 1] >= x[0]]
        if bs:
            x = min(bs, key=lambda y: y[0])
            out.append({"k": "sup_casse", "lv": round(x[0], 4), "tf": x[2], "n": x[1]})
        if c < ma200 and self.c[t - 1] >= self.ma200[t - 1]:
            out.append({"k": "sous_mm200", "lv": round(float(ma200), 4)})
        if self.rt[t] == -1 and self.rt[t - 1] != -1:
            out.append({"k": "rt_rouge"})
        return out


def score(sig):
    """Note : cassure 3, rebond 2, +1 si la situation est « forte » ; 0 = rien à regarder."""
    return sum((3 if g["k"] == "cassure" else 2) + (1 if g.get("fort") else 0) for g in sig if g["k"] in BULL)


def today(rows):
    """Situations de la dernière séance (pour le calcul du soir)."""
    if len(rows) < 260:
        return []
    s = Series(rows)
    t = len(rows) - 1
    return s.at(t)


def build(allrows, days=5):
    """Fichier du soir : situations des `days` dernières séances de chaque valeur (la plus récente d'abord)."""
    items = []
    for sym, rows in allrows.items():
        if len(rows) < 260:
            continue
        s = Series(rows)
        n = len(rows)
        for t in range(n - 1, max(210, n - days) - 1, -1):
            sig = s.at(t)
            if not sig:
                continue
            items.append({"sym": sym, "date": rows[t][0], "age": n - 1 - t, "close": rows[t][4],
                          "last": rows[-1][4], "score": score(sig), "sig": sig})
    return items
