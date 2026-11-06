"""Prépare les documents du Poste de veille à partir des sources publiques.

Usage :
    python3 -I dashboard/refresh.py OUT_DIR [--config config.json]

Écrit dans OUT_DIR un fichier JSON par document de la base de l'artifact :
    markets__<id>.json      cours + historique 6 mois (Yahoo Finance, différé)
    feeds__news.json        titres Yahoo + 8-K SEC (via trader-news)
    feeds__congress.json    dernières déclarations du House Clerk (via trader-pelosi)
    feeds__meta.json        date de mise à jour et sources
La liste suivie vient de --config (le document config/watchlist de la base) ;
sans config, la liste par défaut ci-dessous sert de départ.
Bibliothèque standard uniquement. Aucune donnée personnelle n'est envoyée :
seuls les symboles boursiers partent vers Yahoo et la SEC.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(ROOT, ".claude", "skills")
UA = {"User-Agent": "Mozilla/5.0 (compatible; trader-skill/1.0)"}
SYM_RE = re.compile(r"^[A-Z0-9.\-^]{1,12}$")
DEFAULT = {"watchlist": ["AAPL", "AXP", "GOOGL", "KO", "BAC", "SGO.PA"], "indices": ["^FCHI", "^GSPC"]}


def doc_id(sym):
    return sym.replace("^", "idx-")


def chart(sym):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=6mo&interval=1d" % urllib.request.quote(sym)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        d = json.load(r)["chart"]["result"][0]
    m = d["meta"]
    closes = d["indicators"]["quote"][0]["close"]
    hist = [[time.strftime("%Y-%m-%d", time.gmtime(t)), round(c, 4)]
            for t, c in zip(d.get("timestamp", []), closes) if c is not None]
    return {"sym": sym, "name": m.get("longName") or m.get("shortName") or sym,
            "currency": m.get("currency"), "price": m.get("regularMarketPrice"),
            "prev": m.get("chartPreviousClose"), "high52": m.get("fiftyTwoWeekHigh"),
            "low52": m.get("fiftyTwoWeekLow"),
            "asof": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(m.get("regularMarketTime", 0))),
            "history": hist}


def run_json(args, timeout=180):
    out = subprocess.run([sys.executable, "-I"] + args, capture_output=True, timeout=timeout, cwd=ROOT)
    return json.loads(out.stdout.decode("utf-8") or "null")


def news(tickers, state_path):
    us = [t for t in tickers if "." not in t and not t.startswith("^")]
    if not us:
        return []
    d = run_json([os.path.join(SKILLS, "trader-news", "news.py"), "--tickers"] + us +
                 ["--hours", "72", "--json", "--state", state_path]) or {}
    keep = ("id", "source", "kind", "ticker", "title", "summary", "link", "time", "touches", "tags")
    items = [{k: i.get(k) for k in keep} for i in d.get("items", [])]
    for i in items:
        if i.get("summary"):
            i["summary"] = i["summary"][:260]
    items.sort(key=lambda i: i.get("time") or "", reverse=True)
    return items[:60]


def congress(pdf_dir, limit=10):
    ptr = os.path.join(SKILLS, "trader-pelosi", "ptr.py")
    index = run_json([ptr, "index", "--json", "--limit", str(limit)]) or []
    filings = []
    for f in index:
        try:
            rep = run_json([ptr, "fetch", f["doc_id"], "--json", "--pdf-dir", pdf_dir], timeout=90) or {}
        except Exception:
            continue
        rep = rep.get("report", rep)
        rows = [{k: r.get(k) for k in ("ticker", "asset", "type_name", "date", "amount", "owner_name")}
                for r in rep.get("rows", [])]
        filings.append({"doc_id": f["doc_id"], "name": f["name"], "district": f.get("district"),
                        "filed": f.get("filed"), "url": f.get("url"), "rows": rows})
    return filings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--config")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    cfg = DEFAULT
    if a.config and os.path.isfile(a.config):
        with open(a.config, encoding="utf-8") as fh:
            cfg = json.load(fh)
    syms = [s for s in (cfg.get("watchlist", []) + cfg.get("indices", [])) if SYM_RE.match(str(s))]
    errors = []
    for s in syms:
        try:
            doc = chart(s)
            with open(os.path.join(a.out, "markets__%s.json" % doc_id(s)), "w", encoding="utf-8") as fh:
                json.dump(doc, fh)
        except Exception as e:
            errors.append("%s: %s" % (s, e))
        time.sleep(0.4)
    state = os.path.join(ROOT, "trader", "state")
    os.makedirs(state, exist_ok=True)
    with open(os.path.join(a.out, "feeds__news.json"), "w", encoding="utf-8") as fh:
        json.dump({"items": news(cfg.get("watchlist", []), os.path.join(state, "dashboard-news.json"))}, fh)
    with open(os.path.join(a.out, "feeds__congress.json"), "w", encoding="utf-8") as fh:
        json.dump({"filings": congress(os.path.join(state, "ptr-pdfs"))}, fh)
    meta = {"updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "sources": ["Yahoo Finance (cours différés)", "Yahoo Finance RSS", "SEC EDGAR 8-K", "House Clerk PTR"],
            "errors": errors}
    with open(os.path.join(a.out, "feeds__meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh)
    print("ok: %d valeurs, erreurs: %s" % (len(syms) - len(errors), errors or "aucune"))


if __name__ == "__main__":
    main()
