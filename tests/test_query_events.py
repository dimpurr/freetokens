"""Regression test: `query.py events` must not crash on events without a `lanes` field.

Offers-only events carry no `lanes` key. Filtering by --lane must skip them
instead of raising KeyError; unfiltered listing must still include them.

Run: python3 tests/test_query_events.py (stdlib only, exit 0 = pass).
"""
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import query


def run_events(*args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = query.main(["events", *args])
    assert rc == 0, f"events exited {rc}"
    return json.loads(buf.getvalue())


def main():
    assert any("lanes" not in e for e in query.EVENTS), "need an offers-only event for this test"
    n_all = len(run_events())
    assert n_all == len(query.EVENTS), "unfiltered listing must include lan present and lan-less events"
    out = run_events("--lane", "ling-3.1-flash-zen")
    assert all("ling-3.1-flash-zen" in e.get("lanes", []) for e in out), "lane filter hit an event without the lane"
    out = run_events("--lane", "no-such-lane-xyz")
    assert out == [], "unknown lane must yield empty list, not crash"
    print(f"ok: {n_all} events listed, lane filter skips lan-less events")


if __name__ == "__main__":
    main()
