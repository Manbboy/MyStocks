"""Ticker allemand des actions européennes des listes, pour les résumés Telegram de pré-ouverture (échanges avant 9 h).
Pour chaque valeur : on rassemble toutes les cotations allemandes ouvertes dès 8 h que Yahoo connaît (Stuttgart, Francfort,
Berlin, Munich, Düsseldorf, Hambourg ; Xetra ouvre à 9 h, donc exclu) à partir de plusieurs recherches (nom, 1er mot du nom,
code de la valeur), on écarte celles dont le prix s'éloigne de plus de 15 % de celui de la place principale, et on garde
celle qui a eu le plus de bougies avant 9 h sur les 5 dernières séances (puis le plus de volume).
Résultat : data/de_tickers.json ("" = aucune cotation trouvée). Les valeurs déjà trouvées ne sont recherchées qu'avec --all."""
import json, os, re, sys, time, unicodedata, urllib.request, urllib.parse, datetime
from zoneinfo import ZoneInfo
ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(ROOT, "data", "de_tickers.json")
EU = re.compile(r"\.(PA|AS|BR|DE|MI|MC|SG|F|LS|IR|VI|HE|CO|ST|OL|SW|L)$")
EXCH = {"STU", "FRA", "BER", "MUN", "DUS", "HAM"}
BX = ZoneInfo("Europe/Brussels")
def get(u):
    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=20))
def norm(t): return unicodedata.normalize("NFD", t.lower()).encode("ascii", "ignore").decode()
def search(q):
    try: return get("https://query2.finance.yahoo.com/v1/finance/search?" + urllib.parse.urlencode({"q": q, "quotesCount": 50, "newsCount": 0})).get("quotes", [])
    except Exception: return []
def chart(sym, rng="5d", iv="5m"):
    try:
        r = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range={rng}&interval={iv}")["chart"]["result"][0]
        return r
    except Exception: return None
def pick(sym, name):
    ref = chart(sym, "5d", "1d")
    px = ref and ref["meta"].get("regularMarketPrice")
    if not px: return ""
    words = [w for w in re.split(r"[\s\-'’.]", norm(name)) if len(w) > 1]
    key = words[0] if words else norm(name)
    cands = {}
    for q in {name, name.split(" ")[0], sym.split(".")[0] + " " + name.split(" ")[0]}:
        for x in search(q):
            s = x.get("symbol", "")
            if x.get("exchange") in EXCH and x.get("quoteType") in ("EQUITY", "ETF") and key in norm(x.get("longname") or x.get("shortname") or ""):
                cands[s] = x.get("exchange")
        time.sleep(0.25)
    best, bscore = "", None
    for s in cands:
        c = chart(s, "5d", "5m"); time.sleep(0.2)
        if not c: continue
        m = c["meta"]; p = m.get("regularMarketPrice")
        if not p or m.get("currency") not in (None, "EUR") or abs(p / px - 1) > 0.15: continue
        ts = c.get("timestamp") or []; vol = ((c.get("indicators", {}).get("quote") or [{}])[0].get("volume")) or []
        pre = sum(1 for t in ts if datetime.datetime.fromtimestamp(t, BX).hour < 9)
        score = (pre, sum(v or 0 for v in vol))
        if bscore is None or score > bscore: best, bscore = s, score
    return best
def main():
    cfg = json.load(open(os.path.join(ROOT, "portfolios.json")))
    have = json.load(open(OUT)) if os.path.exists(OUT) else {}
    redo = "--all" in sys.argv
    items = {i["yahoo"]: i["name"] for p in cfg["portfolios"] for i in p["items"] if EU.search(i["yahoo"])}
    for sym, name in items.items():
        if not redo and have.get(sym): continue
        if re.search(r"\.(SG|F)$", sym): have[sym] = sym; continue
        have[sym] = pick(sym, name)
        print(sym, name, "→", have[sym] or "—", flush=True)
    json.dump({k: have.get(k, "") for k in sorted(items)}, open(OUT, "w"), indent=0, ensure_ascii=False)
if __name__ == "__main__": main()
