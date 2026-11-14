"""Indicateur « Tino » (inspiré des analyses mensuelles de Tino, Le Podcast de la Bourse).

Sur tout l'historique mensuel :
- zones : bandes de prix formées par plusieurs sommets / creux mensuels voisins (anciens plafonds de consolidation,
  anciens creux) ; une zone franchie change de rôle (résistance devenue support) ;
- oblique longue : droite passant sous les creux majeurs (enveloppe basse), prolongée dans le futur ;
- cible : moment où l'oblique (montante) atteindra une zone de support.
Rows : [date "YYYY-MM-DD", open, high, low, close, volume] en mensuel.
"""
import math


def _pivots(rows, k):
    """Sommets / creux mensuels : plus haut (plus bas) sur k mois de part et d'autre."""
    out = []
    n = len(rows)
    for i in range(n):
        lo, hi = max(0, i - k), min(n, i + k + 1)
        h, l = rows[i][2], rows[i][3]
        if h >= max(r[2] for r in rows[lo:hi]) and i - lo >= min(k, i) and hi - i - 1 >= min(k, n - 1 - i):
            out.append((i, "H"))
        if l <= min(r[3] for r in rows[lo:hi]) and i - lo >= min(k, i) and hi - i - 1 >= min(k, n - 1 - i):
            out.append((i, "L"))
    return out


P = {"M": {"k": 3, "win": 240, "span": 48, "ext": 36, "hor": 120, "wmax": 1.30, "dwin": 72, "dspan": 12},      # mensuel : 20 ans, oblique sur 4 ans au moins
     "W": {"k": 4, "win": 260, "span": 39, "ext": 52, "hor": 104, "wmax": 1.20, "dwin": 104, "dspan": 13}}      # hebdomadaire : 5 ans, oblique sur 9 mois au moins


def zones(rows, last, k=3, wmax=1.30):
    """Zones de prix (lo, hi) bâties sur les sommets et creux mensuels qui se regroupent."""
    if len(rows) < 24:
        return []
    piv = _pivots(rows, k)
    bands = []
    for i, t in piv:
        o, h, l, c = rows[i][1], rows[i][2], rows[i][3], rows[i][4]
        if t == "H":
            top, bot = h, max(o, c)
        else:
            top, bot = min(o, c), l
        mid = (top + bot) / 2
        # épaisseur : mèche + corps proche, bornée entre 3 % et 12 % du prix
        th = max(top - bot, 0.03 * mid)
        th = min(th, 0.12 * mid)
        bands.append({"lo": mid - th / 2, "hi": mid + th / 2, "piv": [(rows[i][0], t, h if t == "H" else l)]})
    bands.sort(key=lambda b: b["lo"])
    merged = []
    for b in bands:      # regroupe les bandes qui se chevauchent (à 2 % près)
        if merged and b["lo"] <= merged[-1]["hi"] * 1.02 and (max(merged[-1]["hi"], b["hi"]) / min(merged[-1]["lo"], b["lo"])) < wmax:
            m = merged[-1]
            m["lo"], m["hi"] = min(m["lo"], b["lo"]), max(m["hi"], b["hi"])
            m["piv"] += b["piv"]
        else:
            merged.append({"lo": b["lo"], "hi": b["hi"], "piv": list(b["piv"])})
    out = []
    for m in merged:
        n = len(m["piv"])
        kinds = {p[1] for p in m["piv"]}
        if n < 2:
            continue
        # resserre la zone sur les prix des contacts (sommets / creux) si elle est trop large
        px = sorted(p[2] for p in m["piv"])
        lo, hi = m["lo"], m["hi"]
        if hi / lo > 1.18:
            lo, hi = max(lo, px[0] * 0.985), min(hi, px[-1] * 1.015)
            if hi / lo < 1.03:
                c = (hi + lo) / 2
                lo, hi = c * 0.985, c * 1.015
        first = min(p[0] for p in m["piv"])
        lastp = max(p[0] for p in m["piv"])
        out.append({"lo": round(lo, 4), "hi": round(hi, 4), "n": n, "polar": len(kinds) == 2,
                    "from": first, "lastHit": lastp, "role": "sup" if hi < last else ("res" if lo > last else "in")})
    return out


def oblique(rows, last_date, win=240, span=48, recent=120):
    """Oblique longue de support : arête de l'enveloppe basse des creux mensuels, couvrant au moins 3 ans et la plus récente."""
    n = len(rows)
    if n < 48:
        return None
    start = max(0, n - win)
    pts = [(i, rows[i][3]) for i in range(start, n)]
    hull = []
    for p in pts:                       # enveloppe convexe basse (monotone chain)
        while len(hull) >= 2 and (hull[-1][0] - hull[-2][0]) * (p[1] - hull[-2][1]) - (hull[-1][1] - hull[-2][1]) * (p[0] - hull[-2][0]) <= 0:
            hull.pop()
        hull.append(p)
    best = None
    for a, b in zip(hull, hull[1:]):
        if b[0] - a[0] < span or b[1] <= a[1]:        # assez longue, et montante
            continue
        m = (b[1] - a[1]) / (b[0] - a[0])
        now = a[1] + m * (n - 1 - a[0])
        if now <= 0 or now < 0.2 * rows[-1][4]:      # trop loin sous le cours : sans intérêt
            continue
        # contacts : creux mensuels à moins de 5 % au-dessus de la droite
        touch = [i for i in range(max(a[0], n - recent), n) if rows[i][3] <= (a[1] + m * (i - a[0])) * 1.05]
        cand = {"i1": a[0], "i2": b[0], "p1": a[1], "m": m, "touch": len(touch), "now": now}
        # le plus de contacts (la droite « travaille » le plus longtemps), puis la plus récente
        if best is None or (len(touch), b[0]) > (best["touch"], best["i2"]):
            best = cand
    if not best:
        return None
    i1, m = best["i1"], best["m"]
    val = lambda i: best["p1"] + m * (i - i1)
    return {"t1": rows[i1][0], "p1": round(best["p1"], 4), "t2": rows[best["i2"]][0], "p2": round(val(best["i2"]), 4),
            "now": round(val(n - 1), 4), "slope": m, "touches": best["touch"], "_n": n, "_i1": i1}


def channel(rows, ob, k=3):
    """Haut de canal : parallèle à l'oblique, posée sur le plus de sommets possible depuis le premier creux (canaux de Tino)."""
    if not ob:
        return None
    i1, p1, m, n = ob["_i1"], ob["p1"], ob["slope"], ob["_n"]
    line = lambda i: p1 + m * (i - i1)
    highs = [i for i, t in _pivots(rows, k) if t == "H" and i >= i1]
    best = None
    for c in highs:
        d = rows[c][2] - line(c)
        if d <= 0:
            continue
        top = lambda i: line(i) + d
        touch = [i for i in highs if abs(rows[i][2] - top(i)) <= 0.05 * top(i)]
        over = sum(1 for i in range(i1, n) if rows[i][4] > top(i) * 1.03)     # clôtures nettement au-dessus du canal
        if len(touch) < 2 or touch[-1] - touch[0] < 12 or over > 3:
            continue
        if best is None or (len(touch), d) > (best[1], best[0]):
            best = (d, len(touch))
    if not best:
        return None
    return {"d": round(best[0], 4), "now": round(line(n - 1) + best[0], 4), "touches": best[1]}


def downline(rows, win, span):
    """Oblique baissière : arête de l'enveloppe haute des sommets depuis le plus haut récent (droite qui coiffe les sommets)."""
    n = len(rows)
    start = max(0, n - win)
    ip = max(range(start, n), key=lambda i: rows[i][2])
    if n - 1 - ip < span:
        return None
    hull = []
    for p in [(i, rows[i][2]) for i in range(ip, n - 2)]:       # enveloppe convexe haute
        while len(hull) >= 2 and (hull[-1][0] - hull[-2][0]) * (p[1] - hull[-2][1]) - (hull[-1][1] - hull[-2][1]) * (p[0] - hull[-2][0]) >= 0:
            hull.pop()
        hull.append(p)
    best = None
    for a, b in zip(hull, hull[1:]):
        if b[0] - a[0] < span // 2 or b[1] >= a[1]:
            continue
        m = (b[1] - a[1]) / (b[0] - a[0])
        line = lambda i: a[1] + m * (i - a[0])
        now = line(n - 1)
        if now <= 0 or now > 1.6 * rows[-1][4]:           # trop haut au-dessus du cours : sans intérêt
            continue
        touch = [i for i in range(a[0], n) if rows[i][2] >= line(i) * 0.96]
        if best is None or (len(touch), b[0]) > (best["touches"], best["_j"]):
            best = {"t1": rows[a[0]][0], "p1": round(a[1], 4), "t2": rows[b[0]][0], "p2": round(b[1], 4), "now": round(now, 4),
                    "touches": len(touch), "broken": rows[-1][4] > now, "slope": m, "_i1": a[0], "_n": n, "_j": b[0]}
    return best


def ma200(rows):
    if len(rows) < 200:
        return None
    return sum(r[4] for r in rows[-200:]) / 200


def _add(d, k, unit):
    if unit == "W":
        import datetime as _dt
        return (_dt.date.fromisoformat(d[:10]) + _dt.timedelta(days=7 * k)).isoformat()
    return _add_months(d, k)


def _add_months(d, k):
    y, mo = int(d[:4]), int(d[5:7]) - 1 + k
    return f"{y + mo // 12:04d}-{mo % 12 + 1:02d}-01"


def analyse(rows, unit="M"):
    """Résumé pour summary.json : zones de support sous le cours (2 ou 3), résistance au-dessus, oblique, cible."""
    if not rows or len(rows) < 24:
        return None
    last = rows[-1][4]
    p = P[unit]
    zs = zones(rows, last, p["k"], p["wmax"])
    sup = sorted([z for z in zs if z["hi"] < last * 0.995 or z["role"] == "in"], key=lambda z: -z["hi"])
    # zones de support : on garde les plus marquantes (au moins 2 contacts), en évitant les zones collées
    keep = []
    for z in sup:
        if z["hi"] < last * 0.25:                      # trop loin sous le cours : sans intérêt
            continue
        if z["hi"] > last * 1.0 and z["role"] != "in":
            continue
        if z["role"] == "in" and z["n"] < 4:            # zone sous les pieds : seulement si elle est solide
            continue
        if keep and z["hi"] > keep[-1]["lo"] * 0.97:
            continue
        if z["n"] < 2 or (z["n"] < 3 and not z["polar"] and keep):
            continue
        keep.append(z)
        if len(keep) == 3:
            break
    res = []
    top = max([z["hi"] for z in keep], default=0)
    for z in sorted([z for z in zs if z["hi"] > last * 1.005 and z["n"] >= 2 and z["role"] != "in"], key=lambda z: z["lo"]):
        z = dict(z)
        if z["lo"] < top:                 # pas de chevauchement avec une zone de soutien
            z["lo"] = top
        if z["hi"] / z["lo"] >= 1.02 and z["lo"] > last * 1.005:
            res = [z]
            break
    ob = oblique(rows, rows[-1][0], p["win"], p["span"])
    out = {"zones": [{"lo": z["lo"], "hi": z["hi"], "n": z["n"], "from": z["from"], "in": z["role"] == "in"} for z in keep],
           "res": [{"lo": z["lo"], "hi": z["hi"], "n": z["n"], "from": z["from"]} for z in res]}
    if ob:
        o = {k: ob[k] for k in ("t1", "p1", "t2", "p2", "now", "touches")}
        o["end"] = _add(rows[-1][0], p["ext"], unit)
        o["pend"] = round(ob["p1"] + ob["slope"] * (ob["_n"] - 1 + p["ext"] - ob["_i1"]), 4)
        out["obl"] = o
        # cible : premier mois (dans les 10 ans) où l'oblique entre dans une zone de support
        if ob["slope"] > 0:
            for z in keep:
                if ob["now"] >= z["lo"]:
                    continue
                k = math.ceil((z["lo"] - ob["now"]) / ob["slope"])
                if 0 < k <= p["hor"]:
                    out["target"] = {"date": _add(rows[-1][0], k, unit), "lo": z["lo"], "hi": z["hi"]}
                    e = max(p["ext"], k + p["ext"] // 3)
                    o["end"] = _add(rows[-1][0], e, unit)
                    o["pend"] = round(ob["p1"] + ob["slope"] * (ob["_n"] - 1 + e - ob["_i1"]), 4)
                    break
    if ob:
        ch = channel(rows, ob, p["k"])
        if ch:
            out["chan"] = ch
    dl = downline(rows, p["dwin"], p["dspan"])
    if dl:
        e = p["ext"] // 2
        out["down"] = {k: dl[k] for k in ("t1", "p1", "t2", "p2", "now", "touches", "broken")}
        out["down"]["end"] = _add(rows[-1][0], e, unit)
        out["down"]["pend"] = round(max(dl["p1"] + dl["slope"] * (dl["_n"] - 1 + e - dl["_i1"]), 0), 4)
    mm = ma200(rows)
    if mm:
        out["mm"] = round(mm, 4)
        for z in out["zones"]:          # la MM200 passe dans la zone : soutien renforcé (Total, LVMH, Capgemini…)
            if z["lo"] * 0.97 <= mm <= z["hi"] * 1.03:
                z["mm"] = True
    z0 = out["zones"][0] if out["zones"] else None
    if z0:
        out["dist"] = 0.0 if z0["in"] else round((z0["hi"] / last - 1) * 100, 1)
    return out


def confluence(m, w):
    """Zones hebdomadaires qui chevauchent une zone mensuelle (ou que l'oblique mensuelle traverse aujourd'hui)."""
    if not m or not w:
        return []
    out = []
    for z in w.get("zones", []):
        hit = any(z["lo"] <= y["hi"] and y["lo"] <= z["hi"] for y in m.get("zones", []))
        ob = m.get("obl")
        on_obl = bool(ob and z["lo"] * 0.98 <= ob["now"] <= z["hi"] * 1.02)
        if hit or on_obl:
            out.append({"lo": z["lo"], "hi": z["hi"], "why": "zone" if hit else "oblique"})
    return out
