"""Test citlivosti parametrů VA re-entry: mřížka stop x min_target na celém roce.

Ticky každého dne se načtou jednou a přehrají všem kombinacím.

Použití: python scripts/sensitivity_va.py
"""
import sys
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from bot.data import load_day
from bot.engine import POINT_VALUE, Broker, run
from bot.strategy_va import Levels, VAReentry
from scripts.analyze_patterns import BARS, rth, value_area

STOPS = [15, 20, 25, 30, 35, 40]
MIN_TARGETS = [5, 10, 15, 20, 25]
OUT = Path(__file__).resolve().parent.parent / "outputs" / "va_sensitivity.csv"


def main() -> None:
    bars = pd.read_parquet(BARS)
    bars["date"] = bars.index.date
    days = {d: g for d, g in bars.groupby("date") if len(rth(g)) > 300}
    dates = sorted(days)
    combos = list(product(STOPS, MIN_TARGETS))
    pnl = {c: [] for c in combos}

    for i, (prev, cur) in enumerate(zip(dates, dates[1:]), 1):
        poc, vah, val = value_area(rth(days[prev]))
        ticks = load_day(str(cur)).tz_convert("America/New_York").between_time("09:30", "16:00")
        if ticks.empty:
            continue
        for stop, mt in combos:
            broker = Broker()
            run(ticks, VAReentry(Levels(poc, vah, val), stop_points=stop,
                                 min_target_points=mt), broker)
            pnl[(stop, mt)].extend(
                t.points * POINT_VALUE - 2 * broker.commission for t in broker.trades)
        if i % 25 == 0:
            print(f"{i}/{len(dates) - 1}", flush=True)

    rows = []
    for (stop, mt), p in pnl.items():
        s = pd.Series(p)
        eq = s.cumsum()
        rows.append({"stop": stop, "min_target": mt, "trades": len(s),
                     "net_usd": round(s.sum()), "avg_usd": round(s.mean()) if len(s) else 0,
                     "win_rate": round((s > 0).mean(), 3) if len(s) else None,
                     "max_dd": round((eq.cummax() - eq).max()) if len(s) else 0})
    res = pd.DataFrame(rows).sort_values("net_usd", ascending=False)
    res.to_csv(OUT, index=False)
    print("\nPivot net PnL (řádky=stop, sloupce=min_target):")
    print(res.pivot(index="stop", columns="min_target", values="net_usd"))
    print(f"\nZiskových kombinací: {(res['net_usd'] > 0).sum()}/{len(res)}")
    print(f"Detail: {OUT}")


if __name__ == "__main__":
    main()
