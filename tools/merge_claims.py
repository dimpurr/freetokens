#!/usr/bin/env python3
"""Validate benchmark claims from worker files and merge them into data/benchmarks.json (ADR-036).

Usage: python3 tools/merge_claims.py claims/G1.json [claims/G2.json ...] [--dry-run] [--report out.md]

Each file is a JSON array of
  {model, benchmark, score, variant, source_type, url, seen, quote?, peers?}
A row is rejected (and reported, never silently dropped) when
  - a field is missing or has the wrong type, the score is not a finite number, the date is not YYYY-MM-DD
  - the URL is not http(s), or its host is on DENY_HOSTS (Artificial Analysis and relays of it, arena sites
    whose terms forbid republishing, aggregators of unclear provenance)
  - the benchmark is AA-named (aa_*) or on DENY_BENCHMARKS, or the model id is not in data/models.json or is on DENY_MODELS
Accepted rows are normalised:
  - source_type official -> vendor; rows from VENDOR_HOSTS (model cards, relays of a vendor table) are vendor
  - benchmark names are lowercased; `gpqa` becomes `gpqa_diamond` only when the variant says Diamond
  - peers keep {name, score}; a reference score a worker supplied (`ref`) moves to the private
    ft-reference.json (peers map), never into the public file
  - duplicates (same model, benchmark, url, score) are dropped
`quote` is kept for audit; no page ever displays it.
Standard library only; no network.
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from ft_calibrate import private_dir  # noqa: E402

TYPES = {"leaderboard", "third_party", "vendor", "community", "leak"}
DENY_HOSTS = {
    "artificialanalysis.ai": "Artificial Analysis data (ADR-036: AA only through the private snapshot)",
    "lmarena.ai": "terms forbid republishing", "arena.ai": "terms forbid republishing",
    "benchlm.ai": "provenance unclear, may relay Artificial Analysis",
}
DENY_BENCHMARKS = {"jevbench": "provenance unclear"}
DENY_MODELS = {"big-pickle": "identity undisclosed"}
VENDOR_HOSTS = {"huggingface.co", "essamamdani.com", "aimlapi.com", "tech.ifeng.com"}  # model cards and relays of a vendor table


def host_of(url):
    return (urlparse(url).hostname or "").lower()


def host_in(host, hosts):
    return any(host == h or host.endswith("." + h) for h in hosts)


def check(r, model_ids):
    """Returns (normalised row, None) or (None, reason)."""
    need = {"model": str, "benchmark": str, "source_type": str, "url": str, "seen": str, "variant": str}
    for k, t in need.items():
        if not isinstance(r.get(k), t) or not r[k].strip():
            return None, f"missing or empty field {k}"
    sc = r.get("score")
    if isinstance(sc, bool) or not isinstance(sc, (int, float)) or not math.isfinite(sc):
        return None, "score is not a finite number"
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["seen"]):
        return None, "seen is not YYYY-MM-DD"
    u = urlparse(r["url"])
    if u.scheme not in ("http", "https") or not u.hostname:
        return None, "URL is not http(s)"
    h = host_of(r["url"])
    for d, why in DENY_HOSTS.items():
        if host_in(h, [d]):
            return None, f"host {h}: {why}"
    b = r["benchmark"].strip().lower()
    if not re.fullmatch(r"[a-z0-9_]+", b):
        return None, f"benchmark name {r['benchmark']!r} is not lowercase_underscore"
    if b.startswith("aa_"):
        return None, "AA-named benchmark"
    if b in DENY_BENCHMARKS:
        return None, f"benchmark {b}: {DENY_BENCHMARKS[b]}"
    if r["model"] in DENY_MODELS:
        return None, f"model {r['model']}: {DENY_MODELS[r['model']]}"
    if r["model"] not in model_ids:
        return None, f"unknown model id {r['model']!r}"
    if r["source_type"] not in TYPES and r["source_type"] != "official":
        return None, f"source_type {r['source_type']!r} not one of {sorted(TYPES)}"
    if b == "gpqa" and "diamond" in r["variant"].lower():
        b = "gpqa_diamond"
    st = "vendor" if r["source_type"] == "official" else r["source_type"]
    if host_in(h, VENDOR_HOSTS):
        st = "vendor"
    out = {"model": r["model"], "benchmark": b, "score": sc, "variant": r["variant"].strip(), "source_type": st, "url": r["url"], "seen": r["seen"]}
    for k in ("quote", "excluded"):
        if r.get(k):
            out[k] = r[k]
    if r.get("peers"):
        out["peers"] = [{k: p[k] for k in ("name", "score", "ref") if k in p} for p in r["peers"] if "name" in p and "score" in p]
    return out, None


def key(c):
    return (c["model"], c["benchmark"], c["url"], round(c["score"], 2))


def merge(rows, bench, model_ids, private_peers=None):
    """Returns (accepted, rejected[(row, reason)], dups). Mutates bench['claims']; moves peer refs into private_peers."""
    have = {key(c) for c in bench["claims"]}
    acc, rej, dup = [], [], []
    for r in rows:
        n, why = check(r, model_ids)
        if why:
            rej.append((r, why))
            continue
        if key(n) in have:
            dup.append(n)
            continue
        have.add(key(n))
        if n.get("peers") and private_peers is not None:
            refs = [{"name": p["name"], "ref": p["ref"]} for p in n["peers"] if p.get("ref") is not None]
            if refs:
                private_peers[f"{n['model']}|{n['benchmark']}"] = refs
        if n.get("peers"):
            n["peers"] = [{"name": p["name"], "score": p["score"]} for p in n["peers"]]
        bench["claims"].append(n)
        acc.append(n)
    return acc, rej, dup


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report")
    a = ap.parse_args()
    bpath = ROOT / "data/benchmarks.json"
    bench = json.loads(bpath.read_text())
    model_ids = {m["id"] for m in json.loads((ROOT / "data/models.json").read_text())}
    rows = []
    for f in a.files:
        for r in json.loads(Path(f).read_text(encoding="utf-8")):
            rows.append(dict(r, _file=Path(f).name))
    ref_path = private_dir() / "ft-reference.json"
    ref = json.loads(ref_path.read_text()) if ref_path.exists() else None
    peers = ref["peers"] if ref else None
    acc, rej, dup = merge([{k: v for k, v in r.items() if k != "_file"} for r in rows], bench, model_ids, peers)
    lines = [f"merge_claims: {len(rows)} rows read · {len(acc)} accepted · {len(dup)} duplicates · {len(rej)} rejected"]
    for r, why in rej:
        lines.append(f"  REJECT {r.get('model')} / {r.get('benchmark')} = {r.get('score')} ({host_of(r.get('url') or '') or 'no host'}): {why}")
    text = "\n".join(lines)
    print(text)
    if a.report:
        Path(a.report).write_text(text + "\n")
    if not a.dry_run:
        bpath.write_text(json.dumps(bench, indent=2, ensure_ascii=False) + "\n")
        if ref is not None:
            ref_path.write_text(json.dumps(ref, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
