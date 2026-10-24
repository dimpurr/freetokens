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

Estimators are pluggable: ESTIMATORS maps a name to fn(target_model, bench, pool, rules)
-> est dict or None. Champions and challengers (ADR-031 item 4):
  v1  champion - build.estimate(), imported not copied
  a   challenger - per-benchmark fit, claims weighted by inverse residual variance of the
      benchmark line, plus a three-layer vendor offset (global + per-vendor shrunk + a
      subject-skew term) estimated from paired vendor-vs-third-party scores
  b   challenger - AA sub-score structure; placeholder, needs AA_API_KEY (16b-3)
  c   challenger - low-rank matrix completion (soft-impute, effective rank kept in 2-4),
      control only; hand-rolled stdlib SVD (no numpy on this box, and the tool stays stdlib-only)

Comparing them side by side: --estimator all. The first champion change needs Dim to read
the scorecard: this mode only reports, it never switches the champion or touches
data/est_scorecard.json.

Usage:
    python3 tools/est_backtest.py                    # champion run: report + data/est_scorecard.json
    python3 tools/est_backtest.py --no-write         # print only
    python3 tools/est_backtest.py --estimator a      # one estimator (v1 default; a/b/c)
    python3 tools/est_backtest.py --estimator all    # challengers side by side, report only

Reads data/ (anchors.json, benchmarks.json, est_history.json if present) and schema/schema.json
est_rules. Writes .private/reports/est-backtest/<date>.md (single estimator, or <date>-challengers.md
for --estimator all) and data/est_scorecard.json (champion path only).
Standard library only; no keys, no network.
"""
import argparse
import datetime as dt
import json
import math
import os
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
    if not e or e.get("status") != "ok":
        return None
    e["used"] = [c["benchmark"] for c in e["evidence"] if c.get("implied") is not None]
    return e


# ---------- challenger A: inverse-variance weights + three-layer vendor offset ----------

# Subject-skew proxy categories. ADR-031: coding-only models are systematically
# overestimated because AA also measures knowledge/reasoning/instruction/long-context.
# The repo has no activation-parameter column (data is read-only here), so the third
# offset layer carries the same correction with the skew measurable inside the data:
# mean z on coding benchmarks minus mean z on the general benchmarks. Swap in real
# activation params later by adding a data column; nothing else in the layer changes.
CODING_BENCHES = {"aicodingdaily", "swe_bench_verified", "swe_bench_pro",
                  "terminal_bench_2_1", "livecodebench", "aider_polyglot"}
GENERAL_BENCHES = {"gpqa_diamond", "hle", "bfcl", "tau_bench"}

# empirical-Bayes prior sample count for shrinking a vendor's own offset to the global one
VENDOR_OFFSET_PRIOR_N = 2.0

A_STATE = {}  # last computed challenger-A diagnostics, for the comparison report


def _score_entries(sc):
    """A score cell is {score,url,src}; tolerate a future list form (same model+bench
    from two sources is exactly what the vendor-offset pairs need, see OUT)."""
    return sc if isinstance(sc, list) else [sc]


def _claim_src(c):
    return c.get("src") or {"official": "vendor"}.get(c.get("source_type"), c.get("source_type", "unknown"))


def _vendor_of(name):
    return name.split()[0].rstrip("-")


def _ols(xs, ys):
    n = len(xs)
    mx, my = st.mean(xs), st.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx if sxx else 0.0
    a = my - b * mx
    r = st.correlation(xs, ys) if n >= 2 and sxx and sum((y - my) ** 2 for y in ys) else 0.0
    s2 = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys)) / n
    return {"a": a, "b": b, "r": r, "s2": max(s2, 1e-6), "n": n}


def _a_fits(pool, registry, rules):
    """Benchmark lines fitted on the pool only, gated exactly like the champion
    (min_anchors, min_r) so A isolates the weighting, not the availability rules."""
    fits = {}
    for bid in registry:
        pts = [(e["score"], m["aa_index"]) for m in pool if m.get("aa_index") is not None
               for cell in [m.get("scores", {}).get(bid)] if cell is not None
               for e in _score_entries(cell)]
        if len(pts) < rules["min_anchors"]:
            continue
        f = _ols([p[0] for p in pts], [p[1] for p in pts])
        if f["r"] >= rules["min_r"]:
            fits[bid] = f
    return fits


def _offsets_from_pairs(pool):
    """Layer 1+2 of ADR-031 item 3: vendor self-report minus third-party score, on
    (model, benchmark) cells where both exist. Global delta + per-vendor delta shrunk
    toward the global with prior pseudo-count VENDOR_OFFSET_PRIOR_N."""
    pairs = []  # (vendor, benchmark, vendor_score - third_party_score)
    for m in pool:
        for bid, sc in m.get("scores", {}).items():
            entries = _score_entries(sc)
            v = [e for e in entries if e.get("src") == "vendor"]
            t = [e for e in entries if e.get("src") in ("third_party", "leaderboard")]
            if v and t:
                pairs.append((_vendor_of(m["name"]), bid,
                              st.mean(e["score"] for e in v) - st.mean(e["score"] for e in t)))
    delta_global = st.mean(p[2] for p in pairs) if pairs else 0.0
    deltas = {}
    for p in pairs:
        deltas.setdefault(p[0], []).append(p[2])
    shrunk = {v: (len(d) * st.mean(d) + VENDOR_OFFSET_PRIOR_N * delta_global) / (len(d) + VENDOR_OFFSET_PRIOR_N)
              for v, d in deltas.items()}
    return delta_global, shrunk, len(pairs)


def _colstats(pool, bids):
    stats = {}
    for bid in bids:
        xs = [_score_entries(m["scores"][bid])[0]["score"] for m in pool
              if bid in m.get("scores", {}) and len(_score_entries(m["scores"][bid])) == 1]
        if len(xs) >= 2 and st.pstdev(xs) > 1e-9:
            stats[bid] = (st.mean(xs), st.pstdev(xs))
    return stats


def _skew(scores, stats):
    """coding-vs-general z gap; a side with no observed benchmark sits at the pool mean (0)."""
    def zmean(bids):
        zs = [(scores[b] - stats[b][0]) / stats[b][1] for b in bids if b in scores and b in stats]
        return st.mean(zs) if zs else 0.0
    return zmean([b for b in scores if b in CODING_BENCHES]), zmean([b for b in scores if b in GENERAL_BENCHES])


def _fit_skew(pool, fits, stats):
    """Layer 3: regress (inverse-variance estimate - true AA) on the skew of pool models.
    Returns (alpha, beta, n); corrections are subtracted from the estimate."""
    pts = []
    for m in pool:
        scores = {b: _score_entries(m["scores"][b])[0]["score"] for b in fits if b in m.get("scores", {})}
        if not scores or m.get("aa_index") is None:
            continue
        ws = [(fits[b]["a"] + fits[b]["b"] * scores[b], 1.0 / fits[b]["s2"]) for b in scores]
        implied = sum(v * w for v, w in ws) / sum(w for _, w in ws)
        zc, zg = _skew(scores, stats)
        pts.append((zc - zg, implied - m["aa_index"]))
    if len(pts) < 20 or st.pstdev([p[0] for p in pts]) < 1e-9:
        return 0.0, 0.0, len(pts)
    f = _ols([p[0] for p in pts], [p[1] for p in pts])
    return f["a"], f["b"], len(pts)


def est_a(target, bench, pool, rules):
    """Challenger A: implied AA per claim from the benchmark fit line, claims weighted by
    inverse residual variance of that line; vendor-reported scores de-biased by the three-
    layer offset; the whole estimate then corrected by the fitted skew regression."""
    registry = bench.get("benchmarks", {})
    claims = [c for c in bench.get("claims", []) if c["model"] == target["id"] and not c.get("excluded")
              and c["benchmark"] in registry]
    if not claims:
        return None
    fits = _a_fits(pool, registry, rules)
    delta_global, deltas, n_pairs = _offsets_from_pairs(pool)
    stats = _colstats(pool, list(fits))
    alpha, beta, n_skew = _fit_skew(pool, fits, stats)
    A_STATE.update({"n_pairs": n_pairs, "delta_global": round(delta_global, 2),
                    "vendor_deltas": {k: round(v, 2) for k, v in deltas.items()},
                    "skew_alpha": round(alpha, 2), "skew_beta": round(beta, 2), "n_skew": n_skew})

    used = []
    for c in claims:
        f = fits.get(c["benchmark"])
        if not f:
            continue
        src = _claim_src(c)
        score = c["score"] - (delta_global + deltas.get(_vendor_of(target["id"]), 0.0)) if src == "vendor" else c["score"]
        used.append({"benchmark": c["benchmark"], "url": c["url"],
                     "implied": f["a"] + f["b"] * score, "w": 1.0 / f["s2"]})
    benches = {u["benchmark"] for u in used}
    sources = {u["url"].split("/")[2] for u in used}
    if len(benches) < rules["min_benchmarks"] or len(sources) < rules["min_sources"]:
        return None
    center = sum(u["implied"] * u["w"] for u in used) / sum(u["w"] for u in used)
    scores = {}
    for c in claims:
        if c["benchmark"] in benches:
            scores[c["benchmark"]] = c["score"]
    zc, zg = _skew(scores, stats)
    center -= alpha + beta * (zc - zg)
    width = rules["band_width"]
    low = round(center - width / 2)
    return {"status": "ok", "center": round(center, 1), "low": low, "high": low + width,
            "benchmarks": len(benches), "used": sorted(benches)}


# ---------- challenger C: low-rank completion (soft-impute), control only ----------
# Hand-rolled stdlib linear algebra: numpy is not installed on this box and the tool's
# stdlib-only promise (build/tuner hosts) outranks the "pure numpy" fallback in the brief.

def jacobi_eig(src, max_sweeps=20, tol=1e-10):
    """Eigen-decomposition of a symmetric matrix by cyclic Jacobi. -> (eigenvalues desc,
    eigenvectors as columns). Size here is 11x11; convergence is a few sweeps."""
    n = len(src)
    A = [row[:] for row in src]
    V = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for _ in range(max_sweeps):
        off = sum(A[p][q] ** 2 for p in range(n - 1) for q in range(p + 1, n))
        if off < tol * max(1.0, sum(A[i][i] ** 2 for i in range(n))):
            break
        for p in range(n - 1):
            for q in range(p + 1, n):
                if abs(A[p][q]) < 1e-14:
                    continue
                # with the (col,row) update below, A'[p][q] = a_pq cos2t + (a_pp-a_qq)/2 sin2t
                theta = 0.5 * math.atan2(-2.0 * A[p][q], A[p][p] - A[q][q])
                c, s = math.cos(theta), math.sin(theta)
                for k in range(n):
                    akp, akq = A[k][p], A[k][q]
                    A[k][p] = c * akp - s * akq
                    A[k][q] = s * akp + c * akq
                for k in range(n):
                    akp, akq = A[p][k], A[q][k]
                    A[p][k] = c * akp - s * akq
                    A[q][k] = s * akp + c * akq
                for k in range(n):
                    vkp, vkq = V[k][p], V[k][q]
                    V[k][p] = c * vkp - s * vkq
                    V[k][q] = s * vkp + c * vkq
    evals = [A[i][i] for i in range(n)]
    order = sorted(range(n), key=lambda i: -evals[i])
    return [evals[i] for i in order], [[V[r][i] for r in range(n)] for i in order]  # vecs: i-th vector = vecs[i][r]


def svd_transform(M, lam=0.0, rank=None):
    """Right singular vectors via the Gram matrix, then rebuild with the singular values
    soft-thresholded (lam) or hard-truncated (rank). -> (transformed matrix, kept components)."""
    rows, cols = len(M), len(M[0])
    G = [[sum(M[r][i] * M[r][j] for r in range(rows)) for j in range(cols)] for i in range(cols)]
    evals, V = jacobi_eig(G)
    keep = []
    for i, ev in enumerate(evals):
        sig = math.sqrt(ev) if ev > 0 else 0.0
        if sig < 1e-9:
            f = 0.0
        elif rank is not None:
            f = 1.0 if len(keep) < rank else 0.0
        else:
            f = max(sig - lam, 0.0) / sig
        keep.append(f)
    # V[i] is the i-th right singular vector (component j at V[i][j])
    MV = [[sum(M[r][j] * V[i][j] for j in range(cols)) * keep[i] for i in range(cols)] for r in range(rows)]
    out = [[sum(MV[r][i] * V[i][j] for i in range(cols)) for j in range(cols)] for r in range(rows)]
    return out, sum(1 for f in keep if f > 0)


def soft_impute(Z, obs, lam=0.0, rank=None, iters=80, tol=1e-9):
    """Fill the missing cells (obs=False) of the z-scored matrix Z by iterating
    X <- thresh(SVD)( P_obs(Z) + P_missing(X) ), X0 = observed part (Hastie et al.
    soft-impute, with hard truncation available). -> (X, last effective rank)."""
    rows, cols = len(Z), len(Z[0])
    X = [[Z[r][c] if obs[r][c] else 0.0 for c in range(cols)] for r in range(rows)]
    last_rank = 0
    for _ in range(iters):
        M = [[Z[r][c] if obs[r][c] else X[r][c] for c in range(cols)] for r in range(rows)]
        Xn, last_rank = svd_transform(M, lam, rank)
        num = sum((Xn[r][c] - X[r][c]) ** 2 for r in range(rows) for c in range(cols))
        den = sum(Xn[r][c] ** 2 for r in range(rows) for c in range(cols)) + 1e-12
        X = Xn
        if num < tol * den:
            break
    return X, last_rank


_C_HYP = {}  # selected hyper-parameter + CV table, computed once per process on the pool


def _c_candidates():
    return ([("soft", lam) for lam in (1.0, 2.0, 4.0, 8.0, 16.0)]
            + [("hard", k) for k in (2, 3, 4)])  # ADR-031: keep effective rank in 2-4


def _c_select(rows, cols, aa_col, folds=5):
    """5-fold CV over models: hide a fold's AA cells, complete, mean |z error| on them.
    Soft-impute candidates must keep the effective rank inside 2-4."""
    n = len(rows)
    cand = _c_candidates()
    table = {}
    for mode, param in cand:
        errs, ranks = [], []
        for f in range(folds):
            hidden = [i for i in range(n) if i % folds == f]
            obs = [[v is not None and not (j == aa_col and i in hidden) for j, v in enumerate(row)]
                   for i, row in enumerate(rows)]
            X, rk = soft_impute([[0.0 if v is None else v for v in row] for row in rows], obs,
                                **({"lam": param} if mode == "soft" else {"rank": param}))
            errs.append(st.mean(abs(X[i][aa_col] - rows[i][aa_col]) for i in hidden if rows[i][aa_col] is not None))
            ranks.append(rk)
        mean_rank = st.mean(ranks)
        ok = 2 <= mean_rank <= 4
        table[(mode, param)] = (round(st.mean(errs), 4), round(mean_rank, 1), ok)
    valid = [(err, key) for key, (err, _rk, ok) in table.items() if ok]
    sel = min(valid)[1] if valid else ("hard", 3)
    return sel, table


def est_c(target, bench, pool, rules):
    """Challenger C: z-score the models x (benchmarks + AA) matrix, complete it at low
    rank, read the hidden AA cell back. Control, not a candidate champion."""
    registry = bench.get("benchmarks", {})
    bids = sorted(registry)
    claims = [c for c in bench.get("claims", []) if c["model"] == target["id"] and not c.get("excluded")
              and c["benchmark"] in registry]
    if not claims:
        return None
    rows_raw = []
    for m in pool:
        if m.get("aa_index") is None:
            continue
        row = []
        for b in bids:
            cell = m.get("scores", {}).get(b)
            row.append(None if cell is None else _score_entries(cell)[0]["score"])
        row.append(m["aa_index"])
        rows_raw.append(row)
    t_scores = {c["benchmark"]: c["score"] for c in claims}
    t_row = [t_scores.get(b) for b in bids] + [None]
    rows_raw.append(t_row)

    cols = list(zip(*rows_raw))
    stats = []
    for col in cols:
        seen = [v for v in col if v is not None]
        mu = st.mean(seen)
        sd = st.pstdev(seen) if len(seen) >= 2 else 0.0
        stats.append((mu, sd if sd > 1e-9 else 1.0))
    Z = [[(v - stats[j][0]) / stats[j][1] if v is not None else None for j, v in enumerate(row)] for row in rows_raw]

    aa_col = len(bids)
    if not _C_HYP:
        sel, table = _c_select([[v for v in r] for r in Z[:-1]], aa_col, aa_col)
        _C_HYP.update({"sel": sel, "cv": {f"{m}:{p}": v for (m, p), v in table.items()}})
    mode, param = _C_HYP["sel"]
    obs = [[v is not None for v in row] for row in Z]
    X, _rk = soft_impute([[0.0 if v is None else v for v in row] for row in Z], obs,
                         **({"lam": param} if mode == "soft" else {"rank": param}))
    center = X[-1][aa_col] * stats[aa_col][1] + stats[aa_col][0]

    used = sorted(t_scores)
    sources = {c["url"].split("/")[2] for c in claims if c["benchmark"] in t_scores}
    if len(used) < rules["min_benchmarks"] or len(sources) < rules["min_sources"]:
        return None
    width = rules["band_width"]
    low = round(center - width / 2)
    return {"status": "ok", "center": round(center, 1), "low": low, "high": low + width,
            "benchmarks": len(used), "used": used}


def est_b(target, bench, pool, rules):
    """Challenger B (ADR-031): estimate from the AA sub-score structure - the vendor
    benchmarks are exactly AA's sub-scores, so align each to AA scale and average.
    Blocked on AA per-model sub-scores, i.e. AA_API_KEY (16b-3), which has not arrived."""
    sys.exit("challenger b is a placeholder: it needs AA sub-scores, i.e. the AA_API_KEY "
             "(16b-3) in chco .env. Nothing to fit yet - see BRIEF 16c.")


ESTIMATORS = {"v1": est_v1, "a": est_a, "b": est_b, "c": est_c}
CHALLENGERS = ["a", "b", "c"]


# ---------- leave-one-out run ----------

def run_backtest(anchors, registry, estimator, rules):
    """Hide each reference model's AA, rebuild it from the others, score the difference."""
    rows = []
    for a in anchors:
        name = a["name"]
        src_by_bid = {bid: _score_entries(sc)[0].get("src", "unknown")
                      for bid, sc in a.get("scores", {}).items() if len(_score_entries(sc)) == 1}
        claims = [
            {
                "model": name,
                "benchmark": bid,
                "score": sc["score"],
                "source_type": registry.get(bid, {}).get("source_type", "leaderboard"),
                "src": sc.get("src", "unknown"),
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
        used = e.get("used") or [c["benchmark"] for c in claims]
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
            "src_group": "+".join(sorted({src_by_bid.get(b, "unknown") for b in used})),
        })
    return rows


def summarize(rows):
    """Overall + grouped (benchmarks used, source types of the scores used) mean diff /
    bias / 5-point hit rate. The source group is the set of per-score `src` labels
    (16b) on the benchmarks the estimate actually used - mixed groups included."""
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
        "by_source_type": {g: agg([r for r in rows if r["src_group"] == g])
                           for g in sorted({r["src_group"] for r in rows})},
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


def est_label(name):
    return f"`{name}`" + (" (champion)" if name == "v1" else " (challenger)")


def report_md(date, est_name, rules, summ, fwd, n_targets):
    ov = summ["overall"]
    nb_keys = sorted(summ["by_n_benchmarks"], key=int)
    lines = [
        f"# EST backtest · {date}",
        "",
        f"- Estimator: {est_label(est_name)} (champion = `build.estimate()`, imported not copied)",
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
        f"| {est_label(est_name)} | **{fmt(ov['mean_abs_diff'])}** | {fmt(ov['bias'])} | {fmt(ov['hit_rate'])} |",
        "",
        "Baseline (v1 on the 16a data, hand check Dim 2026-10-22): n=136 · mean abs diff 4.53 · hit rate 0.30.",
        "Reproduced by this tool; on the 16b data the same champion scores 4.26 / 0.35.",
        "",
        "### By number of benchmarks used",
        "",
        "| benchmarks used | models | mean abs diff | bias | hit rate |",
        "|---|---|---|---|---|",
    ]
    for k in nb_keys:
        g = summ["by_n_benchmarks"][k]
        lines.append(f"| {k} | {g['n']} | {fmt(g['mean_abs_diff'])} | {fmt(g['bias'])} | {fmt(g['hit_rate'])} |")
    lines += [
        "",
        f"More evidence, better estimate ({nb_keys[0]} → {nb_keys[-1]} benchmarks here), as ADR-031 expects. "
        "The deepest cells are small, so read them as a hint, not a proof.",
        "",
        "### By source type of the scores used",
        "",
        "The group is the set of per-score `src` labels (16b) on the benchmarks the estimate actually "
        "used; `a+b` means the estimate mixed them. Since 16b the fitted benchmarks draw on public "
        "leaderboards *and* third-party re-runs, so this split is live.",
        "",
        "| source group | models | mean abs diff | bias | hit rate |",
        "|---|---|---|---|---|",
    ]
    for g_name, g in summ["by_source_type"].items():
        lines.append(f"| {g_name} | {g['n']} | {fmt(g['mean_abs_diff'])} | {fmt(g['bias'])} | {fmt(g['hit_rate'])} |")
    lines += [
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


# ---------- challenger comparison (--estimator all) ----------

def run_est_table(anchors, bench_doc, registry, rules, est_names):
    """The nine live EST models scored under each estimator - the side-effect view:
    what the website would say if a challenger ever won."""
    build.LANG = "en"
    ids = sorted({c["model"] for c in bench_doc.get("claims", [])})
    table = {mid: {} for mid in ids}
    for name in est_names:
        for mid in ids:
            e = ESTIMATORS[name]({"id": mid, "aa_index": {"value": None}}, bench_doc, anchors, rules)
            table[mid][name] = e
    return table


def comparison_md(date, rules, summs, est_table, n_anchors):
    names = [n for n in ["v1", "a", "c"] if n in summs]
    lines = [
        f"# EST estimator comparison · {date}",
        "",
        f"- Leave-one-out backtest, {n_anchors} reference models, band width {rules['band_width']}, "
        f"`est_rules.version = {rules.get('version')}`. Same data for everyone; nothing is deployed.",
        "- `v1` champion = `build.estimate()` · `a` inverse-variance + three-layer vendor offset · "
        "`c` low-rank soft-impute (control) · `b` skipped: needs AA sub-scores (AA_API_KEY, 16b-3).",
        "",
        "## Backtest, side by side",
        "",
        "| estimator | n | mean abs diff | bias | hit rate |",
        "|---|---|---|---|---|",
    ]
    for name in names:
        ov = summs[name]["overall"]
        lines.append(f"| {est_label(name)} | {ov['n']} | **{fmt(ov['mean_abs_diff'])}** | {fmt(ov['bias'])} | {fmt(ov['hit_rate'])} |")
    lines += ["", "### By number of benchmarks used (mean abs diff · hit rate)", ""]
    nb_keys = sorted({k for n in names for k in summs[n]["by_n_benchmarks"]}, key=int)
    lines.append("| benchmarks | " + " | ".join(names) + " |")
    lines.append("|---|" + "---|" * len(names))
    for k in nb_keys:
        cells = []
        for n in names:
            g = summs[n]["by_n_benchmarks"].get(k)
            cells.append(f"{fmt(g['mean_abs_diff'])} · {fmt(g['hit_rate'])} ({g['n']})" if g else "—")
        lines.append(f"| {k} | " + " | ".join(cells) + " |")
    src_keys = sorted({k for n in names for k in summs[n]["by_source_type"]})
    lines += ["", "### By source group of the scores used (mean abs diff · hit rate)", "",
              "| source group | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for g_name in src_keys:
        cells = []
        for n in names:
            g = summs[n]["by_source_type"].get(g_name)
            cells.append(f"{fmt(g['mean_abs_diff'])} · {fmt(g['hit_rate'])} ({g['n']})" if g else "—")
        lines.append(f"| {g_name} | " + " | ".join(cells) + " |")

    lines += ["", "## The nine live EST models under each estimator", "",
              "| model | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for mid, row in sorted(est_table.items()):
        cells = []
        for n in names:
            e = row.get(n)
            cells.append(f"{e['center']} [{e['low']}–{e['high']}]" if e else "insufficient")
        lines.append(f"| {mid} | " + " | ".join(cells) + " |")

    champ = summs["v1"]["overall"] if "v1" in summs else None
    lines += ["", "## Champion-change rule", ""]
    winners = []
    if champ:
        for name in names:
            if name == "v1":
                continue
            ov = summs[name]["overall"]
            if ov["mean_abs_diff"] < champ["mean_abs_diff"] and ov["hit_rate"] > champ["hit_rate"]:
                winners.append(name)
    if winners:
        lines.append(f"- **等正手：EST 冠军** — {', '.join(est_label(w) for w in winners)} beats the champion on both "
                     "overall mean abs diff and hit rate. First champion change requires Dim to read this "
                     "scorecard (ADR-031 item 4). No switch made, no deployment, changes stay in the working tree.")
        lines.append("- Read the tables before switching: the win may be overall-only. Check the challenger's bias, "
                     "the deep-evidence rows (the champion's peer anchoring, ADR-023, wins there) and the nine-model "
                     "table — a switch that moves any live EST past 25/30/35 or by more than 3 points trips the "
                     "ADR-031 stop lines regardless of backtest rank.")
    else:
        lines.append("- No challenger beats the champion (`v1`) on both mean abs diff and 5-point hit rate "
                    "⇒ **no champion change**; `v1` stays, nothing to switch, nothing to deploy.")
    if A_STATE:
        lines += ["", "## Challenger A diagnostics (from the full-pool run)", "",
                  f"- Vendor-offset pairs (same model + benchmark, vendor & third-party both present): "
                  f"**{A_STATE.get('n_pairs', 0)}** → global offset {A_STATE.get('delta_global')} "
                  f"(per-vendor: {A_STATE.get('vendor_deltas') or 'none'}). With 0 pairs the layer is exact but idle.",
                  f"- Skew-correction fit: alpha {A_STATE.get('skew_alpha')}, beta {A_STATE.get('skew_beta')} "
                  f"on {A_STATE.get('n_skew')} pool models (coding−general z gap, activation-parameter proxy)."]
    if _C_HYP:
        cv = _C_HYP.get("cv", {})
        sel = _C_HYP["sel"]
        lines += ["", "## Challenger C hyper-parameter (5-fold AA-cell CV on the pool)", "",
                  f"- Selected: **{sel[0]}:{sel[1]}** (effective rank kept in 2–4). CV mean |z error|:", "",
                  "| candidate | z error | mean rank | rank in 2–4 |", "|---|---|---|---|"]
        for k, (err, rk, ok) in sorted(cv.items()):
            mark = " ← selected" if k == f"{sel[0]}:{sel[1]}" else ""
            lines.append(f"| {k} | {fmt(err, 4)} | {rk} | {'✓' if ok else '✗'}{mark} |")
    lines += ["", "ADR-031 item 4: champions change only on backtest evidence *and*, for the first time, Dim's "
              "read of this scorecard. This file is that read; the production estimator in build.py is untouched.", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--estimator", default="v1", choices=sorted(ESTIMATORS) + ["all"])
    ap.add_argument("--no-write", action="store_true", help="print the report, do not touch files")
    a = ap.parse_args()

    build.LANG = "en"
    rules = build.SCHEMA["est_rules"]
    anchors = load("anchors", [])
    bench_doc = load("benchmarks", {})
    registry = bench_doc.get("benchmarks", {})
    history = load("est_history", [])

    if a.estimator == "all":
        names = [n for n in ["v1", "a", "c"] if n in ESTIMATORS]
        summs = {n: summarize(run_backtest(anchors, registry, ESTIMATORS[n], rules)) for n in names}
        est_table = run_est_table(anchors, bench_doc, registry, rules, names)
        text = comparison_md(a.date, rules, summs, est_table, len(anchors))
        if not a.no_write:
            rep_dir = ROOT / ".private" / "reports" / "est-backtest"
            rep_dir.mkdir(parents=True, exist_ok=True)
            (rep_dir / f"{a.date}-challengers.md").write_text(text)
            print(f"  → .private/reports/est-backtest/{a.date}-challengers.md (scorecard untouched)")
        for n in names:
            ov = summs[n]["overall"]
            print(f"  {n:3s} n={ov['n']} · mean abs diff {fmt(ov['mean_abs_diff'])} · bias {fmt(ov['bias'])} · hit {fmt(ov['hit_rate'])}")
        print(f"  b skipped: awaiting AA_API_KEY (16b-3); present in env: {int('AA_API_KEY' in os.environ)}")
        return

    if a.estimator not in ESTIMATORS:
        sys.exit(f"unknown estimator {a.estimator!r}; have {sorted(ESTIMATORS)}")

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
