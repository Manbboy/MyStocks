"""
Mesure sur l'historique des situations de signals.py (toutes les valeurs de data/series).

Pour chaque situation détectée à la séance t : achat à l'ouverture de t+1, puis
rendement à 10 et 20 séances (clôture). Comparé à la référence : toutes les séances (et les séances en tendance haussière).
Écrit data/signals_stats.json.
"""
import json
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import signals as S

ROOT = Path(__file__).resolve().parent.parent
SER = ROOT / "data" / "series"
H1, H2 = 10, 20


def one(path):
    rows = json.load(open(path))["rows"]
    if len(rows) < 400:
        return None
    s = S.Series(rows)
    n = len(rows)
    ev, base, base_up = [], [], []
    for t in range(210, n - H2 - 1):
        sig = s.at(t)
        e = s.o[t + 1]                       # achat à l'ouverture du lendemain
        if not e or e <= 0:
            continue
        r1, r2 = s.c[t + H1] / e - 1, s.c[t + H2] / e - 1
        base.append((r1, r2))
        if s.c[t] > s.ma200[t] and s.ma50[t] > s.ma200[t]:
            base_up.append((r1, r2))
        for g in sig:
            ev.append((g["k"] + ("_fort" if g.get("fort") else ""), r1, r2, t))
        if any(g["k"] in S.BULL for g in sig):
            ev.append(("toutes", r1, r2, t))
    return ev, base, base_up


def stats(r):
    r = np.array(r)
    if not len(r):
        return None
    return {"n": int(len(r)), "moy": round(float(r.mean()) * 100, 2), "med": round(float(np.median(r)) * 100, 2),
            "pos": round(float((r > 0).mean()) * 100, 1)}


def main():
    files = sorted(SER.glob("*.json"))
    with Pool() as p:
        res = [x for x in p.map(one, files) if x]
    ev = [e for r in res for e in r[0]]
    base = [b for r in res for b in r[1]]
    up = [b for r in res for b in r[2]]
    out = {"valeurs": len(res), "seances": len(base),
           "ref": {"j10": stats([b[0] for b in base]), "j20": stats([b[1] for b in base])},
           "ref_hausse": {"j10": stats([b[0] for b in up]), "j20": stats([b[1] for b in up])}, "sit": {}}
    for k in sorted({x[0] for x in ev}):
        e = [x for x in ev if x[0] == k]
        out["sit"][k] = {"j10": stats([x[1] for x in e]), "j20": stats([x[2] for x in e])}
    (ROOT / "data" / "signals_stats.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
