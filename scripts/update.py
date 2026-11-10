"""
Met à jour les données de la page « Mes actions ».

- Lit portfolios.json
- Télécharge tout l'historique disponible (Yahoo Finance, via yfinance) :
  10 ans en journalier + tout l'historique en mensuel (pour les moyennes mobiles longues)
- Calcule les supports et résistances
- Écrit data/summary.json et data/series/<symbole>.json

Usage :
    python scripts/update.py          # données réelles
    python scripts/update.py --demo   # données simulées (test hors ligne)
"""
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SERIES = DATA / "series"

MAX_LEVELS = 3          # niveaux affichés de chaque côté du cours
MIN_TOUCHES = 2         # un niveau doit avoir été touché au moins 2 fois

# Paramètres par échelle de temps :
#   lookback = nombre de chandeliers analysés, window = un sommet/creux doit dominer
#   ce nombre de chandeliers de chaque côté, pct = écart max. entre deux contacts d'un même niveau
TIMEFRAMES = {
    "D": {"rule": None, "lookback": 250, "window": 5, "pct": 0.02, "label": "1 an de séances"},
    "W": {"rule": "W", "lookback": 156, "window": 3, "pct": 0.02,  "label": "3 ans de semaines"},
    "M": {"rule": "M", "lookback": 120, "window": 2, "pct": 0.02,  "label": "10 ans de mois"},
    "Q": {"rule": "Q", "lookback": 40,  "window": 1, "pct": 0.02,  "label": "10 ans de trimestres"},
}


def safe_name(sym: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", sym)


def atr(df: pd.DataFrame, n: int = 14) -> float:
    h, l, c = df["High"], df["Low"], df["Close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    v = tr.rolling(n).mean().iloc[-1]
    return float(v) if not math.isnan(v) else float((h - l).mean())


def resample(df: pd.DataFrame, rule):
    """Regroupe les séances en chandeliers semaine / mois / trimestre."""
    if rule is None:
        return df.reset_index(drop=True)
    dt = pd.to_datetime(df["Date"])
    key = dt.dt.to_period(rule)
    g = df.groupby(key, sort=True)
    out = pd.DataFrame({
        "Date": g["Date"].first(),
        "Open": g["Open"].first(),
        "High": g["High"].max(),
        "Low": g["Low"].min(),
        "Close": g["Close"].last(),
        "Volume": g["Volume"].sum(),
    })
    return out.reset_index(drop=True)


def support_resistance(df: pd.DataFrame, lookback: int, window: int, pct: float):
    """Repère les sommets et creux répétés et les regroupe en niveaux."""
    d = df.tail(lookback).reset_index(drop=True)
    n = len(d)
    if n < window * 2 + 3:
        return [], []
    price = float(d["Close"].iloc[-1])
    tol = pct * price   # même règle que le curseur « Précision des contacts » de la page (2 % par défaut)

    w = window
    pivots = []  # (prix, index, "H" sommet / "L" creux)
    highs, lows = d["High"].values, d["Low"].values
    for i in range(w, n - w):
        if highs[i] == highs[i - w:i + w + 1].max():
            pivots.append((float(highs[i]), i, "H"))
        if lows[i] == lows[i - w:i + w + 1].min():
            pivots.append((float(lows[i]), i, "L"))

    def cluster(items):
        """Regroupe les pivots proches (à tol près) en niveaux d'au moins MIN_TOUCHES contacts."""
        clusters = []
        for p, i, kind in sorted(items):
            if clusters and abs(p - clusters[-1]["mean"]) <= tol:
                c = clusters[-1]
                c["prices"].append(p); c["idx"].append(i); c["kinds"].append(kind)
                c["mean"] = sum(c["prices"]) / len(c["prices"])
            else:
                clusters.append({"prices": [p], "idx": [i], "kinds": [kind], "mean": p})
        out = []
        for c in clusters:
            if len(c["prices"]) < MIN_TOUCHES:
                continue
            hits = sorted(zip(c["idx"], c["prices"], c["kinds"]))
            out.append({
                "price": round(c["mean"], 4),
                "touches": len(c["prices"]),
                "last": str(d["Date"].iloc[max(c["idx"])])[:10],
                "tol": round(tol, 4),
                "hits": [[str(d["Date"].iloc[i])[:10], round(p, 4), k] for i, p, k in hits],
            })
        return out

    # Mode strict : support = creux répétés (rebond vers le haut), résistance = sommets répétés (rejet vers le bas)
    sup_levels = [l for l in cluster([x for x in pivots if x[2] == "L"]) if l["price"] < price]
    res_levels = [l for l in cluster([x for x in pivots if x[2] == "H"]) if l["price"] > price]

    supports = sorted(sup_levels, key=lambda l: -l["price"])[:MAX_LEVELS]
    resistances = sorted(res_levels, key=lambda l: l["price"])[:MAX_LEVELS]

    # S'il n'y a aucun niveau répété d'un côté, on montre l'extrême de la période
    if not supports:
        i = int(d["Low"].idxmin())
        if d["Low"].iloc[i] < price:
            supports = [{"price": round(float(d["Low"].iloc[i]), 4), "touches": 1, "last": str(d["Date"].iloc[i])[:10], "extreme": True,
                         "tol": round(tol, 4), "hits": [[str(d["Date"].iloc[i])[:10], round(float(d["Low"].iloc[i]), 4), "L"]]}]
    if not resistances:
        i = int(d["High"].idxmax())
        if d["High"].iloc[i] > price:
            resistances = [{"price": round(float(d["High"].iloc[i]), 4), "touches": 1, "last": str(d["Date"].iloc[i])[:10], "extreme": True,
                            "tol": round(tol, 4), "hits": [[str(d["Date"].iloc[i])[:10], round(float(d["High"].iloc[i]), 4), "H"]]}]
    return supports, resistances


def all_levels(df: pd.DataFrame):
    out = {}
    for tf, p in TIMEFRAMES.items():
        sup, res = support_resistance(resample(df, p["rule"]), p["lookback"], p["window"], p["pct"])
        out[tf] = {"supports": sup, "resistances": res, "from": str(resample(df, p["rule"]).tail(p["lookback"])["Date"].iloc[0])[:10]}
    return out


def fetch_real(sym: str):
    import yfinance as yf
    t = yf.Ticker(sym)
    df = t.history(period="max", interval="1d", auto_adjust=False)   # cours réels (ajustés des divisions, pas des dividendes), comme TradingView
    if df is None or df.empty:
        raise RuntimeError("aucune donnée")
    df = df.reset_index()
    df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
    currency = None
    try:
        currency = t.fast_info.get("currency")
    except Exception:
        pass
    return df[["Date", "Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"]), currency


def fetch_demo(sym: str):
    """Cours simulés (marche aléatoire avec zones de rebond) pour tester hors ligne."""
    rng = np.random.default_rng(abs(hash(sym)) % (2**32))
    days = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=6000)
    base = rng.uniform(10, 400)
    x = np.cumsum(rng.normal(0, 0.015, len(days)))
    x += 0.15 * np.sin(np.linspace(0, 12, len(days)))
    close = base * np.exp(x)
    high = close * (1 + rng.uniform(0, 0.015, len(days)))
    low = close * (1 - rng.uniform(0, 0.015, len(days)))
    opn = np.r_[close[0], close[:-1]]
    df = pd.DataFrame({"Date": days.strftime("%Y-%m-%d"), "Open": opn, "High": np.maximum(high, opn),
                       "Low": np.minimum(low, opn), "Close": close, "Volume": rng.integers(1e5, 5e6, len(days))})
    return df, "EUR" if "." in sym else "USD"


def main():
    demo = "--demo" in sys.argv
    fetch = fetch_demo if demo else fetch_real
    cfg = json.loads((ROOT / "portfolios.json").read_text(encoding="utf-8"))
    symbols = sorted({it["yahoo"] for p in cfg["portfolios"] for it in p["items"]})

    SERIES.mkdir(parents=True, exist_ok=True)
    summary = {"timeframes": {k: v["label"] for k, v in TIMEFRAMES.items()}, "updated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "demo": demo, "symbols": {}}
    errors = []

    for sym in symbols:
        try:
            df, currency = fetch(sym)
            if len(df) < 2:
                raise RuntimeError("historique trop court")
            monthly = resample(df, "M")
            cutoff = (pd.Timestamp.today() - pd.DateOffset(years=10)).strftime("%Y-%m-%d")
            df = df[df["Date"] >= cutoff].reset_index(drop=True)
            last, prev = float(df["Close"].iloc[-1]), float(df["Close"].iloc[-2])
            levels = all_levels(df)
            sup, res = levels["D"]["supports"], levels["D"]["resistances"]
            rows = [[r.Date, round(r.Open, 4), round(r.High, 4), round(r.Low, 4), round(r.Close, 4), int(r.Volume or 0)]
                    for r in df.itertuples()]
            fname = safe_name(sym) + ".json"
            long_rows = [[r.Date, round(r.Open, 4), round(r.High, 4), round(r.Low, 4), round(r.Close, 4), int(r.Volume or 0)]
                         for r in monthly.itertuples()]
            (SERIES / fname).write_text(json.dumps({"symbol": sym, "rows": rows, "long": long_rows}, separators=(",", ":")), encoding="utf-8")
            summary["symbols"][sym] = {
                "file": "series/" + fname,
                "date": df["Date"].iloc[-1],
                "last": round(last, 4),
                "change": round(last - prev, 4),
                "changePct": round((last / prev - 1) * 100, 2) if prev else None,
                "currency": currency,
                "supports": sup,
                "resistances": res,
                "levels": levels,
            }
            print(f"OK   {sym:10s} {last:>10.2f}  " + "  ".join(f"{tf}:{len(v['supports'])}S/{len(v['resistances'])}R" for tf, v in levels.items()))
        except Exception as e:
            errors.append(sym)
            summary["symbols"][sym] = {"error": str(e)[:200]}
            print(f"ERR  {sym:10s} {e}")

    (DATA / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(symbols) - len(errors)}/{len(symbols)} actions mises à jour.")
    if errors:
        print("En erreur :", ", ".join(errors))


if __name__ == "__main__":
    main()
