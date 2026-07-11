"""Walk-forward test VA re-entry: výběr parametrů na 1. polovině roku,
vyhodnocení na 2. polovině (out-of-sample).

Použití: python scripts/walkforward_va.py
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
from scripts.sensitivity_va import MIN_TARGETS, STOPS

OUT = Path(__file__).resolve().parent.parent / "outputs" / "va_walkforward.csv"


def stats(s: pd.Series) -> str:
    eq = s.cumsum()
    dd = (eq.cummax() - eq).max() if len(s) else 0
    wr = (s > 0).mean() if len(s) else 0
    return f"obchodů {len(s)}, net ${s.sum():,.0f}, avg ${s.mean():,.0f}, WR {wr:.1%}, maxDD ${dd:,.0f}"


def main() -> None:
    bars = pd.read_parquet(BARS)
    bars["date"] = bars.index.date
    days = {d: g for d, g in bars.groupby("date") if len(rth(g)) > 300}
    dates = sorted(days)
    combos = list(product(STOPS, MIN_TARGETS))

    rows = []
    for i, (prev, cur) in enumerate(zip(dates, dates[1:]), 1):
        poc, vah, val = value_area(rth(days[prev]))
        ticks = load_day(str(cur)).tz_convert("America/New_York").between_time("09:30", "16:00")
        if ticks.empty:
            continue
        for stop, mt in combos:
            broker = Broker()
            run(ticks, VAReentry(Levels(poc, vah, val), stop_points=stop,
                                 min_target_points=mt), broker)
            for t in broker.trades:
                rows.append({"date": cur, "stop": stop, "min_target": mt,
                             "net": t.points * POINT_VALUE - 2 * broker.commission})
        if i % 25 == 0:
            print(f"{i}/{len(dates) - 1}", flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(OUT, index=False)

    split = dates[len(dates) // 2]
    ins = df[df["date"] < split]
    oos = df[df["date"] >= split]
    print(f"\nSplit: in-sample do {split}, out-of-sample od {split}")

    rank = ins.groupby(["stop", "min_target"])["net"].sum().sort_values(ascending=False)
    best = rank.index[0]
    print(f"Nejlepší parametry na 1. pololetí: stop={best[0]}, min_target={best[1]} "
          f"(IS net ${rank.iloc[0]:,.0f})")

    sel_is = ins[(ins["stop"] == best[0]) & (ins["min_target"] == best[1])]["net"]
    sel_oos = oos[(oos["stop"] == best[0]) & (oos["min_target"] == best[1])]["net"]
    print(f"In-sample : {stats(sel_is)}")
    print(f"Out-of-sample: {stats(sel_oos)}")

    oos_all = oos.groupby(["stop", "min_target"])["net"].sum()
    print(f"\nOOS ziskových kombinací: {(oos_all > 0).sum()}/{len(oos_all)}")
    print(f"OOS percentil zvolené kombinace: {(oos_all < oos_all[best]).mean():.0%}")


if __name__ == "__main__":
    main()
