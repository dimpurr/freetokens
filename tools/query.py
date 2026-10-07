#!/usr/bin/env python3
"""Stable read-only queries over data/*.json for other tools (stdlib only, JSON out).

    python3 tools/query.py score <model-id|name>      # AA index or EST band, with sources
    python3 tools/query.py lanes <model-id|lane-id|channel>   # status, checks, limits, volume
    python3 tools/query.py events [--since YYYY-MM-DD] [--lane ID]
    python3 tools/query.py pool [--min 30]            # agent-usable free lanes with a score, best first

Scores use build.estimate(), the same code the site uses.
CONTRACT (parsed by chco `oc-free status`; tell m1max-dimmodel before renaming or removing any of these):
  score -> kind, value, low, high, confidence · lanes -> status, ends.expected, ends.announced, ends.confidence · pool -> lane, score.*
New keys may be added freely.
"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build  # noqa: E402

MODELS = {m["id"]: m for m in build.load("models")}
LANES = build.load("lanes")
EVENTS = build.load("events")
CHANS = {c["name"]: c for c in build.load_optional("channels", [])}
EST, _ = build.estimate(list(MODELS.values()), build.load_optional("benchmarks", {}), build.load_optional("anchors", []))
CLAIMS = build.load_optional("benchmarks", {}).get("claims", [])


def find_model(q):
    ql = q.lower()
    return MODELS.get(q) or next((m for m in MODELS.values() if m["name"].lower() == ql), None) \
        or next((m for m in MODELS.values() if ql in m["id"] or ql in m["name"].lower()), None)


def score(m):
    a = m["aa_index"]
    if a.get("value") is not None:
        return {"model": m["id"], "name": m["name"], "kind": "aa", "value": a["value"], "low": a["value"], "high": a["value"],
                "source": a.get("url"), "date": a.get("date"), "confidence": "official"}
    e = EST.get(m["id"], {})
    if e.get("status") == "ok":
        n = e.get("benchmarks", 0)
        return {"model": m["id"], "name": m["name"], "kind": "est", "value": e["center"], "low": e["low"], "high": e["high"],
                "confidence": "medium" if n >= 2 else "low", "benchmarks": n,
                "evidence": [{k: c.get(k) for k in ("benchmark", "score", "source_type", "url", "variant")} for c in CLAIMS if c["model"] == m["id"]]}
    return {"model": m["id"], "name": m["name"], "kind": "none", "value": None, "note": a.get("note") or "no AA index and too little evidence for an estimate"}


def lane_view(l):
    a = l.get("access") or (CHANS.get(l["channel"]) or {}).get("access") or {}
    return {"lane": l["id"], "model": l["model"], "channel": l["channel"], "model_id": l["model_id"], "status": l["status"],
            "free": l["status"] in ("live", "listed", "overdue"), "checked": l["checked"], "tested": l.get("limits_observed"),
            "limits": l["limits_stated"], "volume": l.get("volume"), "ends": l["ends"], "started": l["started"],
            "access": {"form": a.get("form"), "rules": a.get("rules", [])},
            "agent_usable": l["status"] in ("live", "listed", "overdue") and a.get("form") in ("api", "own_cli") and "no_automation" not in a.get("rules", [])}


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__); return 0
    cmd, rest = argv[0], argv[1:]
    opt = lambda k, d=None: rest[rest.index(k) + 1] if k in rest else d
    if cmd == "score":
        m = find_model(" ".join(rest))
        out = score(m) if m else {"error": f"no model matches {' '.join(rest)!r}"}
    elif cmd == "lanes":
        q = " ".join(rest); m = find_model(q) if q else None
        ls = [l for l in LANES if l["id"] == q or l["channel"].lower() == q.lower() or (m and l["model"] == m["id"])]
        out = [lane_view(l) for l in ls]
    elif cmd == "events":
        since, lane = opt("--since", ""), opt("--lane")
        out = [e for e in sorted(EVENTS, key=lambda e: e["date"], reverse=True) if e["date"][:10] >= since and (not lane or lane in e["lanes"])]
    elif cmd == "pool":
        mn = float(opt("--min", 30))
        out = []
        for l in LANES:
            v = lane_view(l)
            if not v["agent_usable"]: continue
            s = score(MODELS[l["model"]])
            if s["value"] is not None and s["value"] >= mn:
                out.append({**{k: v[k] for k in ("lane", "channel", "model_id", "status", "tested", "volume")}, "score": s})
        out.sort(key=lambda x: -x["score"]["value"])
    else:
        print(__doc__); return 2
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
