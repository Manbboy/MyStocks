"""Ticker allemand (Stuttgart, sinon Francfort) des actions européennes des listes, pour les résumés de pré-ouverture
(échanges avant 9 h). Ne cherche que les valeurs nouvelles ; résultat dans data/de_tickers.json ("" = aucun trouvé)."""
import json, os, re, time, unicodedata, urllib.request, urllib.parse
ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(ROOT, "data", "de_tickers.json")
EU = re.compile(r"\.(PA|AS|BR|DE|MI|MC|SG|F|LS|IR|VI|HE|CO|ST|OL|SW|L)$")
def norm(t): return unicodedata.normalize("NFD", t.lower()).encode("ascii", "ignore").decode()
def search(name):
    u = "https://query2.finance.yahoo.com/v1/finance/search?" + urllib.parse.urlencode({"q": name, "quotesCount": 20, "newsCount": 0})
    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=20)).get("quotes", [])
def main():
    cfg = json.load(open(os.path.join(ROOT, "portfolios.json")))
    have = json.load(open(OUT)) if os.path.exists(OUT) else {}
    items = {i["yahoo"]: i["name"] for p in cfg["portfolios"] for i in p["items"] if EU.search(i["yahoo"])}
    for sym, name in items.items():
        if sym in have: continue
        if re.search(r"\.(SG|F)$", sym): have[sym] = sym; continue
        w = norm(re.split(r"[\s\-]", name)[0])
        try:
            q = [x for x in search(name) if x.get("quoteType") in ("EQUITY", "ETF") and w in norm(x.get("longname") or x.get("shortname") or "")]
            have[sym] = next((x["symbol"] for x in q if x.get("exchange") == "STU"), next((x["symbol"] for x in q if x.get("exchange") == "FRA"), ""))
        except Exception as e:
            print(sym, e); continue
        print(sym, name, "→", have[sym] or "—"); time.sleep(0.4)
    json.dump({k: have[k] for k in sorted(have) if k in items}, open(OUT, "w"), indent=0, ensure_ascii=False)
if __name__ == "__main__": main()
