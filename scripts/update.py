"""
Met à jour les données de la page « Mes actions ».

- Lit portfolios.json
- Télécharge 10 ans de cours journaliers par action (Yahoo Finance, via yfinance)
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

PIVOT_WINDOW = 5        # un sommet/creux doit dominer 5 séances de chaque côté
LOOKBACK = 250          # ~1 an de séances pour chercher les niveaux
MAX_LEVELS = 3          # niveaux affichés de chaque côté du cours
MIN_TOUCHES = 2         # un niveau doit avoir été touché au moins 2 fois


def safe_name(sym: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", sym)


def atr(df: pd.DataFrame, n: int = 14) -> float:
    h, l, c = df["High"], df["Low"], df["Close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    v = tr.rolling(n).mean().iloc[-1]
    return float(v) if not math.isnan(v) else float((h - l).mean())


def support_resistance(df: pd.DataFrame):
    """Repère les sommets et creux répétés et les regroupe en niveaux."""
    d = df.tail(LOOKBACK).reset_index(drop=True)
    n = len(d)
    if n < PIVOT_WINDOW * 2 + 5:
        return [], []
    price = float(d["Close"].iloc[-1])
    tol = max(0.012 * price, 0.6 * atr(d))

    w = PIVOT_WINDOW
    pivots = []  # (prix, index)
    highs, lows = d["High"].values, d["Low"].values
    for i in range(w, n - w):
        if highs[i] == highs[i - w:i + w + 1].max():
            pivots.append((float(highs[i]), i))
        if lows[i] == lows[i - w:i + w + 1].min():
            pivots.append((float(lows[i]), i))

    # Regroupement des pivots proches en un même niveau
    pivots.sort()
    clusters = []
    for p, i in pivots:
        if clusters and abs(p - clusters[-1]["mean"]) <= tol:
            c = clusters[-1]
            c["prices"].append(p)
            c["idx"].append(i)
            c["mean"] = sum(c["prices"]) / len(c["prices"])
        else:
            clusters.append({"prices": [p], "idx": [i], "mean": p})

    levels = []
    for c in clusters:
        touches = len(c["prices"])
        if touches < MIN_TOUCHES:
            continue
        last = max(c["idx"])
        levels.append({
            "price": round(c["mean"], 4),
            "touches": touches,
            "last": str(df.tail(LOOKBACK)["Date"].iloc[last])[:10],
            "recent": last >= n - 60,
        })

    supports = sorted([l for l in levels if l["price"] < price], key=lambda l: -l["price"])[:MAX_LEVELS]
    resistances = sorted([l for l in levels if l["price"] > price], key=lambda l: l["price"])[:MAX_LEVELS]

    # S'il n'y a aucun niveau répété d'un côté, on montre l'extrême sur 1 an
    if not supports:
        lo = float(d["Low"].min())
        if lo < price:
            supports = [{"price": round(lo, 4), "touches": 1, "last": str(df.tail(LOOKBACK)["Date"].iloc[int(d["Low"].idxmin())])[:10], "recent": False, "extreme": True}]
    if not resistances:
        hi = float(d["High"].max())
        if hi > price:
            resistances = [{"price": round(hi, 4), "touches": 1, "last": str(df.tail(LOOKBACK)["Date"].iloc[int(d["High"].idxmax())])[:10], "recent": False, "extreme": True}]
    return supports, resistances


def fetch_real(sym: str):
    import yfinance as yf
    t = yf.Ticker(sym)
    df = t.history(period="10y", interval="1d", auto_adjust=True)
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
    days = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=2500)
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
    summary = {"updated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "demo": demo, "symbols": {}}
    errors = []

    for sym in symbols:
        try:
            df, currency = fetch(sym)
            if len(df) < 2:
                raise RuntimeError("historique trop court")
            last, prev = float(df["Close"].iloc[-1]), float(df["Close"].iloc[-2])
            sup, res = support_resistance(df)
            rows = [[r.Date, round(r.Open, 4), round(r.High, 4), round(r.Low, 4), round(r.Close, 4), int(r.Volume or 0)]
                    for r in df.itertuples()]
            fname = safe_name(sym) + ".json"
            (SERIES / fname).write_text(json.dumps({"symbol": sym, "rows": rows}, separators=(",", ":")), encoding="utf-8")
            summary["symbols"][sym] = {
                "file": "series/" + fname,
                "date": df["Date"].iloc[-1],
                "last": round(last, 4),
                "change": round(last - prev, 4),
                "changePct": round((last / prev - 1) * 100, 2) if prev else None,
                "currency": currency,
                "supports": sup,
                "resistances": res,
            }
            print(f"OK   {sym:10s} {last:>10.2f}  S={[l['price'] for l in sup]}  R={[l['price'] for l in res]}")
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
