"""Roční backtest strategie VA re-entry v replay enginu (tick po ticku).

Použití: python scripts/backtest_va.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from bot.data import load_day
from bot.engine import POINT_VALUE, Broker, run
from bot.strategy_va import Levels, VAReentry
from scripts.analyze_patterns import BARS, rth, value_area

OUT = Path(__file__).resolve().parent.parent / "outputs" / "va_trades.csv"
STOP_PTS = 25.0    # pevný stop v bodech (None = extrém dne)
MIN_TARGET = 15.0  # min. vzdálenost POC od vstupu v bodech


def main() -> None:
    bars = pd.read_parquet(BARS)
    bars["date"] = bars.index.date
    days = {d: g for d, g in bars.groupby("date") if len(rth(g)) > 300}
    dates = sorted(days)

    rows = []
    for i, (prev, cur) in enumerate(zip(dates, dates[1:]), 1):
        poc, vah, val = value_area(rth(days[prev]))
        ticks = load_day(str(cur)).tz_convert("America/New_York").between_time("09:30", "16:00")
        if ticks.empty:
            continue
        broker = Broker()
        run(ticks, VAReentry(Levels(poc, vah, val), stop_points=STOP_PTS,
                             min_target_points=MIN_TARGET), broker)
        for tr in broker.trades:
            net = tr.points * POINT_VALUE - 2 * broker.commission
            rows.append({"date": cur, "dir": tr.direction, "entry_ts": tr.entry_ts,
                         "exit_ts": tr.exit_ts, "entry": tr.entry_price,
                         "exit": tr.exit_price, "points": round(tr.points, 2),
                         "net_usd": round(net, 2)})
        if i % 50 == 0:
            print(f"{i}/{len(dates) - 1}", flush=True)

    tr = pd.DataFrame(rows)
    OUT.parent.mkdir(exist_ok=True)
    tr.to_csv(OUT, index=False)

    equity = tr["net_usd"].cumsum()
    dd = (equity.cummax() - equity).max()
    wins = (tr["net_usd"] > 0).mean()
    print(f"\n=== VA re-entry, rok dat, 1 kontrakt ===")
    print(f"Obchodů: {len(tr)} | Win rate: {wins:.1%}")
    print(f"Net PnL: ${tr['net_usd'].sum():,.0f} | Průměr/obchod: ${tr['net_usd'].mean():,.0f}")
    print(f"Nejlepší: ${tr['net_usd'].max():,.0f} | Nejhorší: ${tr['net_usd'].min():,.0f}")
    print(f"Max drawdown: ${dd:,.0f}")
    print(f"Long: {len(tr[tr['dir'] == 1])} | Short: {len(tr[tr['dir'] == -1])}")
    print(f"Detail: {OUT}")


if __name__ == "__main__":
    main()
