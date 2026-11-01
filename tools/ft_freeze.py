#!/usr/bin/env python3
"""One-time freeze for FT Intelligence (ADR-036).

Reads the data as it stood before FTI (git revision, default 40f6a788: anchors.json,
models.json, benchmarks.json) and writes

  $FT_PRIVATE/ft-reference.json   the frozen reference scores (old anchors) + published benchmark
                                  scores per reference model; the only input ft_calibrate.py fits on
  $FT_PRIVATE/aa-snapshot.json    the AA values models.json carried; a source, not a column
  <claims-out>                    public claims for the site models that were also reference models
                                  (their non-AA published scores), ready for tools/merge_claims.py

Nothing here is read by build.py. Run it once; the private files then stay frozen.
Standard library only; no network.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from ft_calibrate import private_dir, is_aa_url  # noqa: E402


def git_json(rev, path):
    return json.loads(subprocess.check_output(["git", "-C", str(ROOT), "show", f"{rev}:{path}"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rev", default="40f6a788")
    ap.add_argument("--claims-out", required=True)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    pd = private_dir()
    pd.mkdir(parents=True, exist_ok=True)
    if (pd / "ft-reference.json").exists() and not a.force:
        sys.exit("ft-reference.json already exists: the reference is frozen once (use --force to redo)")
    anchors = git_json(a.rev, "data/anchors.json")
    models = git_json(a.rev, "data/models.json")
    bench = git_json(a.rev, "data/benchmarks.json")

    by_url = {m["aa_index"]["url"]: m for m in models if m["aa_index"].get("value") is not None}
    ref, snap, claims = [], {}, []
    used_ids = set()
    for x in anchors:
        m = by_url.get(x["aa_url"])
        e = {"name": x["name"], "id": m["id"] if m else None, "ref": x["aa_index"], "aa_url": x["aa_url"],
             "seen": x.get("seen"), "scores": x["scores"]}
        for k in ("vendor_scores", "vendor_peers"):
            if x.get(k):
                e[k] = x[k]
        ref.append(e)
        if m:
            used_ids.add(m["id"])
            have = set()
            for bid, c in x["scores"].items():
                if bid.startswith("aa_") or is_aa_url(c.get("url", "")):
                    continue
                st = {"leaderboard": "leaderboard", "third_party": "third_party", "vendor": "vendor"}.get(c.get("src"), "community")
                have.add(bid)
                claims.append({"model": m["id"], "benchmark": bid, "score": c["score"],
                               "variant": c.get("variant") or "reference table score", "source_type": st,
                               "url": c["url"], "seen": c.get("seen") or x.get("seen") or "2026-10-25"})
            for bid, c in (x.get("vendor_scores") or {}).items():
                if bid in have or bid.startswith("aa_") or is_aa_url(c.get("url", "")):
                    continue
                cl = {"model": m["id"], "benchmark": bid, "score": c["score"],
                      "variant": (c.get("variant") or "vendor-reported")[:200], "source_type": "vendor",
                      "url": c["url"], "seen": c.get("seen") or "2026-10-25"}
                if x.get("vendor_peers", {}).get(bid):
                    cl["peers"] = [{"name": p["name"], "score": p["score"], "ref": p.get("aa")} for p in x["vendor_peers"][bid] if p.get("aa") is not None]
                claims.append(cl)
    for m in models:
        v = m["aa_index"]
        if v.get("value") is None:
            continue
        snap[m["id"]] = {k: v[k] for k in ("value", "date", "url", "basis", "prev_value", "prev_date") if k in v}
        if m["id"] not in used_ids:  # a site model with an AA score but no benchmark table: still a reference point
            ref.append({"name": m["name"], "id": m["id"], "ref": v["value"], "aa_url": v["url"], "seen": v.get("date"), "scores": {}})
    # peers of the existing public claims: their reference values go private, keyed by claim
    peers = {}
    for c in bench.get("claims", []):
        if c.get("peers"):
            peers[f"{c['model']}|{c['benchmark']}"] = [{"name": p["name"], "ref": p.get("aa")} for p in c["peers"] if p.get("aa") is not None]
    (pd / "ft-reference.json").write_text(json.dumps({"frozen": "2026-11-01", "from": a.rev,
        "note": "frozen reference scores, the scale of AA v5 at freeze time; private input of tools/ft_calibrate.py",
        "models": ref, "peers": peers}, indent=1, ensure_ascii=False) + "\n")
    (pd / "aa-snapshot.json").write_text(json.dumps({"frozen": "2026-11-01", "models": snap}, indent=1, ensure_ascii=False) + "\n")
    Path(a.claims_out).write_text(json.dumps(claims, indent=1, ensure_ascii=False) + "\n")
    print(f"reference models: {len(ref)} ({sum(1 for r in ref if r['id'])} on the site) · aa snapshot: {len(snap)} · claims for site models: {len(claims)} · peer sets: {len(peers)}")


if __name__ == "__main__":
    main()
