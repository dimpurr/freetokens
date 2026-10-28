"""Regression test: meter/pool invariants (ADR-033).

- pooled lanes must carry pool.offer + pool.cap
- pool.cap must be complete: per in vocab 'per', amount a positive number, unit a non-empty vocab 'unit' value
- per_model lanes must not carry pool
- pool.offer must reference an existing offer

Run: python3 tests/test_meter_pool.py (stdlib only, exit 0 = pass). The test_meter_pool() wrapper at the
bottom lets a bare `pytest tests/` collect it instead of reporting zero tests.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
lanes = json.loads((ROOT / "data" / "lanes.json").read_text())
offers = {o["id"] for o in json.loads((ROOT / "data" / "offers.json").read_text())}
VOCAB = json.loads((ROOT / "schema" / "schema.json").read_text())["vocab"]


def main():
    n_pooled = n_per = 0
    for l in lanes:
        m = l.get("meter")
        if m == "pooled":
            n_pooled += 1
            pool = l.get("pool")
            assert isinstance(pool, dict), f"{l['id']}: pooled lane missing pool"
            assert pool.get("offer") in offers, f"{l['id']}: pool.offer {pool.get('offer')!r} unknown"
            cap = pool.get("cap")
            assert isinstance(cap, dict) and all(k in cap for k in ("amount", "unit", "per")), f"{l['id']}: pool.cap incomplete"
            assert cap.get("per") in VOCAB["per"], f"{l['id']}: pool.cap.per {cap.get('per')!r} is not in vocab per"
            amt = cap.get("amount")
            assert not isinstance(amt, bool) and isinstance(amt, (int, float)) and amt > 0, f"{l['id']}: pool.cap.amount {amt!r} is not a positive number"
            assert isinstance(cap.get("unit"), str) and cap["unit"].strip(), f"{l['id']}: pool.cap.unit is empty"
            assert cap["unit"] in VOCAB["unit"], f"{l['id']}: pool.cap.unit {cap['unit']!r} is not in vocab unit"
        elif m == "per_model":
            n_per += 1
            assert "pool" not in l, f"{l['id']}: per_model lane must not carry pool"
        else:
            raise AssertionError(f"{l['id']}: unknown meter {m!r}")
    print(f"ok: {n_pooled} pooled, {n_per} per_model; all pool.offer resolve")


def test_meter_pool():
    main()


if __name__ == "__main__":
    main()
