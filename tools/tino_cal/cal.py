import json, sys, math, importlib
import os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
import tino
from gt import GT
M = json.load(open(os.path.join(os.path.dirname(__file__), "monthly.json")))
def monthly(rows):
    rows = [r for r in rows if not any(isinstance(x, float) and math.isnan(x) for x in r[1:])]
    out = {}
    for d, o, h, l, c in rows:
        k = d[:7]
        if k not in out: out[k] = [k + "-01", o, h, l, c, 0]
        else:
            m = out[k]; m[2] = max(m[2], h); m[3] = min(m[3], l); m[4] = c
    return list(out.values())

def ov(a, b, tol=0.03):
    """a = notre zone, b = zone de Tino : centres proches et largeur comparable (pas de zone géante qui couvre tout)"""
    ma, mb = (a[0] + a[1]) / 2, (b[0] + b[1]) / 2
    near = b[0] * (1 - tol) <= ma <= b[1] * (1 + tol) or a[0] * (1 - tol) <= mb <= a[1] * (1 + tol)
    wa, wb = a[1] / a[0] - 1, b[1] / b[0] - 1
    return near and wa <= max(2 * wb, 0.10)
def score(verbose=False):
    tot = dict(near=0, nn=0, rec=0, nr=0, prec=0, np=0)
    for s, g in GT.items():
        rows = M[s]; last = rows[-1][4]
        a = tino.analyse(rows)
        ours = [(z["lo"], z["hi"]) for z in (a or {}).get("zones", [])]
        gs = [z for z in g["S"] if z[1] >= last * 0.25]
        if gs:
            tot["nn"] += 1
            near = max(gs, key=lambda z: z[1])
            hit = bool(ours) and ov(ours[0], near)
            tot["near"] += hit
        r = sum(any(ov(o, z) for o in ours) for z in gs); tot["rec"] += r; tot["nr"] += len(gs)
        p = sum(any(ov(o, z) for z in gs) for o in ours); tot["prec"] += p; tot["np"] += len(ours)
        if verbose:
            print(f"{s:9} last={last:<9.4g} tino={gs}  ours={[(round(x,3),round(y,3)) for x,y in ours]}  obl={(a or {}).get('obl',{}).get('now')}")
    return tot
if __name__ == "__main__":
    t = score(True); print(t, "near %.0f%% recall %.0f%% prec %.0f%%" % (100*t['near']/t['nn'], 100*t['rec']/t['nr'], 100*t['prec']/max(1,t['np'])))
