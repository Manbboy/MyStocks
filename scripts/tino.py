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
    """Zones de prix (lo, hi) : regroupement des extrêmes mensuels (plus hauts des sommets, plus bas des creux) qui se répètent.
    Comme Tino, la zone se cale sur les mèches qui butent au même endroit, pas sur les corps des bougies."""
    if len(rows) < 24:
        return []
    piv = _pivots(rows, k)
    pts = [((rows[i][2] if t == "H" else rows[i][3]), rows[i][0], t) for i, t in piv]
    if BODY:                                   # aussi le corps (haut du corps d'un sommet, bas du corps d'un creux)
        pts += [((max(rows[i][1], rows[i][4]) if t == "H" else min(rows[i][1], rows[i][4])), rows[i][0], t) for i, t in piv]
    pts.sort()
    clusters = []
    for x, d, t in pts:       # extrêmes à moins de GAP les uns des autres, zone pas plus large que wmax
        c = clusters[-1] if clusters else None
        if c and x <= c["px"][-1] * (1 + GAP) and x / c["px"][0] <= wmax:
            c["px"].append(x); c["piv"].append((d, t, x))
        else:
            clusters.append({"px": [x], "piv": [(d, t, x)]})
    out = []
    for c in clusters:
        n = len({p[0] for p in c["piv"]})          # contacts = pivots distincts
        if n < 2:
            continue
        lo, hi = c["px"][0] * (1 - PAD), c["px"][-1] * (1 + PAD)
        if hi / lo < 1 + MINW:                      # épaisseur minimale
            m = (hi + lo) / 2
            lo, hi = m / (1 + MINW / 2), m * (1 + MINW / 2)
        dates = sorted(p[0] for p in c["piv"])
        kinds = {p[1] for p in c["piv"]}
        out.append({"lo": round(lo, 4), "hi": round(hi, 4), "n": n, "polar": len(kinds) == 2,
                    "from": dates[0], "lastHit": dates[-1], "span": _months(dates[0], dates[-1]),
                    "role": "sup" if hi < last else ("res" if lo > last else "in")})
    return out


def _months(a, b):
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7])


PIERCE, PREFER = 0.10, "long"


def _is_low(rows, i, k=2):
    """creux local (plus bas des k mois de part et d'autre) : un contact = un creux qui vient sur la droite, pas chaque mois"""
    lo = rows[i][3]
    return all(rows[j][3] >= lo for j in range(max(0, i - k), min(len(rows), i + k + 1)))
GAP, PAD, MINW, MINSPAN, MINSCORE, NSUP, NEAR_SCORE, BODY = 0.04, 0.02, 0.05, 12, 0, 3, 3.5, False


def zones_body(rows, last, k=3, wmax=1.30):
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
                    "from": first, "lastHit": lastp, "span": _months(first, lastp), "role": "sup" if hi < last else ("res" if lo > last else "in")})
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
    # droites entre deux sommets de l'enveloppe (pas forcément voisins, comme Tino qui relie 2020, 2022 et 2026 d'un seul trait) :
    # les creux intermédiaires peuvent la percer de PIERCE au plus
    pairs = [(a, b) for x, a in enumerate(hull) for b in hull[x + 1:]]
    allc = []
    for a, b in pairs:
        if b[0] - a[0] < span or b[1] <= a[1]:        # assez longue, et montante
            continue
        m = (b[1] - a[1]) / (b[0] - a[0])
        line = lambda i: a[1] + m * (i - a[0])
        if any(rows[i][3] < line(i) * (1 - PIERCE) for i in range(a[0], n)):
            continue
        now = line(n - 1)
        if now <= 0 or now < 0.2 * rows[-1][4]:      # trop loin sous le cours : sans intérêt
            continue
        # contacts : creux mensuels à moins de 5 % au-dessus de la droite (ou qui la percent un peu)
        touch = [i for i in range(max(a[0], n - recent), n) if rows[i][3] <= line(i) * 1.05 and _is_low(rows, i)]
        # le plus de contacts, puis la plus longue (la droite qui « travaille » le plus longtemps)
        full = sum(1 for i in range(a[0], n) if rows[i][3] <= line(i) * 1.05 and _is_low(rows, i))
        cand = {"i1": a[0], "i2": b[0], "p1": a[1], "m": m, "touch": len(touch), "full": full, "now": now,
                "key": (len(touch), b[0]) if PREFER == "recent" else (len(touch), b[0] - a[0])}
        allc.append(cand)
        if best is None or cand["key"] > best["key"]:
            best = cand
    if not best:
        return None
    def pack(c):
        i1, m = c["i1"], c["m"]
        val = lambda i: c["p1"] + m * (i - i1)
        return {"t1": rows[i1][0], "p1": round(c["p1"], 4), "t2": rows[c["i2"]][0], "p2": round(val(c["i2"]), 4),
                "now": round(val(n - 1), 4), "slope": m, "touches": c["touch"], "_n": n, "_i1": i1}
    out = pack(best)
    # seconde oblique : une autre droite solide (≥ 3 contacts) qui passe nettement ailleurs aujourd'hui (comme les deux droites de Tino sur Vinci)
    # (autre point de départ, à 3 ans au moins ; contacts comptés sur toute sa longueur)
    alt = [c for c in allc if c["full"] >= 3 and abs(c["i1"] - best["i1"]) >= 36 and abs(c["now"] / best["now"] - 1) > 0.10
           and c["now"] >= 0.3 * rows[-1][4]]
    if alt:
        a2 = max(alt, key=lambda c: (c["full"], c["i2"] - c["i1"]))
        out["alt"] = pack(a2); out["alt"]["touches"] = a2["full"]
    return out


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
    if not best or line(n - 1) + best[0] > 1.6 * rows[-1][4]:     # trop haut au-dessus du cours : sans intérêt
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
    # zones de soutien : les plus solides d'abord (contacts, changement de rôle, durée), sans chevauchement, puis triées par prix
    cand = [z for z in zs if (z["hi"] < last * 0.995 or z["role"] == "in") and z["hi"] >= last * 0.25 and z["span"] >= MINSPAN
            and (z["role"] != "in" or z["n"] >= 4)]
    score = lambda z: z["n"] + (1.5 if z["polar"] else 0) + min(z["span"] / 60, 2)
    keep = []
    near = [z for z in sorted(cand, key=lambda z: -z["hi"]) if score(z) >= NEAR_SCORE]
    if near:
        keep.append(near[0])                          # d'abord la zone solide la plus proche sous le cours
    for z in sorted(cand, key=score, reverse=True):
        if score(z) < MINSCORE:
            continue
        if any(z["lo"] < k["hi"] * 1.03 and z["hi"] > k["lo"] * 0.97 for k in keep):
            continue
        keep.append(z)
        if len(keep) == NSUP:
            break
    if len(keep) < 2:          # trop peu de zones sur les mèches : on complète avec les zones bâties sur les corps (ancien calcul)
        zb = zones_body(rows, last, p["k"], p["wmax"])
        for z in sorted([z for z in zb if z["hi"] < last * 0.995 and z["hi"] >= last * 0.25 and z["span"] >= MINSPAN and z["n"] >= 2], key=score, reverse=True):
            if any(z["lo"] < k["hi"] * 1.03 and z["hi"] > k["lo"] * 0.97 for k in keep):
                continue
            keep.append(z)
            if len(keep) == 2:
                break
    keep.sort(key=lambda z: -z["hi"])
    res = []
    top = max([z["hi"] for z in keep], default=0)
    for z in sorted([z for z in zs if z["hi"] > last * 1.005 and z["n"] >= 2 and z["role"] != "in" and z["span"] >= MINSPAN], key=lambda z: z["lo"]):
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
        if ob.get("alt"):                 # seconde oblique (plus fine sur le graphique)
            a2 = ob["alt"]
            out["obl2"] = {k: a2[k] for k in ("t1", "p1", "t2", "p2", "now", "touches")}
            out["obl2"]["end"] = o["end"]
            out["obl2"]["pend"] = round(a2["p1"] + a2["slope"] * (a2["_n"] - 1 + p["ext"] - a2["_i1"]), 4)
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
