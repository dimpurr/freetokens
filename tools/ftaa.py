#!/usr/bin/env python3
"""FTAA (ADR-035): one intelligence score for the whole site, fixed on the Artificial Analysis v5 scale.

    python3 tools/ftaa.py fit            # pair our old scores with AA v5 scores, print the quadratic fit and leave-one-out error
    python3 tools/ftaa.py fit --write    # also store the coefficients in schema/schema.json ("ftaa")
    python3 tools/ftaa.py apply          # dry run: convert data/models.json, anchors.json, benchmarks peers, est_history
    python3 tools/ftaa.py apply --write  # write them

A model with a v5 score on AA gets it directly (basis "direct", one decimal). A model with only an older score is
mapped through the curve (basis "mapped"). The older score stays in prev_value / prev_date. A new AA version later
adds one more curve (version -> FTAA); FTAA itself is never rescaled.
The AA key is read by tools/watch.py aa_table() from the environment or chco .env and is never printed.
"""
import json, sys, datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


def slug_of(url):
    return str(url or "").rstrip("/").split("/")[-1] or None


def _solve(A, b):
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for i in range(n):
        p = max(range(i, n), key=lambda r: abs(M[r][i]))
        M[i], M[p] = M[p], M[i]
        for r in range(i + 1, n):
            f = M[r][i] / M[i][i]
            for c in range(i, n + 1):
                M[r][c] -= f * M[i][c]
    x = [0.0] * n
    for i in reversed(range(n)):
        x[i] = (M[i][n] - sum(M[i][c] * x[c] for c in range(i + 1, n))) / M[i][i]
    return x


def polyfit2(pts):
    """Least squares y = a + b x + c x^2 -> (a, b, c)."""
    S = [sum(x ** k for x, _ in pts) for k in range(5)]
    T = [sum(y * x ** k for x, y in pts) for k in range(3)]
    return tuple(_solve([[S[i + j] for j in range(3)] for i in range(3)], T))


def curve_value(curve, x):
    """Old-scale score -> FTAA. Quadratic inside the fitted domain (where our pairs are). Above the top it continues
    one-for-one (AA v4 and v5 agree up there). Below the bottom it runs straight to zero, so it never turns upward
    where no pair constrains it. The result is never negative."""
    a, b, c = curve["coef"]
    lo, hi = curve["domain"]
    f = lambda t: a + b * t + c * t * t
    if x > hi:
        y = f(hi) + (x - hi)
    elif x < lo:
        y = f(lo) * x / lo
    else:
        y = f(x)
    return max(y, 0.0)


def load_json(rel):
    return json.loads((ROOT / rel).read_text())


def dump_json(rel, obj):
    """Write back with the indent and trailing newline the file already had, so the diff shows only changed values."""
    f = ROOT / rel
    old = f.read_text()
    line = next((l for l in old.splitlines() if l.startswith(" ")), " ")
    indent = len(line) - len(line.lstrip(" "))
    f.write_text(json.dumps(obj, ensure_ascii=False, indent=indent) + ("\n" if old.endswith("\n") else ""))


def v5_table():
    import watch
    t = watch.aa_table()
    if not t:
        sys.exit("blocked: no AA data API table (no key, or the call failed)")
    return {s: r["aa"] for s, r in t.items() if r.get("aa") is not None}


def legacy_model(a):
    """(old score, old date) of a models.json aa_index, whether or not it was already converted."""
    if a.get("basis"):
        return a.get("prev_value"), a.get("prev_date")
    return a.get("value"), a.get("date")


def legacy_anchor(x):
    return x["aa_prev"] if "aa_basis" in x else x["aa_index"]


def pairs(v5):
    """{slug: (old, new, label)}: models.json and anchors.json entries whose AA page slug has a v5 score.
    The anchor reading (one decimal) wins over the model reading (integer) for the same slug."""
    out = {}
    for m in load_json("data/models.json"):
        old, _ = legacy_model(m["aa_index"])
        s = slug_of(m["aa_index"].get("url"))
        if old is not None and s in v5:
            out[s] = (float(old), v5[s], m["id"])
    for x in load_json("data/anchors.json"):
        s = slug_of(x.get("aa_url"))
        if s in v5:
            out[s] = (float(legacy_anchor(x)), v5[s], x["name"])
    return out


def fit(v5):
    pts = sorted((o, n) for o, n, _ in pairs(v5).values())
    coef = polyfit2(pts)
    errs, lin = [], []
    for i, (x, y) in enumerate(pts):
        rest = pts[:i] + pts[i + 1:]
        c = polyfit2(rest)
        errs.append(abs(c[0] + c[1] * x + c[2] * x * x - y))
        mx, my = sum(p[0] for p in rest) / len(rest), sum(p[1] for p in rest) / len(rest)
        sl = sum((p[0] - mx) * (p[1] - my) for p in rest) / sum((p[0] - mx) ** 2 for p in rest)
        lin.append(abs(my + sl * (x - mx) - y))
    cur = {"coef": [round(v, 8) for v in coef], "domain": [round(pts[0][0], 1), round(pts[-1][0], 1)]}
    info = {"n": len(pts), "loo_mean_abs_diff": round(sum(errs) / len(errs), 2),
            "loo_within_3": round(sum(e <= 3 for e in errs) / len(errs), 2),
            "linear_loo_mean_abs_diff": round(sum(lin) / len(lin), 2)}
    return cur, info


def schema_block(cur, info, today):
    return {"$comment": "ADR-035. FTAA = Artificial Analysis Intelligence Index v5 scale, fixed. A model with a v5 score uses it "
                        "(basis direct); one with only an older score goes through this curve (basis mapped). Fitted by "
                        "tools/ftaa.py on pairs of our old score and the AA v5 score; a later AA version adds one more curve, "
                        "FTAA is never rescaled.",
            "version": 1, "from": "AA v4.3.2", "fitted": today.isoformat(), "curve": cur, "fit": info}


def write_schema_block(block):
    """Put the "ftaa" block just before "est_rules" in schema.json as text, so the hand-formatted file is not reflowed."""
    import re
    f = ROOT / "schema/schema.json"
    t = f.read_text()
    t = re.sub(r'\n "ftaa": \{.*?\n \},(?=\n "est_rules")', "", t, flags=re.S)
    body = json.dumps(block, ensure_ascii=False, indent=1).replace("\n", "\n ")
    marker = '\n "est_rules": {'
    assert marker in t
    f.write_text(t.replace(marker, '\n "ftaa": ' + body + "," + marker, 1))


def convert(v5, curve, ds, old, url):
    """-> (value, basis) for an old-scale score `old` of the AA page `url`."""
    s = slug_of(url)
    if s in v5:
        return round(float(v5[s]), 1), "direct"
    return round(curve_value(curve, float(old)), 1), "mapped"


def apply(v5, curve, today, write):
    ds = today.isoformat()
    ch = {"models_direct": 0, "models_mapped": 0, "anchors_direct": 0, "anchors_mapped": 0,
          "peers_direct": 0, "peers_mapped": 0, "history": 0}
    moves = []
    models = load_json("data/models.json")
    for m in models:
        a = m["aa_index"]
        old, odate = legacy_model(a)
        if old is None:
            continue
        keep = {k: v for k, v in a.items() if k not in ("value", "date", "approx", "prev_value", "prev_date", "basis")}
        new, basis = convert(v5, curve, ds, old, a.get("url"))
        ch["models_" + basis] += 1
        m["aa_index"] = dict({"value": new, "date": ds if basis == "direct" else odate}, **keep,
                             basis=basis, prev_value=old, prev_date=odate)
        moves.append((new - old, m["id"], old, new, basis))
    anchors = load_json("data/anchors.json")
    for x in anchors:
        old = legacy_anchor(x)
        x["aa_index"], x["aa_basis"] = convert(v5, curve, ds, old, x.get("aa_url"))
        x["aa_prev"] = old
        ch["anchors_" + x["aa_basis"]] += 1
    bench = load_json("data/benchmarks.json")
    for c in bench.get("claims", []):
        for p in c.get("peers", []):
            if p.get("aa") is None:
                continue
            old = p["aa_prev"] if "aa_basis" in p else p["aa"]
            p["aa"], p["aa_basis"] = convert(v5, curve, ds, old, p.get("aa_url"))
            p["aa_prev"] = old
            ch["peers_" + p["aa_basis"]] += 1
    hist = load_json("data/est_history.json")
    for h in hist:
        if h.get("settled") or h.get("status") != "ok" or h.get("scale") == "ftaa":
            continue
        width = h["high"] - h["low"]
        center = round(curve_value(curve, h["center"]), 1)
        low = round(center - width / 2)
        h["prev"] = {"center": h["center"], "low": h["low"], "high": h["high"]}
        h.update(center=center, low=low, high=low + width, scale="ftaa")
        ch["history"] += 1
    if write:
        dump_json("data/models.json", models)
        dump_json("data/anchors.json", anchors)
        dump_json("data/benchmarks.json", bench)
        dump_json("data/est_history.json", hist)
    return ch, sorted(moves, key=lambda r: r[0])


def main(argv):
    if not argv or argv[0] not in ("fit", "apply"):
        print(__doc__)
        return 2
    write = "--write" in argv
    today = dt.date.today()
    v5 = v5_table()
    cur, info = fit(v5)
    a, b, c = cur["coef"]
    print(f"pairs: {info['n']}  domain(old): {cur['domain']}")
    print(f"FTAA = {a:.6f} + {b:.6f} x + {c:.8f} x^2")
    print(f"leave-one-out mean abs diff: {info['loo_mean_abs_diff']} (linear {info['linear_loo_mean_abs_diff']}), within 3: {info['loo_within_3']}")
    print("vertex at old score", round(-b / (2 * c), 1) if c else None, "(top of domain", cur["domain"][1], ")")
    print("  ".join(f"{x}->{curve_value(cur, x):.1f}" for x in (0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 58, 60)))
    if argv[0] == "fit":
        if write:
            write_schema_block(schema_block(cur, info, today))
            print("wrote schema/schema.json ftaa")
        return 0
    sch = load_json("schema/schema.json")
    curve = sch["ftaa"]["curve"] if "ftaa" in sch else cur
    ch, moves = apply(v5, curve, today, write)
    print(ch)
    for d, mid, old, new, basis in moves[:5] + moves[-5:]:
        print(f"  {mid}: {old} -> {new} ({basis}) {d:+.1f}")
    print("written" if write else "dry run (add --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
