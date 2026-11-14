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


def zones(rows, last):
    """Zones de prix (lo, hi) bâties sur les sommets et creux mensuels qui se regroupent."""
    if len(rows) < 24:
        return []
    piv = _pivots(rows, 3)
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
        if merged and b["lo"] <= merged[-1]["hi"] * 1.02 and (max(merged[-1]["hi"], b["hi"]) / min(merged[-1]["lo"], b["lo"])) < 1.30:
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


def oblique(rows, last_date):
    """Oblique longue de support : arête de l'enveloppe basse des creux mensuels, couvrant au moins 3 ans et la plus récente."""
    n = len(rows)
    if n < 48:
        return None
    start = max(0, n - 240)              # 20 dernières années
    pts = [(i, rows[i][3]) for i in range(start, n)]
    hull = []
    for p in pts:                       # enveloppe convexe basse (monotone chain)
        while len(hull) >= 2 and (hull[-1][0] - hull[-2][0]) * (p[1] - hull[-2][1]) - (hull[-1][1] - hull[-2][1]) * (p[0] - hull[-2][0]) <= 0:
            hull.pop()
        hull.append(p)
    best = None
    for a, b in zip(hull, hull[1:]):
        if b[0] - a[0] < 48 or b[1] <= a[1]:          # au moins 4 ans, et montante
            continue
        m = (b[1] - a[1]) / (b[0] - a[0])
        now = a[1] + m * (n - 1 - a[0])
        if now <= 0 or now < 0.2 * rows[-1][4]:      # trop loin sous le cours : sans intérêt
            continue
        # contacts : creux mensuels à moins de 5 % au-dessus de la droite
        touch = [i for i in range(a[0], n) if rows[i][3] <= (a[1] + m * (i - a[0])) * 1.05]
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


def _add_months(d, k):
    y, mo = int(d[:4]), int(d[5:7]) - 1 + k
    return f"{y + mo // 12:04d}-{mo % 12 + 1:02d}-01"


def analyse(rows):
    """Résumé pour summary.json : zones de support sous le cours (2 ou 3), résistance au-dessus, oblique, cible."""
    if not rows or len(rows) < 24:
        return None
    last = rows[-1][4]
    zs = zones(rows, last)
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
    res = sorted([z for z in zs if z["lo"] > last * 1.005 and z["n"] >= 2], key=lambda z: z["lo"])[:1]
    ob = oblique(rows, rows[-1][0])
    out = {"zones": [{"lo": z["lo"], "hi": z["hi"], "n": z["n"], "from": z["from"], "in": z["role"] == "in"} for z in keep],
           "res": [{"lo": z["lo"], "hi": z["hi"], "n": z["n"], "from": z["from"]} for z in res]}
    if ob:
        o = {k: ob[k] for k in ("t1", "p1", "t2", "p2", "now", "touches")}
        o["end"] = _add_months(rows[-1][0], 36)
        o["pend"] = round(ob["p1"] + ob["slope"] * (ob["_n"] - 1 + 36 - ob["_i1"]), 4)
        out["obl"] = o
        # cible : premier mois (dans les 10 ans) où l'oblique entre dans une zone de support
        if ob["slope"] > 0:
            for z in keep:
                if ob["now"] >= z["lo"]:
                    continue
                k = math.ceil((z["lo"] - ob["now"]) / ob["slope"])
                if 0 < k <= 120:
                    out["target"] = {"date": _add_months(rows[-1][0], k), "lo": z["lo"], "hi": z["hi"]}
                    o["end"] = _add_months(rows[-1][0], max(36, k + 12))
                    o["pend"] = round(ob["p1"] + ob["slope"] * (ob["_n"] - 1 + max(36, k + 12) - ob["_i1"]), 4)
                    break
    z0 = out["zones"][0] if out["zones"] else None
    if z0:
        out["dist"] = 0.0 if z0["in"] else round((z0["hi"] / last - 1) * 100, 1)
    return out
