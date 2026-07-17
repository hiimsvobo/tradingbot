"""Extrakce big sweepů z ročních tick dat do jednoho parquetu.

Big sweep = souvislá plnění se stejným ts_event a stranou (agresor prorazil
více úrovní najednou), součet >= BIG kontraktů. Ukládá ts, stranu, velikost,
VWAP cenu sweepu a rozpětí cen (od-do).

Výstup: data/big_sweeps.parquet
Použití: python scripts/extract_big_sweeps.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from bot.data import DATA_DIR, load_day

BIG = 50
OUT = Path(__file__).resolve().parent.parent / "data" / "big_sweeps.parquet"


def main() -> None:
    dates = sorted(p.name.split("-")[2].split(".")[0] for p in DATA_DIR.glob("*.trades.csv"))
    frames = []
    for i, d in enumerate(dates, 1):
        try:
            t = load_day(d).tz_convert("America/New_York")
        except Exception:
            continue
        if len(t) < 1000:
            continue
        t = t[t["side"].isin(["B", "A"])].reset_index()
        grp = (t["ts_event"].ne(t["ts_event"].shift()) |
               t["side"].ne(t["side"].shift())).cumsum()
        agg = t.groupby(grp).agg(ts=("ts_event", "first"), side=("side", "first"),
                                 size=("size", "sum"),
                                 pv=("price", lambda s: 0.0),  # placeholder
                                 p_min=("price", "min"), p_max=("price", "max"))
        # VWAP sweepu
        t["pv"] = t["price"] * t["size"]
        agg["pv"] = t.groupby(grp)["pv"].sum() / agg["size"]
        agg = agg[agg["size"] >= BIG].rename(columns={"pv": "price"})
        frames.append(agg)
        if i % 25 == 0:
            print(f"{i}/{len(dates)}", flush=True)

    df = pd.concat(frames, ignore_index=True)
    df.to_parquet(OUT)
    print(f"\n{len(df):,} big sweepů -> {OUT}")


if __name__ == "__main__":
    main()
