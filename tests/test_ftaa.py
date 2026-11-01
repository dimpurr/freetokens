"""FTAA (ADR-035) invariants: the stored curve is well behaved, and every converted number in data/ follows it.

No network and no AA key: the v5 side is whatever `basis: direct` rows already hold.
Run: python3 tests/test_ftaa.py (stdlib only, exit 0 = pass).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import ftaa
import query

SCH = json.loads((ROOT / "schema/schema.json").read_text())["ftaa"]
CURVE = SCH["curve"]


def test_curve():
    xs = [i / 2 for i in range(0, 161)]  # 0 .. 80
    ys = [ftaa.curve_value(CURVE, x) for x in xs]
    assert ys[0] == 0 and min(ys) >= 0, "FTAA is never negative and 0 maps to 0"
    assert all(b >= a - 1e-9 for a, b in zip(ys, ys[1:])), "the curve never goes down"
    lo, hi = CURVE["domain"]
    for x in (lo, hi):  # continuous at both ends of the fitted range
        assert abs(ftaa.curve_value(CURVE, x - 1e-6) - ftaa.curve_value(CURVE, x + 1e-6)) < 1e-3
    assert ftaa.curve_value(CURVE, hi + 5) - ftaa.curve_value(CURVE, hi) == 5 * 1.0, "above the top scores carry over one-for-one"
    assert SCH["fit"]["loo_mean_abs_diff"] < 5, "stored leave-one-out error"


def test_fit_recovers_a_quadratic():
    pts = [(x, 2 + 0.5 * x + 0.01 * x * x) for x in range(5, 60, 3)]
    a, b, c = ftaa.polyfit2(pts)
    assert abs(a - 2) < 1e-6 and abs(b - 0.5) < 1e-6 and abs(c - 0.01) < 1e-8


def test_data_follows_the_curve():
    models = json.loads((ROOT / "data/models.json").read_text())
    n_map = 0
    for m in models:
        a = m["aa_index"]
        if a.get("value") is None:
            continue
        assert a["basis"] in ("direct", "mapped"), m["id"]
        assert 0 <= a["value"] <= 70, m["id"]
        if a["basis"] == "mapped":
            n_map += 1
            assert a["value"] == round(ftaa.curve_value(CURVE, a["prev_value"]), 1), f"{m['id']}: mapped value off the curve"
    assert n_map > 0
    for x in json.loads((ROOT / "data/anchors.json").read_text()):
        assert x["aa_basis"] in ("direct", "mapped"), x["name"]
        if x["aa_basis"] == "mapped":
            assert x["aa_index"] == round(ftaa.curve_value(CURVE, x["aa_prev"]), 1), f"{x['name']}: mapped anchor off the curve"
    for h in json.loads((ROOT / "data/est_history.json").read_text()):
        if not h.get("settled") and h.get("status") == "ok" and h.get("scale") == "ftaa":
            assert h["high"] - h["low"] == h["prev"]["high"] - h["prev"]["low"], "band width survives the conversion"


def test_query_score_carries_basis():
    for m in query.MODELS.values():
        s = query.score(m)
        assert "basis" in s, m["id"]
        if s["kind"] == "aa":
            assert s["basis"] == m["aa_index"]["basis"] and s["value"] == m["aa_index"]["value"]
        elif s["kind"] == "est":
            assert s["basis"] == "est"
    for k in ("kind", "value", "low", "high", "confidence"):  # contract fields read by chco `oc-free status`
        assert k in query.score(next(iter(query.MODELS.values())))


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    sys.exit(0)
