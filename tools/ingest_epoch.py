#!/usr/bin/env python3
"""Read the Epoch AI Benchmarking Hub download (CC BY 4.0) into FT Intelligence evidence (ADR-036).

Run it as `python3 -I tools/ingest_epoch.py --data <dir with csv/>`: the download is untrusted data, so the
interpreter runs isolated and only plain csv parsing touches it.

Used: the main benchmark CSVs (file name without `_external`) and the Epoch Capabilities Index (ECI).
Not used: every `*_external.csv` (third-party data Epoch only relays, with its own terms), and any file
that mentions Artificial Analysis. Credit: Epoch AI, 'Capabilities & benchmarking', epoch.ai/benchmarks, CC BY 4.0.

Per model and benchmark the best score over Epoch's effort settings is taken ("best reported setting",
as for the other leaderboards); ECI uses the model's single ECI row.

A model with `snapshots` in models.json is matched per snapshot on the exact name `<id>-<snapshot id>` (Epoch writes
`deepseek-v4.1-flash-1017_max`); each claim carries its `snapshot`, and the reference score of such a model is paired
only with the current snapshot's rows.
Names are matched exactly after normalising (lowercase, alphanumerics only, effort suffix `_high`/`_max`... removed),
the rule of match_epoch.py. A match is refused (and listed) when
  - Epoch also carries a dated snapshot of the same name (name plus 3-4 digits, e.g. ...flash0731): which one the
    plain name means is unknown, or
  - the model is on DOUBTFUL (identity or snapshot unverified, from the 2026-11-01 Epoch coverage review).

Writes
  data/benchmarks.json   registry entries epoch_* (only for benchmarks that pass the registry rule); old epoch_* claims are dropped
                         so a re-run replaces them (merge the new claims file afterwards)
  <claims-out>           public claims for site models (merge them with tools/merge_claims.py)
  $FT_PRIVATE/ft-reference.json   Epoch scores of the reference models, the data the lines are fitted on
"""
import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from ft_calibrate import private_dir, fit  # noqa: E402

HUB = "https://epoch.ai/benchmarks"
NOT_BENCH = {"benchmark_metadata.csv", "model_metadata.csv"}
DOUBTFUL = {
    "deepseek-v4-flash": "Epoch carries dated snapshots; which one the plain name is was not verified",
    "deepseek-v4.1-flash": "snapshot identity (1017 in-place upgrade) not verified against Epoch's rows",
    "muse-spark-1.3-contributor": "Epoch entry is the plain Muse Spark; Contributor access not verified as the same model",
    "muse-spark-1.2-contributor": "Epoch entry is the plain Muse Spark; Contributor access not verified as the same model",
    "qwen3.8-flash": "our own notes say the identity is an assumption",
    "hy4-preview": "single file, effort unknown, identity not verified",
    "mistral-small-3.2": "Epoch has mistral-small-3.2-2506, same family but not an exact name",
    "beam": "release date in Epoch's ECI row disagrees with ours",
}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def strip_effort(s):
    return s.rsplit("_", 1)[0] if "_" in s else s


def effort_of(s):
    return s.rsplit("_", 1)[1] if "_" in s else "unspecified"


def read_epoch(base):
    """-> bench{stem: {key: (best score 0-100, effort)}}, eci{key: (eci, date)}, allkeys, skipped_files"""
    bench, eci, allkeys, skipped = {}, {}, set(), []
    meta = {}
    with open(base / "benchmark_metadata.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("source_file"):
                meta[r["source_file"]] = r["benchmark"]
    for p in sorted(base.glob("*.csv")):
        if p.name in NOT_BENCH or p.stem.endswith("_external"):
            continue
        text = p.read_text(encoding="utf-8")
        if "artificialanalysis" in text.lower():
            skipped.append(p.name)
            continue
        rows = {}
        for r in csv.DictReader(text.splitlines()):
            name = (r.get("Model version") or "").strip()
            v = r.get("Best score (across scorers)") or r.get("mean_score")
            if not name or v in (None, ""):
                continue
            try:
                v = float(v) * 100
            except ValueError:
                continue
            k = norm(strip_effort(name))
            allkeys.add(k)
            if k not in rows or v > rows[k][0]:
                rows[k] = (v, effort_of(name))
        if rows:
            bench[p.stem] = rows
    ep = base / "epoch_capabilities_index" / "eci_scores.csv"
    with open(ep, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                v = float(r["eci"])
            except (ValueError, KeyError):
                continue
            for name in (r.get("Model"), r.get("Display name")):
                if name:
                    allkeys.add(norm(name))
                    eci.setdefault(norm(name), (v, r.get("date")))
    return bench, eci, allkeys, skipped, meta


def match_keys(names):
    ks = []
    for n in names:
        if not n:
            continue
        for k in (norm(n), norm(re.sub(r"\(.*?\)", "", n))):
            if k and k not in ks:
                ks.append(k)
    return ks


def ambiguous(k, allkeys):
    return any(o != k and o.startswith(k) and re.fullmatch(r"\d{3,4}", o[len(k):]) for o in allkeys)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="folder holding csv/ (the unzipped Epoch download)")
    ap.add_argument("--claims-out", required=True)
    ap.add_argument("--today", default="2026-11-01")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    rules = json.loads((ROOT / "schema/schema.json").read_text())["ft_rules"]
    base = Path(a.data) / "csv"
    bench, eci, allkeys, skipped_files, meta = read_epoch(base)
    series = dict(bench)
    series["eci"] = {k: (v, "eci") for k, (v, _d) in eci.items()}
    models = json.loads((ROOT / "data/models.json").read_text())
    pdir = private_dir()
    refdoc = json.loads((pdir / "ft-reference.json").read_text())

    refused = []
    snap_models = {m["id"]: m["snapshots"] for m in models if m.get("snapshots")}  # ADR-037: exact snapshot names only

    def find(names, mid=None):
        if mid in DOUBTFUL:
            refused.append((mid or names[0], DOUBTFUL[mid]))
            return None
        ks = match_keys(names)
        if any(ambiguous(k, allkeys) for k in ks if any(k in s for s in series.values())):
            refused.append((mid or names[0], "Epoch also has a dated snapshot of this name"))
            return None
        return ks

    # reference models: Epoch scores become private fit data
    ref_hits = {s: [] for s in series}
    for m in refdoc["models"]:
        slug = (m.get("aa_url") or "").rsplit("/", 1)[-1]
        if m.get("id") in snap_models:  # the reference score is the current snapshot's: match only its exact Epoch name
            ks = [norm(m["id"] + "-" + snap_models[m["id"]][-1]["id"])]
        else:
            ks = find([m["name"], m.get("id"), slug], m.get("id"))
        m["scores"] = {k: v for k, v in m["scores"].items() if not k.startswith("epoch_")}
        if not ks:
            continue
        for s, rows in series.items():
            for k in ks:
                if k in rows:
                    ref_hits[s].append((rows[k][0], m["ref"]))
                    m["scores"]["epoch_" + s] = {"score": round(rows[k][0], 2), "url": HUB, "src": "third_party", "seen": a.today,
                                                 "variant": "Epoch AI Benchmarking Hub, best effort setting" if s != "eci" else "Epoch Capabilities Index"}
                    break
    good = {s for s, pts in ref_hits.items() if (f := fit(pts, rules)) and f["ok"]}

    claims, site_hits = [], set()
    for m in models:
        if m["id"] in snap_models:  # one claim set per snapshot, tagged; the plain name is never used (it could be any snapshot)
            for sn in snap_models[m["id"]]:
                k = norm(m["id"] + "-" + sn["id"])
                for s in sorted(good):
                    if k in series[s]:
                        v, eff = series[s][k]
                        site_hits.add(m["id"])
                        claims.append({"model": m["id"], "benchmark": "epoch_" + s, "score": round(v, 2), "source_type": "third_party", "snapshot": sn["id"],
                                       "variant": ("Epoch AI Benchmarking Hub, best of effort settings (" + eff + ")") if s != "eci" else "Epoch Capabilities Index",
                                       "url": HUB, "seen": a.today})
            continue
        ks = find([m["id"], m["name"]], m["id"])
        if not ks:
            continue
        for s in sorted(good):
            for k in ks:
                if k in series[s]:
                    v, eff = series[s][k]
                    site_hits.add(m["id"])
                    claims.append({"model": m["id"], "benchmark": "epoch_" + s, "score": round(v, 2), "source_type": "third_party",
                                   "variant": ("Epoch AI Benchmarking Hub, best of effort settings (" + eff + ")") if s != "eci" else "Epoch Capabilities Index",
                                   "url": HUB, "seen": a.today})
                    break

    reg_names = {"eci": ("Epoch Capabilities Index", "ECI points (Epoch AI), one composite index per model")}
    registry = {}
    for s in sorted(good):
        nm, metric = reg_names.get(s) or (meta.get(s + ".csv") or s.replace("_", " "), "Best score across scorers, %, best of effort settings (Epoch AI Benchmarking Hub)")
        registry["epoch_" + s] = {"name": nm + " (Epoch AI)", "metric": metric, "url": HUB, "source_type": "third_party"}
    print(f"epoch series read: {len(series)} (files skipped for mentioning AA: {skipped_files or 'none'})")
    for s, pts in sorted(ref_hits.items(), key=lambda kv: -len(kv[1])):
        f = fit(pts, rules)
        print(f"  {'USE ' if s in good else 'skip'} {s:34} reference n={len(pts):>3} " + (f"r={f.get('r', '-')}" if f else ""))
    print(f"site models with Epoch evidence: {len(site_hits)} · claims: {len(claims)} · refused matches: {len(refused)}")
    for mid, why in refused:
        print(f"  REFUSED {mid}: {why}")
    if not a.no_write:
        Path(a.claims_out).write_text(json.dumps(claims, indent=1, ensure_ascii=False) + "\n")
        (pdir / "ft-reference.json").write_text(json.dumps(refdoc, indent=1, ensure_ascii=False) + "\n")
        bp = ROOT / "data/benchmarks.json"
        b = json.loads(bp.read_text())
        b["benchmarks"] = {k: v for k, v in b["benchmarks"].items() if not k.startswith("epoch_")}
        b["benchmarks"].update(registry)
        b["claims"] = [c for c in b["claims"] if not c["benchmark"].startswith("epoch_")]  # re-ingest replaces, never stacks
        bp.write_text(json.dumps(b, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
