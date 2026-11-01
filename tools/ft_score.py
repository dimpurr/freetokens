#!/usr/bin/env python3
"""FT Intelligence per model (ADR-036): data/benchmarks.json claims + data/ft_lines.json -> data/ft_scores.json.

For each model every claim on a registry benchmark (line ok in ft_lines.json) is put on the FTI scale:
  fit   FTI = a + b * score on the benchmark's line (a vendor claim uses the vendor line when one exists)
  peer  a vendor table that also lists models whose reference score is known: reference + b * (score gap),
        read inside the same table so the vendor's harness bias cancels (ADR-023)
Claims on one benchmark (all Epoch AI benchmarks count as one) collapse to one piece of evidence. The centre is the weighted median of the
pieces (weights in schema ft_rules). Evidence counts benchmarks, plus Artificial Analysis as one source
when fewer than `aa_below` other pieces exist and the private snapshot has a value.

A source row that is not used carries `why`: no_refs | few_refs | low_r | floor | excluded (with `note`).
Display rule written into the output: exact (an integer) only with evidence >= min_evidence AND at least one
independent (non-vendor) piece; otherwise a band of band_width points (vendor-only: vendor_only_band);
no evidence: status "none". Artificial Analysis is listed by name and link only, never a number.

Private input (optional, $FT_PRIVATE): aa-snapshot.json, ft-reference.json (peer reference scores).
Without them the scores are computed without AA and without peer references.

Usage: python3 tools/ft_score.py [--no-write]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from ft_calibrate import private_dir  # noqa: E402


def weighted_median(pairs):
    s = sorted(pairs)
    half, acc = sum(w for _, w in s) / 2, 0.0
    for i, (v, w) in enumerate(s):
        acc += w
        if acc > half + 1e-9:
            return v
        if abs(acc - half) <= 1e-9 and i + 1 < len(s):
            return (v + s[i + 1][0]) / 2
    return s[-1][0]


def family(bid):
    """Evidence is counted per source family: every Epoch AI benchmark is one family (ECI already combines them)."""
    return "epoch" if bid.startswith("epoch_") else bid


def pretty(bid):
    return bid.replace("_", " ")


def score_model(claims, lines, rules, names=None, peer_refs=None, aa=None):
    """claims: [{benchmark, score, source_type, url, variant?, peers?, excluded?}] for ONE model.
    aa: {"url": ...} plus "value" when the private snapshot has it. Returns the ft_scores entry."""
    names, peer_refs = names or {}, peer_refs or {}
    W = rules["weights"]
    sources, per = [], {}
    for c in claims:
        bid = c["benchmark"]
        s = {"name": names.get(bid) or pretty(bid), "benchmark": bid, "value": c["score"], "url": c["url"], "type": c["source_type"]}
        ln = lines.get(bid)
        vendor = c["source_type"] == "vendor"
        if c.get("excluded"):
            sources.append(dict(s, used=False, why="excluded", note=c["excluded"]))
            continue
        line = ln.get("vendor") if (vendor and ln and ln.get("vendor")) else (ln if ln and ln.get("ok") else None)
        if line is None:
            w = (ln or {}).get("why") or ""
            sources.append(dict(s, used=False, why="few_refs" if w.startswith("only") else "low_r" if w.startswith("corr") else "floor" if w.startswith("floor") else "no_refs",
                                **({"n": ln["n"]} if ln and ln.get("n") is not None else {}), **({"r": ln["r"]} if ln and "r" in ln else {})))
            continue
        near = []
        for p in c.get("peers") or []:
            ref = p.get("ref") if p.get("ref") is not None else peer_refs.get(p["name"])
            if ref is not None and abs(c["score"] - p["score"]) <= rules["peer_max_gap"]:
                near.append((p, ref))
        if near:
            ws = [(ref + line["b"] * (c["score"] - p["score"]), 1 / (1 + abs(c["score"] - p["score"]) / rules["peer_scale"])) for p, ref in near]
            implied, method = sum(v * w for v, w in ws) / sum(w for _, w in ws), "peer"
            weight = W["vendor_peer"] if vendor else W.get(c["source_type"], 0.5)
            s["peers_used"] = [p["name"] for p, _ in near]
        else:
            lo, hi = line["x"]
            pad = rules["extrapolate"] * (hi - lo)
            x = min(max(c["score"], lo - pad), hi + pad)  # no extrapolation far beyond the reference models
            implied, method = line["a"] + line["b"] * x, "fit"
            weight = W.get(c["source_type"], 0.5)
            s["r"], s["n"] = line["r"], line["n"]
        implied = min(max(implied, 0.0), 70.0)
        s.update(used=True, implied=round(implied, 1), method=method, weight=weight)
        sources.append(s)
        per.setdefault(family(bid), []).append(s)
    items = []
    for bid, ss in per.items():
        w = sum(x["weight"] for x in ss)
        items.append({"bid": bid, "implied": sum(x["implied"] * x["weight"] for x in ss) / w, "weight": max(x["weight"] for x in ss),
                      "independent": any(x["type"] != "vendor" for x in ss), "method": "peer" if any(x["method"] == "peer" for x in ss) else "fit"})
    if len(items) < rules["aa_below"] and aa and aa.get("value") is not None:
        items.append({"bid": "artificial_analysis", "implied": aa["value"], "weight": W["aa"], "independent": True, "method": "aa"})
        sources.append({"name": "Artificial Analysis", "benchmark": "artificial_analysis", "url": aa["url"], "type": "third_party", "used": True, "method": "aa"})
    for s in sources:
        s.pop("weight", None)
    sources.sort(key=lambda s: (not s["used"], s["name"]))
    if not items:
        return {"status": "none", "evidence": 0, "independent": 0, "sources": sources}
    center = weighted_median([(i["implied"], i["weight"]) for i in items])
    indep = sum(1 for i in items if i["independent"])
    exact = len(items) >= rules["min_evidence"] and indep >= 1
    vendor_only = indep == 0 and all(i["method"] == "fit" for i in items)
    width = rules["vendor_only_band"] if vendor_only else rules["band_width"]
    low = round(center - width / 2)
    return {"status": "ok", "center": round(center, 1), "low": round(center, 1) if exact else low, "high": round(center, 1) if exact else low + width,
            "evidence": len(items), "independent": indep, "exact": exact, "vendor_only": vendor_only,
            "method": "peer" if any(i["method"] == "peer" for i in items) else ("aa" if all(i["method"] == "aa" for i in items) else "fit"),
            "spread": round(max(i["implied"] for i in items) - min(i["implied"] for i in items), 1),
            "sources": sources}


def load(name, default=None):
    f = ROOT / "data" / f"{name}.json"
    return json.loads(f.read_text()) if f.exists() else default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    rules = json.loads((ROOT / "schema/schema.json").read_text())["ft_rules"]
    models, bench, lines = load("models"), load("benchmarks"), load("ft_lines")["lines"]
    names = {k: v["name"] for k, v in bench["benchmarks"].items()}
    pdir = private_dir()
    snap = json.loads((pdir / "aa-snapshot.json").read_text())["models"] if (pdir / "aa-snapshot.json").exists() else {}
    peers = json.loads((pdir / "ft-reference.json").read_text()).get("peers", {}) if (pdir / "ft-reference.json").exists() else {}
    if not snap:
        print("note: no private aa-snapshot.json, scoring without Artificial Analysis", file=sys.stderr)
    out = {}
    for m in models:
        cl = [c for c in bench["claims"] if c["model"] == m["id"]]
        refs = {}
        for c in cl:
            for p in peers.get(f"{m['id']}|{c['benchmark']}", []):
                refs[p["name"]] = p["ref"]
        out[m["id"]] = score_model(cl, lines, rules, names, refs, snap.get(m["id"]))
    n = lambda f: sum(1 for e in out.values() if f(e))
    print(f"{len(out)} models: evidence >=3 exact {n(lambda e: e.get('exact'))} · band {n(lambda e: e['status'] == 'ok' and not e.get('exact'))} · none {n(lambda e: e['status'] == 'none')}")
    print(f"evidence 0: {n(lambda e: e['evidence'] == 0)} · 1-2: {n(lambda e: 1 <= e['evidence'] <= 2)} · >=3: {n(lambda e: e['evidence'] >= 3)} "
          f"(independent >=1: {n(lambda e: e['evidence'] >= 3 and e['independent'] >= 1)}) · uses AA: {n(lambda e: any(s['method'] == 'aa' for s in e['sources'] if s['used']))}")
    if not a.no_write:
        (ROOT / "data/ft_scores.json").write_text(json.dumps({"$comment": "ADR-036. Generated by tools/ft_score.py from data/benchmarks.json + data/ft_lines.json; do not edit.", "version": 1, "scores": out}, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
