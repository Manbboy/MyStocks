"""Momentum : chaque fin de mois, les 10 actions (listes EU et US) qui ont le plus monté sur 6 mois (126 séances).

Backtest (fin 2017 - novembre 2026, 112 actions, frais 0,45 % par ordre) : +316 % (17,5 %/an) contre +135 % (10,2 %/an)
en gardant toutes les actions à parts égales ; meilleur sur 2018-2021 et sur 2022-2026. Voir help.html.
Écrit data/momentum.json : classement de la dernière fin de mois (à tenir ce mois-ci), celui de la fin de mois précédente
(entrées / sorties) et un aperçu au dernier cours (ce qui changerait si on reclassait aujourd'hui).
"""
import json, os, re, bisect

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
TOP, LB = 10, 126


def load():
    pf = json.load(open(os.path.join(ROOT, "portfolios.json"), encoding="utf-8"))["portfolios"]
    syms, names = [], {}
    for p in pf:
        if p["name"] not in ("EU", "US"):
            continue
        for it in p["items"]:
            y = it["yahoo"]
            if "=" in y or y.startswith("^") or "-USD" in y or y in names:
                continue
            syms.append(y); names[y] = it.get("name") or y
    summ = json.load(open(os.path.join(ROOT, "data", "summary.json"), encoding="utf-8"))["symbols"]
    S = {}
    for s in syms:
        f = (summ.get(s) or {}).get("file")
        if not f:
            continue
        try:
            rows = json.load(open(os.path.join(ROOT, "data", f), encoding="utf-8"))["rows"]
        except Exception:
            continue
        if len(rows) > LB + 30:
            S[s] = ([r[0] for r in rows], [r[4] for r in rows])
    return S, names


def rank(S, d):
    out = []
    for s, (ds, cs) in S.items():
        i = bisect.bisect_right(ds, d) - 1
        if i < LB or ds[i] < d[:7] + "-01":        # pas de cours ce mois-là : ignorée
            continue
        out.append((cs[i] / cs[i - LB] - 1, s, cs[i]))
    out.sort(reverse=True)
    return out


def main():
    S, names = load()
    dates = sorted({d for ds, _ in S.values() for d in ds})
    last = dates[-1]
    # fins de mois complètes : dernier jour de bourse de chaque mois terminé
    ends = [d for i, d in enumerate(dates[:-1]) if dates[i + 1][:7] != d[:7]]
    cur, prev = ends[-1], ends[-2]
    pack = lambda r: [{"sym": s, "name": names[s], "perf": round(v, 4), "close": round(c, 4)} for v, s, c in r[:TOP]]
    rc, rp, rn = rank(S, cur), rank(S, prev), rank(S, last)
    top_c, top_p, top_n = [x["sym"] for x in pack(rc)], [x["sym"] for x in pack(rp)], [x["sym"] for x in pack(rn)]
    out = {"asof": cur, "prev": prev, "last": last, "lookback": LB, "top": pack(rc),
           "in": [s for s in top_c if s not in top_p], "out": [{"sym": s, "name": names[s]} for s in top_p if s not in top_c],
           "now": pack(rn), "nowIn": [s for s in top_n if s not in top_c], "nowOut": [s for s in top_c if s not in top_n],
           "rank": {s: i + 1 for i, (_, s, _) in enumerate(rc)}, "n": len(rc)}
    json.dump(out, open(os.path.join(ROOT, "data", "momentum.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print("momentum", cur, [names[s] for s in top_c], "entrées", out["in"], "sorties", [x["sym"] for x in out["out"]])


if __name__ == "__main__":
    main()
