"""Roční tick-přesný backtest big-sweep counter-flow strategie (MNQ sizing).

Použití: python scripts/backtest_bigsweep_ticks.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from bot.data import DATA_DIR, load_day
from bot.engine import Broker, run
from bot.strategy_bigsweep import BigSweepFlow

OUT = Path(__file__).resolve().parent.parent / "outputs" / "bigsweep_ticks_trades.csv"
PV = 2.0   # MNQ


def main() -> None:
    dates = sorted(p.name.split("-")[2].split(".")[0] for p in DATA_DIR.glob("*.trades.csv"))
    rows = []
    for i, d in enumerate(dates, 1):
        try:
            ticks = load_day(d).tz_convert("America/New_York").between_time("09:30", "13:00")
        except Exception:
            continue
        if len(ticks) < 1000:
            continue
        broker = Broker(slippage_ticks=2.0, commission_usd=0.85)
        run(ticks, BigSweepFlow(), broker)
        for tr in broker.trades:
            net = tr.points * tr.size * PV - 2 * broker.commission * tr.size
            rows.append({"date": d, "dir": tr.direction, "size": tr.size,
                         "entry_ts": tr.entry_ts, "exit_ts": tr.exit_ts,
                         "entry": tr.entry_price, "exit": tr.exit_price,
                         "net_usd": round(net, 2)})
        if i % 25 == 0:
            print(f"{i}/{len(dates)}", flush=True)

    tr = pd.DataFrame(rows)
    tr.to_csv(OUT, index=False)
    eq = tr["net_usd"].cumsum()
    dd = (eq.cummax() - eq).max()
    half = tr["date"].iloc[len(tr) // 2]
    print(f"\n=== Big-sweep counter-flow, tick-přesně, MNQ risk $500 ===")
    print(f"Obchodů: {len(tr)} | WR: {(tr['net_usd'] > 0).mean():.1%}")
    print(f"Net: ${tr['net_usd'].sum():,.0f} | avg ${tr['net_usd'].mean():,.1f} | maxDD ${dd:,.0f}")
    print(f"1. půlka (do {half}): ${tr[tr['date'] < half]['net_usd'].sum():,.0f} | "
          f"2. půlka: ${tr[tr['date'] >= half]['net_usd'].sum():,.0f}")
    print(f"Detail: {OUT}")


if __name__ == "__main__":
    main()
