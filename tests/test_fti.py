"""FT Intelligence (ADR-036) tests: scoring rules, claim merging, and that no AA number is in the public data.

Run: python3 tests/test_fti.py (stdlib only, exit 0 = pass). Needs no private files.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import ft_score
import ft_calibrate
import merge_claims

RULES = json.loads((ROOT / "schema/schema.json").read_text())["ft_rules"]
LINES = {  # FTI = score / 2 on every benchmark, reference range 0-80
    b: {"a": 0.0, "b": 0.5, "r": 0.9, "n": 20, "x": [0, 80], "ok": True} for b in ("b1", "b2", "b3", "b4")}
LINES["b1"]["vendor"] = {"a": -5.0, "b": 0.5, "r": 0.8, "n": 10, "x": [0, 80]}


def claim(b, score, st="leaderboard", **kw):
    return dict({"benchmark": b, "score": score, "source_type": st, "url": "https://example.org/" + b}, **kw)


def test_weighted_median():
    assert ft_score.weighted_median([(10, 1), (20, 1)]) == 15
    assert ft_score.weighted_median([(10, 1), (20, 1), (40, 5)]) == 40
    assert ft_score.weighted_median([(10, 1), (20, 1), (30, 1)]) == 20


def test_three_independent_sources_give_an_integer():
    e = ft_score.score_model([claim("b1", 60), claim("b2", 60), claim("b3", 60)], LINES, RULES)
    assert e["exact"] and e["evidence"] == 3 and e["low"] == e["high"] == e["center"] == 30.0


def test_two_sources_give_a_five_point_band():
    e = ft_score.score_model([claim("b1", 60), claim("b2", 60)], LINES, RULES)
    assert not e["exact"] and e["high"] - e["low"] == RULES["band_width"] and e["low"] <= 30 <= e["high"]


def test_vendor_only_is_never_exact_and_is_wider():
    e = ft_score.score_model([claim("b1", 60, "vendor"), claim("b2", 60, "vendor"), claim("b3", 60, "vendor")], LINES, RULES)
    assert not e["exact"] and e["independent"] == 0 and e["vendor_only"]
    assert e["high"] - e["low"] == RULES["band_width"]


def test_vendor_claim_uses_the_vendor_line():
    e = ft_score.score_model([claim("b1", 60, "vendor")], LINES, RULES)
    assert e["sources"][0]["implied"] == 25.0  # -5 + 0.5 * 60, not the independent line's 30


def test_aa_only_below_three_other_sources_and_without_a_number():
    aa = {"value": 40.0, "url": "https://artificialanalysis.ai/models/x"}
    e = ft_score.score_model([claim("b1", 60)], LINES, RULES, aa=aa)
    src = [s for s in e["sources"] if s["name"] == "Artificial Analysis"]
    assert len(src) == 1 and "value" not in src[0] and "implied" not in src[0] and e["evidence"] == 2
    e3 = ft_score.score_model([claim("b1", 60), claim("b2", 60), claim("b3", 60)], LINES, RULES, aa=aa)
    assert not [s for s in e3["sources"] if s["name"] == "Artificial Analysis"] and e3["evidence"] == 3
    only = ft_score.score_model([], LINES, RULES, aa=aa)
    assert only["status"] == "ok" and only["evidence"] == 1 and not only["exact"]


def test_disagreement_blocks_an_integer_and_pulls_in_aa():
    lines = dict(LINES, **{"b%d" % i: dict(LINES["b2"]) for i in range(5, 8)})
    cl = [claim("b2", 60), claim("b3", 60), claim("b4", 100)]  # implied 30, 30, 50: spread 20
    e = ft_score.score_model(cl, LINES, RULES)
    assert not e["exact"] and e["disagree"] and e["evidence"] == 3 and e["high"] - e["low"] == RULES["band_width"]
    aa = {"value": 31.0, "url": "https://artificialanalysis.ai/models/x"}
    e = ft_score.score_model(cl, LINES, RULES, aa=aa)
    assert e["evidence"] == 4 and any(s["name"] == "Artificial Analysis" for s in e["sources"]) and not e["exact"]
    close = ft_score.score_model([claim("b2", 60), claim("b3", 60), claim("b4", 70)], LINES, RULES, aa=aa)
    assert close["exact"] and close["evidence"] == 3  # spread 5: AA stays out


def test_published_numbers_are_integers():
    e = ft_score.score_model([claim("b2", 61), claim("b3", 63), claim("b4", 60)], LINES, RULES)
    assert all(isinstance(e[k], int) for k in ("center", "low", "high", "spread"))
    for x in json.loads((ROOT / "data/ft_scores.json").read_text())["scores"].values():
        if x["status"] == "ok":
            assert all(isinstance(x[k], int) for k in ("center", "low", "high")), x


SNAPS = [{"id": "a", "date": "2026-01-01"}, {"id": "b", "date": "2026-06-01"}]


def test_only_the_current_snapshot_is_scored():
    cl = [claim("b1", 60, snapshot="a"), claim("b2", 100, snapshot="b"), claim("b3", 100, snapshot="b"), claim("b4", 100, snapshot="b")]
    e = ft_score.score_model(cl, LINES, RULES, snapshots=SNAPS)
    assert e["center"] == 46 and e["snapshot"] == "b" and e["evidence"] == 3
    old = [s for s in e["sources"] if s["snapshot"] == "a"]
    assert old and not old[0]["used"] and old[0]["why"] == "older_snapshot"


def test_no_current_evidence_falls_back_to_a_band():
    e = ft_score.score_model([claim("b1", 60, snapshot="a"), claim("b2", 60, snapshot="a"), claim("b3", 60, snapshot="a")], LINES, RULES, snapshots=SNAPS)
    assert e["status"] == "ok" and e["stale_snapshot"] and not e["exact"] and e["high"] - e["low"] == RULES["band_width"]


def test_undated_rows_are_attributed_by_date_else_current():
    cl = [claim("b1", 60, date="2026-02-01"), claim("b2", 100, date="2026-07-01"), claim("b3", 100)]
    e = ft_score.score_model(cl, LINES, RULES, snapshots=SNAPS)
    assert e["evidence"] == 2 and e["unattributed"] == 1 and e["center"] == 46
    assert [s["why"] for s in e["sources"] if not s["used"]] == ["older_snapshot"]


def test_history_has_each_snapshots_own_score_and_ends_at_the_current_score():
    cl = [claim("b1", 60, snapshot="a"), claim("b2", 100, snapshot="b")]
    e = ft_score.score_model(cl, LINES, RULES, snapshots=SNAPS)
    assert [h["center"] for h in e["history"]] == [30, 46] and e["history"][-1]["center"] == e["center"]
    assert "history" not in ft_score.score_model(cl, LINES, RULES)


def test_modes_are_not_mixed():
    cl = [claim("b1", 60), claim("b1", 100, mode="max"), claim("b2", 60)]
    e = ft_score.score_model(cl, LINES, RULES)
    assert [s["why"] for s in e["sources"] if not s["used"]] == ["other_mode"] and e["center"] == 30
    only = ft_score.score_model([claim("b1", 100, mode="max"), claim("b1", 60, mode="low")], LINES, RULES)
    assert only["center"] == 46 and len([s for s in only["sources"] if not s["used"]]) == 1


def test_merge_checks_the_snapshot_id():
    row = {"model": "m1", "benchmark": "hle", "score": 5, "variant": "v", "source_type": "leaderboard", "url": "https://x.org/a", "seen": "2026-11-01"}
    assert merge_claims.check(dict(row, snapshot="a"), {"m1"}, {"m1": {"a", "b"}})[1] is None
    assert "not one of the snapshots" in merge_claims.check(dict(row, snapshot="zz"), {"m1"}, {"m1": {"a", "b"}})[1]


def test_a_narrow_reference_range_is_refused():
    pts = [(80 + i, 20 + i) for i in range(8)]  # r = 1, but the reference scores span 7 points (saturated)
    f = ft_calibrate.fit(pts, RULES)
    assert f["ok"] is False and "span" in f["why"]


def test_aliases_do_not_merge_versions_or_harnesses():
    c = ft_calibrate.canon
    assert c("terminal_bench_4") == "terminal_bench_4_0" and c("aime25") == "aime_2025" and c("claweval") == "claw_eval"
    assert c("terminal_bench_2_0") == "terminal_bench_2_0" and c("terminal_bench_2_1") == "terminal_bench_2_1"
    assert c("deep_swe", "DeepSWE v1.1 leaderboard") == "deepswe_v1_1" and c("deep_swe", "datacurve; percent") == "deep_swe"


def test_strict_benchmarks_do_not_cross_harnesses():
    lines = {"s": {"a": 0.0, "b": 0.5, "r": 0.9, "n": 20, "x": [0, 80], "ok": True, "strict": True}}
    e = ft_score.score_model([claim("s", 60, "vendor")], lines, RULES)
    assert e["status"] == "none" and e["sources"][0]["why"] == "harness"
    assert ft_score.score_model([claim("s", 60, "third_party")], lines, RULES)["center"] == 30
    lines["s"]["vendor"] = {"a": 5.0, "b": 0.5, "r": 0.8, "n": 9, "x": [0, 80]}
    assert ft_score.score_model([claim("s", 60, "vendor")], lines, RULES)["center"] == 35


def test_stored_spread_is_rounded_up_so_it_matches_disagree():
    lines = {b: dict(LINES["b2"]) for b in ("c1", "c2", "c3")}
    e = ft_score.score_model([claim("c1", 60), claim("c2", 60), claim("c3", 76.8)], lines, RULES)  # implied 30, 30, 38.4: spread 8.4
    assert e["spread"] == 9 and e["disagree"] and not e["exact"]
    e = ft_score.score_model([claim("c1", 60), claim("c2", 60), claim("c3", 75.6)], lines, RULES)  # spread 7.8
    assert e["spread"] == 8 and not e["disagree"] and e["exact"]


def test_a_band_never_starts_below_zero():
    e = ft_score.score_model([claim("b1", 2)], LINES, RULES)
    assert e["low"] == 0 and e["high"] == RULES["band_width"]


def test_all_clipped_sources_never_make_an_integer():
    lines = {b: {"a": -50.0, "b": 0.5, "r": 0.9, "n": 20, "x": [0, 80], "ok": True} for b in ("k1", "k2", "k3")}  # every implied value is below 0
    e = ft_score.score_model([claim("k1", 10), claim("k2", 10), claim("k3", 10)], lines, RULES)
    assert e["evidence"] == 3 and e["independent_non_aa"] == 3 and e["spread"] == 0
    assert not e["exact"] and e["clipped"] and (e["low"], e["high"]) == (0, RULES["band_width"])
    ok = ft_score.score_model([claim("b1", 60), claim("b2", 60), claim("b3", 60)], LINES, RULES)
    assert ok["exact"] and "clipped" not in ok


def test_artificial_analysis_alone_is_not_the_independent_source_for_an_integer():
    aa = {"value": 20.0, "url": "https://artificialanalysis.ai/models/x"}
    e = ft_score.score_model([claim("b1", 40, "vendor"), claim("b2", 42, "vendor")], LINES, RULES, aa=aa)
    assert e["evidence"] == 3 and e["independent"] == 1 and e["independent_non_aa"] == 0 and not e["exact"]
    assert e["high"] - e["low"] == RULES["band_width"]
    e = ft_score.score_model([claim("b1", 40, "vendor"), claim("b2", 42), claim("b3", 40, "vendor")], LINES, RULES, aa=aa)
    assert e["independent_non_aa"] == 1 and e["exact"]


def test_no_evidence_is_none():
    e = ft_score.score_model([claim("unfitted", 50)], LINES, RULES)
    assert e["status"] == "none" and e["evidence"] == 0 and e["sources"][0]["used"] is False


def test_epoch_benchmarks_count_once():
    lines = dict(LINES, epoch_x=LINES["b2"], epoch_y=LINES["b2"])
    e = ft_score.score_model([claim("epoch_x", 60, "third_party"), claim("epoch_y", 60, "third_party")], lines, RULES)
    assert e["evidence"] == 1


def test_reading_far_outside_the_reference_range_is_clamped():
    e = ft_score.score_model([claim("b2", 10000)], LINES, RULES)
    assert e["sources"][0]["implied"] <= 0.5 * (80 + RULES["extrapolate"] * 80) + 1e-6


def test_floor_effect_line_is_refused():
    pts = [(0, 20 + i) for i in range(8)] + [(5, 40), (9, 45)]
    assert ft_calibrate.fit(pts, RULES)["ok"] is False


def test_merge_rejects_and_normalises():
    ids = {"m1", "big-pickle"}
    ok = {"model": "m1", "benchmark": "gpqa", "score": 50, "variant": "GPQA Diamond, pass@1", "source_type": "official",
          "url": "https://huggingface.co/x/y", "seen": "2026-11-01"}
    n, why = merge_claims.check(ok, ids)
    assert why is None and n["benchmark"] == "gpqa_diamond" and n["source_type"] == "vendor"
    n, why = merge_claims.check(dict(ok, variant="GPQA"), ids)
    assert n["benchmark"] == "gpqa"
    for bad, text in ((dict(ok, url="https://benchlm.ai/x"), "benchlm"), (dict(ok, benchmark="jevbench"), "jevbench"),
                      (dict(ok, benchmark="aa_lcr"), "AA"), (dict(ok, model="big-pickle"), "identity"),
                      (dict(ok, url="https://artificialanalysis.ai/x"), "Artificial"), (dict(ok, model="nope"), "unknown model"),
                      (dict(ok, score="12"), "score"), (dict(ok, url="ftp://x"), "URL")):
        n, why = merge_claims.check(bad, ids)
        assert n is None and text.lower() in why.lower(), (bad, why)
    bench = {"claims": []}
    acc, rej, dup = merge_claims.merge([ok, ok], bench, ids)
    assert len(acc) == 1 and len(dup) == 1 and not rej


def test_public_data_has_no_aa_values():
    models = json.loads((ROOT / "data/models.json").read_text())
    assert not any("aa_index" in m for m in models)
    for name in ("benchmarks", "ft_scores", "ft_lines"):
        text = (ROOT / f"data/{name}.json").read_text()
        assert not re.search(r'"aa(_[a-z_]*)?"\s*:', text), name
        assert "artificialanalysis.ai/models" not in text.replace('"url": "https://artificialanalysis.ai/models/', ""), name
    scores = json.loads((ROOT / "data/ft_scores.json").read_text())["scores"]
    for mid, e in scores.items():
        for s in e["sources"]:
            if s["name"] == "Artificial Analysis":
                assert set(s) <= {"name", "benchmark", "url", "type", "used", "method"}, mid


def main():
    n = 0
    for k, f in sorted(globals().items()):
        if k.startswith("test_"):
            f()
            n += 1
            print("ok", k)
    print(f"ok: {n} tests")


if __name__ == "__main__":
    main()
