"""Calcule les signaux du Poste de veille, avec les mêmes règles que la page.

Usage :
    python3 -I dashboard/signals.py SEED_DIR CONFIG_JSON [--previous PREV_JSON] [--out OUT_JSON]

SEED_DIR : le dossier écrit par refresh.py. CONFIG_JSON : le document config/watchlist.
Affiche les signaux ; avec --previous, ne liste comme nouveaux que ceux absents
de la fois précédente (pour ne notifier qu'une fois).
"""
import argparse
import json
import os


def mean(xs):
    return sum(xs) / len(xs)


def ma_series(c, n):
    return [mean(c[i - n + 1:i + 1]) if i >= n - 1 else None for i in range(len(c))]


def fmt_pct(v):
    return ("+" if v > 0 else "") + ("%.1f" % v).replace(".", ",") + " %"


def compute(seed, cfg):
    out = []
    th_all = cfg.get("thresholds", {})
    opp = {"dropFromHigh": 15, "maCross": True, "congress": True, "earnings": True}
    opp.update(cfg.get("opp", {}))
    watch = [s.upper() for s in cfg.get("watchlist", [])]
    for sym in watch:
        p = os.path.join(seed, "markets__%s.json" % sym.replace("^", "idx-"))
        if not os.path.isfile(p):
            continue
        m = json.load(open(p, encoding="utf-8"))
        c = [x[1] for x in m.get("history", [])]
        if len(c) < 2:
            continue
        price = m.get("price") or c[-1]
        day = (price / c[-2] - 1) * 100
        hi = max(c + [m.get("high52") or 0])
        th = th_all.get(sym, {})
        cur = m.get("currency") or ""
        if th.get("below") is not None and price <= th["below"]:
            out.append(("alert", sym, "%s sous ton seuil de %s %s (cours %.2f)" % (sym, th["below"], cur, price)))
        if th.get("above") is not None and price >= th["above"]:
            out.append(("alert", sym, "%s au-dessus de ton seuil de %s %s (cours %.2f)" % (sym, th["above"], cur, price)))
        if th.get("move") is not None and abs(day) >= th["move"]:
            out.append(("alert", sym, "%s bouge de %s sur la séance" % (sym, fmt_pct(day))))
        if hi > 0 and -(price / hi - 1) * 100 >= opp["dropFromHigh"]:
            out.append(("opp", sym, "%s à %s de son plus haut" % (sym, fmt_pct((price / hi - 1) * 100))))
        if opp["maCross"]:
            s20, s50 = ma_series(c, 20), ma_series(c, 50)
            for i in range(max(1, len(c) - 5), len(c)):
                if None not in (s20[i - 1], s50[i - 1], s20[i], s50[i]) and s20[i - 1] <= s50[i - 1] and s20[i] > s50[i]:
                    out.append(("opp", sym, "%s : moyenne 20 jours repassée au-dessus de la 50 jours" % sym))
                    break
    if opp["congress"]:
        p = os.path.join(seed, "feeds__congress.json")
        if os.path.isfile(p):
            for f in json.load(open(p, encoding="utf-8")).get("filings", []):
                for r in f.get("rows", []):
                    if r.get("ticker") and r["ticker"].upper() in watch and "purchase" in (r.get("type_name") or ""):
                        out.append(("opp", r["ticker"], "%s a déclaré un achat de %s (%s)" % (f["name"], r["ticker"], r.get("amount") or "")))
    return [{"sev": a, "sym": b, "text": t} for a, b, t in out]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("seed")
    ap.add_argument("config")
    ap.add_argument("--previous")
    ap.add_argument("--out")
    a = ap.parse_args()
    cfg = json.load(open(a.config, encoding="utf-8"))
    sig = compute(a.seed, cfg)
    prev = set()
    if a.previous and os.path.isfile(a.previous):
        prev = {s["text"] for s in json.load(open(a.previous, encoding="utf-8"))}
    new = [s for s in sig if s["text"] not in prev]
    if a.out:
        json.dump(sig, open(a.out, "w", encoding="utf-8"), ensure_ascii=False)
    print(json.dumps({"total": len(sig), "new": new}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
