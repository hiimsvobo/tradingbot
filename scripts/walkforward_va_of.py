"""Walk-forward test VA re-entry s orderflow potvrzením vstupu.

Varianty filtru: none (baseline), delta (delta všech obchodů v okně),
big (delta jen obchodů >= 20 kontraktů). Vstup jen když delta ve směru
obchodu >= práh; jinak se čeká na další tick do deadline 10:00.

Výběr kombinace (stop, min_target, filtr, práh) na 1. polovině roku,
vyhodnocení na 2. polovině. Navíc přímé OOS srovnání filtrů při fixních
parametrech ceny (stop 25 / min target 15).

Použití: python scripts/walkforward_va_of.py
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

OUT = Path(__file__).resolve().parent.parent / "outputs" / "va_of_walkforward.csv"

STOPS = [20, 25, 30]
MIN_TARGETS = [10, 15, 20]
# (of_mode, of_min_delta); okno 120 s
FILTERS = [(None, 0), ("delta", 0), ("delta", 200), ("delta", 500),
           ("big", 0), ("big", 100)]
WINDOW_S = 120.0


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
    combos = list(product(STOPS, MIN_TARGETS, FILTERS))

    rows = []
    for i, (prev, cur) in enumerate(zip(dates, dates[1:]), 1):
        poc, vah, val = value_area(rth(days[prev]))
        ticks = load_day(str(cur)).tz_convert("America/New_York").between_time("09:30", "16:00")
        if ticks.empty:
            continue
        for stop, mt, (mode, mind) in combos:
            broker = Broker()
            run(ticks, VAReentry(Levels(poc, vah, val), stop_points=stop,
                                 min_target_points=mt, of_mode=mode,
                                 of_window_s=WINDOW_S, of_min_delta=mind), broker)
            for t in broker.trades:
                rows.append({"date": cur, "stop": stop, "min_target": mt,
                             "of": f"{mode or 'none'}/{mind}",
                             "net": t.points * POINT_VALUE - 2 * broker.commission})
        if i % 25 == 0:
            print(f"{i}/{len(dates) - 1}", flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(OUT, index=False)

    split = dates[len(dates) // 2]
    ins = df[df["date"] < split]
    oos = df[df["date"] >= split]
    print(f"\nSplit: in-sample do {split}, out-of-sample od {split}")

    keys = ["stop", "min_target", "of"]
    rank = ins.groupby(keys)["net"].sum().sort_values(ascending=False)
    best = rank.index[0]
    print(f"Nejlepší kombinace na 1. pololetí: stop={best[0]}, min_target={best[1]}, "
          f"filtr={best[2]} (IS net ${rank.iloc[0]:,.0f})")
    sel = dict(zip(keys, best))
    m_is = (ins[keys] == pd.Series(sel)).all(axis=1)
    m_oos = (oos[keys] == pd.Series(sel)).all(axis=1)
    print(f"In-sample    : {stats(ins[m_is]['net'])}")
    print(f"Out-of-sample: {stats(oos[m_oos]['net'])}")

    print("\n=== OOS srovnání filtrů při stop 25 / min target 15 ===")
    base = oos[(oos["stop"] == 25) & (oos["min_target"] == 15)]
    for of, g in base.groupby("of"):
        print(f"{of:>10}: {stats(g['net'])}")

    print("\n=== OOS: všechny filtry agregované přes celou mřížku ===")
    for of, g in oos.groupby("of"):
        by_combo = g.groupby(["stop", "min_target"])["net"].sum()
        print(f"{of:>10}: součet ${g['net'].sum():,.0f}, "
              f"ziskových kombinací {(by_combo > 0).sum()}/{len(by_combo)}")


if __name__ == "__main__":
    main()
