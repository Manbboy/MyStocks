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
        # un groupe formé de proche en proche peut s'étirer au-delà de la précision : on ne garde que les points à moins de tol du niveau final
        for c in clusters:
            for _ in range(3):
                keep = [k for k, p in enumerate(c["prices"]) if abs(p - c["mean"]) <= tol]
                if not keep or len(keep) == len(c["prices"]):
                    break
                for key in ("prices", "idx", "kinds"):
                    c[key] = [c[key][k] for k in keep]
                c["mean"] = sum(c["prices"]) / len(c["prices"])
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


def rsi_trend_tail(closes, n: int = 14):
    """RSI de Wilder (même calcul que la page) : RSI des 2 dernières séances et moyennes
    gains/pertes + clôture des 2 dernières séances, pour recalculer le RSI du jour avec le cours en séance."""
    if len(closes) <= n + 2:
        return None
    g = l = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        g += max(d, 0); l += max(-d, 0)
    g /= n; l /= n
    hist = [(g, l)]
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        g = (g * (n - 1) + max(d, 0)) / n
        l = (l * (n - 1) + max(-d, 0)) / n
        hist.append((g, l))
    r = lambda gl: 100.0 if gl[1] == 0 else 100 - 100 / (1 + gl[0] / gl[1])
    return {"n": n, "r": [round(r(hist[-2]), 2), round(r(hist[-1]), 2)],
            "a": [[hist[-2][0], hist[-2][1], closes[-2]], [hist[-1][0], hist[-1][1], closes[-1]]]}


def all_levels(df: pd.DataFrame):
    out = {}
    for tf, p in TIMEFRAMES.items():
        sup, res = support_resistance(resample(df, p["rule"]), p["lookback"], p["window"], p["pct"])
        out[tf] = {"supports": sup, "resistances": res, "from": str(resample(df, p["rule"]).tail(p["lookback"])["Date"].iloc[0])[:10]}
    return out


KIND = {}
FX = "EURUSD=X"   # dollars pour 1 euro
EVENTS = {}   # dates de résultats et dividendes détachés, pour expliquer un mouvement du jour


def fetch_events(t, sym: str, df):
    """Résultats (passés récents et prochains) et dividendes détachés : seulement pour les actions."""
    ev = {}
    try:
        if "Dividends" in df.columns:
            d = df[df["Dividends"] > 0].tail(4)
            ev["div"] = [[r.Date, round(float(r.Dividends), 4)] for r in d.itertuples()]
    except Exception:
        pass
    if KIND.get(sym) not in (None, "EQUITY"):
        EVENTS[sym] = ev
        return
    today = pd.Timestamp.today().normalize()
    dates = set()
    try:
        ed = t.get_earnings_dates(limit=8)
        if ed is not None and not ed.empty:
            for x in ed.index:
                x = pd.Timestamp(x)
                dates.add(x.strftime("%Y-%m-%d") + ("*" if x.hour >= 16 else ""))    # * : publié après la clôture
    except Exception as e:
        print(f"  {sym}: dates de résultats indisponibles ({e})")
    if not dates:
        try:
            cal = t.calendar or {}
            for x in (cal.get("Earnings Date") or []):
                dates.add(pd.Timestamp(x).strftime("%Y-%m-%d"))
        except Exception:
            pass
    keep = [d for d in sorted(dates) if abs((pd.Timestamp(d[:10]) - today).days) <= 120]
    if keep:
        ev["earn"] = keep
    EVENTS[sym] = ev


def fetch_real(sym: str):
    import yfinance as yf
    t = yf.Ticker(sym)
    df = t.history(period="max", interval="1d", auto_adjust=False)   # cours réels (ajustés des divisions, pas des dividendes), comme TradingView
    if df is None or df.empty:
        raise RuntimeError("aucune donnée")
    df = df.reset_index()
    df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
    # l'historique complet de Yahoo publie souvent la dernière séance européenne avec un jour de retard :
    # on redemande les 5 derniers jours séparément et on complète / remplace les dernières lignes
    try:
        rec = t.history(period="5d", interval="1d", auto_adjust=False)
        if rec is not None and not rec.empty:
            rec = rec.reset_index()
            rec["Date"] = pd.to_datetime(rec["Date"]).dt.strftime("%Y-%m-%d")
            rec = rec.dropna(subset=["Close"])
            df = pd.concat([df[~df["Date"].isin(rec["Date"])], rec], ignore_index=True).sort_values("Date").reset_index(drop=True)
    except Exception as e:
        print(f"  {sym}: 5 derniers jours indisponibles ({e})")
    # plan B : si une séance récente manque encore, on la reconstitue à partir des cours horaires
    try:
        ih = t.history(period="5d", interval="60m", auto_adjust=False)
        if ih is not None and not ih.empty:
            ih = ih.dropna(subset=["Close"])
            ih["D"] = pd.to_datetime(ih.index).strftime("%Y-%m-%d")
            last = df["Date"].iloc[-1]
            add = []
            for d, g in ih.groupby("D"):
                if d > last:
                    add.append({"Date": d, "Open": g["Open"].iloc[0], "High": g["High"].max(), "Low": g["Low"].min(),
                                "Close": g["Close"].iloc[-1], "Volume": g["Volume"].sum()})
            if add:
                print(f"  {sym}: séance(s) reconstituée(s) depuis l'horaire : {', '.join(a['Date'] for a in add)}")
                df = pd.concat([df, pd.DataFrame(add)], ignore_index=True)
    except Exception as e:
        print(f"  {sym}: cours horaires indisponibles ({e})")
    currency = None
    try:
        currency = t.fast_info.get("currency")
    except Exception:
        pass
    try:   # type d'instrument (EQUITY, ETF, CRYPTOCURRENCY, INDEX, FUTURE…) : sert à regrouper les positions
        KIND[sym] = (t.history_metadata or {}).get("instrumentType")
    except Exception:
        pass
    try:
        fetch_events(t, sym, df)
    except Exception as e:
        print(f"  {sym}: événements indisponibles ({e})")
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
    symbols = sorted({it["yahoo"] for p in cfg["portfolios"] for it in p["items"]} | {FX})   # + taux EUR/USD (conversion du Portfolio en euros)

    SERIES.mkdir(parents=True, exist_ok=True)
    summary = {"timeframes": {k: v["label"] for k, v in TIMEFRAMES.items()}, "updated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "demo": demo, "symbols": {}}
    errors = []
    allrows = {}

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
            if sym != FX:
                allrows[sym] = rows          # le taux de change n'entre pas dans « À regarder »
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
                "type": KIND.get(sym),
                "supports": sup,
                "resistances": res,
                "levels": levels,
                "rt": rsi_trend_tail([r[4] for r in rows]),
                # variation journalière habituelle (écart type sur 60 séances, en %) : repère d'un mouvement inhabituel
                "vol": round(float(df["Close"].pct_change().tail(60).std() * 100), 2) if len(df) > 20 else None,
            }
            ev = EVENTS.get(sym) or {}
            if ev.get("earn"): summary["symbols"][sym]["earn"] = ev["earn"]
            if ev.get("div"): summary["symbols"][sym]["div"] = ev["div"]
            print(f"OK   {sym:10s} {last:>10.2f}  " + "  ".join(f"{tf}:{len(v['supports'])}S/{len(v['resistances'])}R" for tf, v in levels.items()))
        except Exception as e:
            errors.append(sym)
            summary["symbols"][sym] = {"error": str(e)[:200]}
            print(f"ERR  {sym:10s} {e}")

    (DATA / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    # situations « À regarder » des 5 dernières séances (+ résultats mesurés sur l'historique, s'ils existent)
    try:
        import signals
        stats_f = DATA / "signals_stats.json"
        stats = json.loads(stats_f.read_text(encoding="utf-8")) if stats_f.exists() else None
        sig = {"updated": summary["updated"], "items": signals.build(allrows), "stats": stats}
        (DATA / "signals.json").write_text(json.dumps(sig, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"Situations : {len(sig['items'])}")
    except Exception as e:
        print("ERR  situations :", e)
    print(f"\n{len(symbols) - len(errors)}/{len(symbols)} actions mises à jour.")
    if errors:
        print("En erreur :", ", ".join(errors))


if __name__ == "__main__":
    main()
