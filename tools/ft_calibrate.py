#!/usr/bin/env python3
"""Fit the FT Intelligence benchmark lines once, on the frozen reference scores (ADR-036).

Input  (private, $FT_PRIVATE, default <repo>/.private/data):
         ft-reference.json   frozen reference scores + each reference model's published benchmark scores
Output (public): data/ft_lines.json   per benchmark: a, b (score -> FTI), r, n, ok. No reference scores.

A benchmark joins the registry when at least `min_anchors` reference models have a score on it and
the correlation reaches `min_r` (ADR-031, schema ft_rules). Scores whose source page is
artificialanalysis.ai, or benchlm.ai (may relay AA), are never fitted. A benchmark that also has vendor-reported reference
scores gets a second line (`vendor`), fitted on those alone, because vendor self-reports run high.

Usage: python3 tools/ft_calibrate.py [--no-write]
Standard library only.
"""
import argparse
import json
import os
import statistics as st
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PRIVATE = Path.home() / "WorkflowUser/Code/Project/freetokens/.private/data"


def private_dir():
    return Path(os.environ.get("FT_PRIVATE") or DEFAULT_PRIVATE)


NO_FIT_HOSTS = ("artificialanalysis.ai", "benchlm.ai")  # AA itself; BenchLM may relay AA numbers (provenance unclear)


def is_aa_url(url):
    """True for a source that never enters a fit (name kept for the callers: AA and its possible relays)."""
    h = urlparse(url or "").hostname or ""
    return any(h == d or h.endswith("." + d) for d in NO_FIT_HOSTS)


def fit(pts, rules):
    """Least squares y = a + b x over [(x, y)]. Returns None below min_anchors."""
    if len(pts) < rules["min_anchors"]:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    if max(xs.count(x) for x in set(xs)) / len(xs) > rules["max_tie_share"]:
        return {"ok": False, "n": len(pts), "why": "floor or ceiling effect: most reference models share one score"}
    mx, my = st.mean(xs), st.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0 or len(set(ys)) < 2:
        return None
    b = sum((x - mx) * (y - my) for x, y in pts) / sxx
    r = st.correlation(xs, ys)
    return {"a": round(my - b * mx, 4), "b": round(b, 5), "r": round(r, 3), "n": len(pts), "x": [round(min(xs), 2), round(max(xs), 2)], "ok": r >= rules["min_r"]}


def fit_lines(models, rules):
    """models: [{ref, scores{bid:{score,url}}, vendor_scores{bid:{score}}}] -> {bid: line}"""
    pts, vpts = {}, {}
    for m in models:
        for bid, c in m.get("scores", {}).items():
            if bid.startswith("aa_") or is_aa_url(c.get("url")):
                continue
            if c.get("src") == "vendor":
                vpts.setdefault(bid, []).append((c["score"], m["ref"]))
            else:
                pts.setdefault(bid, []).append((c["score"], m["ref"]))
        for bid, c in (m.get("vendor_scores") or {}).items():
            if not bid.startswith("aa_") and not is_aa_url(c.get("url")):
                vpts.setdefault(bid, []).append((c["score"], m["ref"]))
    lines = {}
    for bid in sorted(set(pts) | set(vpts)):
        f = fit(pts.get(bid, []), rules)
        v = fit(vpts.get(bid, []), rules)
        if f is not None and f.get("ok") is False and "why" in f:
            lines[bid] = f
            continue
        if f is None and v is None:
            lines[bid] = {"ok": False, "n": len(pts.get(bid, [])), "why": f"only {len(pts.get(bid, []))} reference models (need {rules['min_anchors']})"}
            continue
        e = f or {"ok": False, "n": len(pts.get(bid, [])), "why": f"only {len(pts.get(bid, []))} reference models (need {rules['min_anchors']})"}
        if f and not f["ok"]:
            e["why"] = f"correlation {f['r']} below {rules['min_r']}"
        if v and v["ok"]:
            e["vendor"] = v
        if v and v["ok"] and not e["ok"]:
            e["ok"] = False  # a vendor-only line never makes the benchmark usable for independent claims
        lines[bid] = e
    return lines


def load_reference():
    return json.loads((private_dir() / "ft-reference.json").read_text())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    rules = json.loads((ROOT / "schema/schema.json").read_text())["ft_rules"]
    ref = load_reference()
    lines = fit_lines(ref["models"], rules)
    ok = {k: v for k, v in lines.items() if v["ok"] or "vendor" in v}
    out = {"$comment": "ADR-036. Fitted once by tools/ft_calibrate.py on frozen private reference scores; a = intercept, b = slope (benchmark score -> FT Intelligence), r, n = reference models. No reference scores are stored here.",
           "version": 1, "frozen": ref["frozen"], "lines": lines}
    for k, v in sorted(lines.items()):
        print(f"{'ok ' if v['ok'] else 'no '} {k:34} n={v['n']:>3} r={v.get('r', '-')}" + (f"  vendor n={v['vendor']['n']} r={v['vendor']['r']}" if "vendor" in v else "") + ("" if v["ok"] else f"  ({v.get('why')})"))
    print(f"{sum(1 for v in lines.values() if v['ok'])} benchmarks pass the registry rule of {len(lines)}")
    if not a.no_write:
        (ROOT / "data/ft_lines.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
