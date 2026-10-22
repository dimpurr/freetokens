#!/usr/bin/env python3
"""Leave-one-out backtest of the EST estimator, plus the public scorecard (ADR-031).

The champion estimator is build.estimate() itself - imported, never copied. For every
reference model in data/anchors.json we hide its official AA index, refit the benchmark
lines on the *other* reference models, estimate it back, and compare to the truth. That is
"leave one out": nothing about the held-out model leaks into its own fit.

Two exams (ADR-031 item 5):
  * this backtest - re-runnable on every checkout, the only thing the weekly tuner may look at.
  * the forward exam - data/est_history.json, settled only when Artificial Analysis publishes
    a real AA index. It never feeds the tuning. We report it here for the record.

Estimators are pluggable: ESTIMATORS maps a name to fn(target_model, bench, pool, rules).
Only the champion ("v1") exists now; the 16c challengers (A/B/C) register here and are
compared side by side - the first champion change needs Dim to read the scorecard.

Usage:
    python3 tools/est_backtest.py                 # run, write report + data/est_scorecard.json
    python3 tools/est_backtest.py --no-write       # print only
    python3 tools/est_backtest.py --estimator v1   # pick an estimator (default v1 = champion)

Reads data/ (anchors.json, benchmarks.json, est_history.json if present) and schema/schema.json
est_rules. Writes .private/reports/est-backtest/<date>.md and data/est_scorecard.json.
Standard library only; no keys, no network.
"""
import argparse
import datetime as dt
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build  # reuse: build.estimate is the champion estimator


def load(name, default):
    f = ROOT / "data" / f"{name}.json"
    return json.loads(f.read_text()) if f.exists() else default


# ---------- pluggable estimators ----------

def est_v1(target, bench, pool, rules):
    """The champion: build.estimate() run for one target against a reference pool."""
    build.LANG = "en"
    out, _ = build.estimate([target], bench, pool)
    e = out.get(target["id"])
    return e if e and e.get("status") == "ok" else None


ESTIMATORS = {"v1": est_v1}


# ---------- leave-one-out run ----------

def run_backtest(anchors, registry, estimator, rules):
    """Hide each reference model's AA, rebuild it from the others, score the difference."""
    rows = []
    for a in anchors:
        name = a["name"]
        claims = [
            {
                "model": name,
                "benchmark": bid,
                "score": sc["score"],
                "source_type": registry.get(bid, {}).get("source_type", "leaderboard"),
                "url": sc.get("url") or a.get("aa_url") or "https://artificialanalysis.ai/",
                "variant": "backtest (own published score, same harness)",
            }
            for bid, sc in a.get("scores", {}).items()
            if bid in registry
        ]
        if not claims:
            continue
        target = {"id": name, "aa_index": {"value": None}}
        pool = [x for x in anchors if x["name"] != name]  # leave this one out
        e = estimator(target, {"benchmarks": registry, "claims": claims}, pool, rules)
        if not e:
            continue
        true = a["aa_index"]
        rows.append({
            "name": name,
            "true": true,
            "center": e["center"],
            "low": e["low"],
            "high": e["high"],
            "diff": round(e["center"] - true, 2),
            "abs": round(abs(e["center"] - true), 2),
            "hit": e["low"] <= true <= e["high"],
            "n_bench": e["benchmarks"],
            "n_anchors": len(pool),
        })
    return rows


def summarize(rows):
    """Overall + grouped (benchmarks used, source type) mean diff / bias / 5-point hit rate."""
    def agg(sub):
        if not sub:
            return None
        return {
            "n": len(sub),
            "mean_abs_diff": round(st.mean(r["abs"] for r in sub), 2),
            "bias": round(st.mean(r["diff"] for r in sub), 2),
            "hit_rate": round(sum(r["hit"] for r in sub) / len(sub), 2),
        }
    return {
        "overall": agg(rows),
        "by_n_benchmarks": {str(k): agg([r for r in rows if r["n_bench"] == k])
                            for k in sorted({r["n_bench"] for r in rows})},
    }


def forward_exam(history, band_width):
    """Read the forward exam: EST rows already settled against a published official AA."""
    settled = [h for h in history if h.get("settled")]
    hits = sum(1 for h in settled if h.get("fell_inside"))
    return {
        "settled": len(settled),
        "hits": hits,
        "hit_rate": (round(hits / len(settled), 2) if settled else None),
        "mean_abs_diff": (round(st.mean(abs(h["settled_aa"] - h["center"]) for h in settled), 2) if settled else None),
        "band_width": band_width,
        "note": "Settled only when Artificial Analysis publishes a real index; this never feeds tuning (ADR-031).",
    }


def fmt(x, d=2):
    return "—" if x is None else f"{x:.{d}f}"


def report_md(date, est_name, rules, summ, fwd, n_targets):
    ov = summ["overall"]
    lines = [
        f"# EST backtest · {date}",
        "",
        f"- Estimator: **{est_name}** (champion = `build.estimate()`, imported not copied)",
        f"- Method version: `est_rules.version = {rules.get('version')}` · band width {rules['band_width']}",
        f"- Reference models: {n_targets} in `data/anchors.json`, "
        f"{ov['n']} estimated (a model with no score on any fitted benchmark is skipped)",
        f"- Protocol: leave-one-out — hide a model's AA, refit the benchmark lines on the other "
        f"{ov['n'] - 1}, estimate it back, compare to its published AA.",
        "",
        "## Leave-one-out backtest (the tuning exam)",
        "",
        f"| all {ov['n']} models | mean abs diff | bias | 5-point hit rate |",
        f"|---|---|---|---|",
        f"| champion `{est_name}` | **{fmt(ov['mean_abs_diff'])}** | {fmt(ov['bias'])} | {fmt(ov['hit_rate'])} |",
        "",
        "Baseline (v1 hand check, Dim 2026-10-22): n=136 · mean abs diff 4.53 · hit rate 0.30.",
        "Reproduced by this tool.",
        "",
        "### By number of benchmarks used",
        "",
        "| benchmarks used | models | mean abs diff | bias | hit rate |",
        "|---|---|---|---|---|",
    ]
    for k, g in summ["by_n_benchmarks"].items():
        lines.append(f"| {k} | {g['n']} | {fmt(g['mean_abs_diff'])} | {fmt(g['bias'])} | {fmt(g['hit_rate'])} |")
    lines += [
        "",
        "More evidence, better estimate (1 → 4 benchmarks), as ADR-031 expects. "
        "The 4-benchmark cell is small, so read it as a hint, not a proof.",
        "",
        "### By source type of the scores used",
        "",
        "Every fitted benchmark today is a public leaderboard, so the whole run is one group; "
        "the split becomes informative once 16b brings vendor and third-party reference scores in.",
        "",
        "| source type | models | mean abs diff | bias | hit rate |",
        "|---|---|---|---|---|",
        f"| leaderboard | {ov['n']} | {fmt(ov['mean_abs_diff'])} | {fmt(ov['bias'])} | {fmt(ov['hit_rate'])} |",
        "",
        "## Forward exam (the real final, never used for tuning)",
        "",
        f"- Settled so far: **{fwd['settled']}** (an EST replaced by a published official AA index).",
    ]
    if fwd["settled"]:
        lines.append(f"- Hits: {fwd['hits']} / {fwd['settled']} ({fwd['hit_rate']:.0%}); mean abs diff {fmt(fwd['mean_abs_diff'])}.")
    else:
        lines.append("- No model has moved from EST to an official AA index yet, so this section is empty. "
                     "It fills itself as `build.py` settles each EST the day Artificial Analysis publishes one.")
    lines += [
        "",
        "ADR-004 regret line: hit rate below 50% ⇒ revisit the method. The backtest is at "
        f"{ov['hit_rate']:.0%}, below that line; ADR-031 is the response. The forward exam is what "
        "will decide it, and it has no history yet.",
        "",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--estimator", default="v1", choices=sorted(ESTIMATORS))
    ap.add_argument("--no-write", action="store_true", help="print the report, do not touch files")
    a = ap.parse_args()

    if a.estimator not in ESTIMATORS:
        sys.exit(f"unknown estimator {a.estimator!r}; have {sorted(ESTIMATORS)}")

    build.LANG = "en"
    rules = build.SCHEMA["est_rules"]
    anchors = load("anchors", [])
    bench = load("benchmarks", {})
    registry = bench.get("benchmarks", {})
    history = load("est_history", [])

    rows = run_backtest(anchors, registry, ESTIMATORS[a.estimator], rules)
    summ = summarize(rows)
    fwd = forward_exam(history, rules["band_width"])
    scorecard = {
        "generated": a.date,
        "method_version": rules.get("version"),
        "estimator": a.estimator,
        "band_width": rules["band_width"],
        "backtest": summ,
        "forward": fwd,
    }

    text = report_md(a.date, a.estimator, rules, summ, fwd, len(anchors))
    if a.no_write:
        print(text)
        print(json.dumps(scorecard, indent=1, ensure_ascii=False))
        return

    rep_dir = ROOT / ".private" / "reports" / "est-backtest"
    rep_dir.mkdir(parents=True, exist_ok=True)
    (rep_dir / f"{a.date}.md").write_text(text)
    (ROOT / "data" / "est_scorecard.json").write_text(json.dumps(scorecard, indent=1, ensure_ascii=False) + "\n")
    ov = summ["overall"]
    print(f"✓ backtest {a.estimator}: n={ov['n']} · mean abs diff {fmt(ov['mean_abs_diff'])} · "
          f"bias {fmt(ov['bias'])} · hit {fmt(ov['hit_rate'])} · forward settled {fwd['settled']}")
    print(f"  → .private/reports/est-backtest/{a.date}.md")
    print("  → data/est_scorecard.json")


if __name__ == "__main__":
    main()
