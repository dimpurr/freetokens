#!/usr/bin/env python3
"""Add reference benchmark scores to the private frozen reference (ADR-036; round 2 of the reference harvest).

Input: R*.json files, rows {reference_model, benchmark, score, variant, source_type, url, seen}.
Output: $FT_PRIVATE/ft-reference.json gets the scores under the reference model of that exact name.
        A reference model's frozen target score (`ref`) is never touched, and no existing score is overwritten.

Rules (the main session's, 2026-11-01):
  - rows on benchlm.ai, artificialanalysis.ai or llm-stats are dropped
  - benchmark names are put through ft_calibrate.canon(): terminal_bench_4 = terminal_bench_4_0, aime25 = aime_2025, claweval = claw_eval
    (deep_swe only counts as deepswe_v1_1 when its variant says 1.1); versions and harnesses are never merged
  - vendor and official rows go to `vendor_scores` (they get their own line); leaderboard and third-party rows go to `scores`
  - tau2_bench has 3 domains per model: they are averaged per model first, so n counts models
  - EXCLUDED benchmarks are not added (BrowseComp: the rows mix settings)
  - a row for a name that is not a reference model, or for a model with snapshots whose reference name does not carry the current snapshot id (its reference score belongs to that snapshot), is skipped
Usage: python3 tools/ft_add_reference.py R1.json R2.json ... [--report out.txt]
"""
import argparse
import collections
import json
import statistics as st
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from ft_calibrate import canon, private_dir  # noqa: E402

BLOCKED = ("benchlm.ai", "artificialanalysis.ai", "llm-stats.com")
EXCLUDED = {"browsecomp": "the rows mix settings (single agent, xhigh, search plus Python, thinking, context management): not one consistent configuration"}
AVERAGE_DOMAINS = {"tau2_bench"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--report")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    rows = []
    for f in a.files:
        rows += json.loads(Path(f).read_text(encoding="utf-8"))
    ref_path = private_dir() / "ft-reference.json"
    ref = json.loads(ref_path.read_text())
    by_name = {m["name"]: m for m in ref["models"]}
    snap_cur = {m["id"]: m["snapshots"][-1]["id"] for m in json.loads((ROOT / "data/models.json").read_text()) if m.get("snapshots")}
    log = collections.Counter()
    notes, groups = [], collections.defaultdict(list)
    for r in rows:
        host = urlparse(r["url"]).hostname or ""
        if any(host == d or host.endswith("." + d) for d in BLOCKED):
            log["blocked url"] += 1
            continue
        bid = canon(r["benchmark"], r.get("variant", ""))
        if bid in EXCLUDED:
            log["excluded benchmark " + bid] += 1
            continue
        m = by_name.get(r["reference_model"])
        if m is None:
            notes.append(f"no reference model named {r['reference_model']!r} ({bid}, {r['score']}): skipped")
            log["unmatched name"] += 1
            continue
        if m.get("id") in snap_cur and snap_cur[m["id"]] not in m["name"]:  # a snapshot model's reference score is the current snapshot's: its name must say so
            notes.append(f"{r['reference_model']}: has snapshots, its reference score is one snapshot's: skipped ({bid})")
            log["snapshot model"] += 1
            continue
        vendor = r["source_type"] in ("vendor", "official")
        groups[(m["name"], bid, vendor)].append(r)
    added = collections.Counter()
    for (name, bid, vendor), rr in groups.items():
        m = by_name[name]
        if bid in AVERAGE_DOMAINS:
            score = round(st.mean(x["score"] for x in rr), 2)
            variant = f"mean of {len(rr)} domains: " + "; ".join(x["variant"] for x in rr)[:240]
        else:
            if len(rr) > 1:
                notes.append(f"{name} / {bid}: {len(rr)} rows in one class, median used")
            score = round(st.median(x["score"] for x in rr), 2)
            variant = rr[0]["variant"]
        entry = {"score": score, "url": rr[0]["url"], "seen": rr[0]["seen"], "variant": variant[:300]}
        if vendor:
            slot = m.setdefault("vendor_scores", {})
            if bid in slot:
                log["already had (vendor)"] += 1
                continue
            slot[bid] = dict(entry, conf="medium", via="model_card")
            added[(bid, "vendor")] += 1
        else:
            if bid in m["scores"]:
                log["already had"] += 1
                continue
            m["scores"][bid] = dict(entry, src=rr[0]["source_type"])
            added[(bid, "independent")] += 1
    out = [f"rows read {len(rows)} · reference scores added {sum(added.values())} · skipped: {dict(log)}"]
    for (bid, cls), n in sorted(added.items()):
        out.append(f"  {bid:28} {cls:12} {n}")
    out += ["  " + n for n in notes]
    text = "\n".join(out)
    print(text)
    if a.report:
        Path(a.report).write_text(text + "\n")
    if not a.no_write:
        ref_path.write_text(json.dumps(ref, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
