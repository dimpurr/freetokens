#!/usr/bin/env python3
"""Leave-one-out backtest of FT Intelligence against the frozen reference scores (ADR-036; replaces ADR-031's exams).

For every reference model in $FT_PRIVATE/ft-reference.json: hide its reference score, refit the benchmark lines on the
other reference models (tools/ft_calibrate.fit_lines), score the held-out model from its own published benchmark scores
(tools/ft_score.score_model) and compare with the hidden reference score. Artificial Analysis is never a source here,
Artificial Analysis sub-scores and benchlm.ai rows are not fitted, so nothing about the held-out model leaks into its estimate.

Two regimes:
  published  the model's own scores on leaderboards and third-party runs (what the lines are fitted on)
  vendor     the model's vendor self-reports with the same-table peers (the regime of a new model's launch post)

The forward exam of ADR-031 is retired. Writes data/ft_scorecard.json (public: aggregate numbers only).

Usage: python3 tools/ft_backtest.py [--no-write] [--date YYYY-MM-DD]
"""
import argparse
import datetime as dt
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from ft_calibrate import fit_lines, is_aa_url, load_reference  # noqa: E402
from ft_score import score_model  # noqa: E402


def claims_for(m, regime):
    out = []
    if regime == "vendor":
        peers = m.get("vendor_peers") or {}
        for bid, c in (m.get("vendor_scores") or {}).items():
            if bid.startswith("aa_") or is_aa_url(c.get("url")):
                continue
            out.append({"benchmark": bid, "score": c["score"], "source_type": "vendor", "url": c.get("url") or "-",
                        "peers": [{"name": p["name"], "score": p["score"], "ref": p["aa"]} for p in peers.get(bid, []) if p.get("aa") is not None]})
        return out
    for bid, c in m.get("scores", {}).items():
        if bid.startswith("aa_") or is_aa_url(c.get("url")):
            continue
        st_ = {"leaderboard": "leaderboard", "third_party": "third_party", "vendor": "vendor"}.get(c.get("src"), "community")
        out.append({"benchmark": bid, "score": c["score"], "source_type": st_, "url": c.get("url") or "-"})
    return out


def run(ref_models, rules, regime):
    rows = []
    for i, m in enumerate(ref_models):
        cl = claims_for(m, regime)
        if not cl:
            continue
        lines = fit_lines([x for j, x in enumerate(ref_models) if j != i], rules)
        e = score_model(cl, lines, rules)
        if e["status"] != "ok":
            continue
        true = m["ref"]
        w = rules["band_width"]
        low = round(e["center"] - w / 2)
        rows.append({"name": m["name"], "true": true, "center": e["center"], "diff": e["center"] - true, "abs": abs(e["center"] - true),
                     "hit": low <= true <= low + w, "evidence": e["evidence"], "exact": e["exact"]})
    return rows


def agg(rows):
    if not rows:
        return None
    return {"n": len(rows), "mean_abs_diff": round(st.mean(r["abs"] for r in rows), 2), "bias": round(st.mean(r["diff"] for r in rows), 2),
            "hit_rate": round(sum(r["hit"] for r in rows) / len(rows), 2), "within_3": round(sum(r["abs"] <= 3 for r in rows) / len(rows), 2)}


def summarize(rows):
    ks = sorted({min(r["evidence"], 4) for r in rows})
    return {"overall": agg(rows),
            "by_evidence": {(str(k) if k < 4 else "4+"): agg([r for r in rows if min(r["evidence"], 4) == k]) for k in ks},
            "exact_only": agg([r for r in rows if r["exact"]])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    a = ap.parse_args()
    rules = json.loads((ROOT / "schema/schema.json").read_text())["ft_rules"]
    ref = load_reference()
    models = ref["models"]
    pub, ven = run(models, rules, "published"), run(models, rules, "vendor")
    card = {"$comment": "ADR-036. Leave-one-out backtest against the frozen reference scores, written by tools/ft_backtest.py.",
            "date": a.date, "method_version": rules["version"], "band_width": rules["band_width"],
            "reference_models": len(models), "published": summarize(pub), "vendor": summarize(ven)}
    for k in ("published", "vendor"):
        o = card[k]["overall"]
        print(f"{k:9} n={o['n']} mean abs diff {o['mean_abs_diff']} bias {o['bias']} {rules['band_width']}-point hit rate {o['hit_rate']} within 3: {o['within_3']}")
        for e, v in card[k]["by_evidence"].items():
            print(f"   evidence {e}: n={v['n']} mean abs diff {v['mean_abs_diff']} hit {v['hit_rate']}")
    if not a.no_write:
        (ROOT / "data/ft_scorecard.json").write_text(json.dumps(card, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
