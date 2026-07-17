"""IVB tick backtest s fixním riskem $500 na MNQ (dynamický počet mikr).

Počet mikr = floor(500 / (risk_b * $2)), min 1. Komise $0.74/strana/kontrakt.
Použití: python scripts/backtest_ivb_ticks_mnq500.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from bot.data import DATA_DIR, load_day
from bot.engine import Broker, run
from bot.strategy_ivb import IvbBreakout

OUT = Path(__file__).resolve().parent.parent / "outputs" / "ivb_ticks_mnq500_trades.csv"
RISK_USD = 500.0
MNQ_PT = 2.0
COMM = 0.74  # za kontrakt a stranu


class IvbLogRisk(IvbBreakout):
    """Zaloguje risk (b) každého vstupu — pro sizing po běhu."""

    def __init__(self):
        super().__init__()
        self.risks: list[float] = []

    def _on_bar_close(self, b) -> None:
        before = self.traded_day
        super()._on_bar_close(b)
        if self.traded_day != before:  # vstoupili jsme
            self.risks.append(abs(b.close - self.broker._stop))


def main() -> None:
    dates = sorted(p.name.split("-")[2].split(".")[0] for p in DATA_DIR.glob("*.trades.csv"))
    rows = []
    for i, d in enumerate(dates, 1):
        try:
            ticks = load_day(d).tz_convert("America/New_York").between_time("09:30", "15:05")
        except Exception:
            continue
        if len(ticks) < 1000:
            continue
        broker = Broker()
        strat = IvbLogRisk()
        run(ticks, strat, broker)
        assert len(broker.trades) == len(strat.risks)
        for tr, risk in zip(broker.trades, strat.risks):
            n = max(1, int(RISK_USD // (risk * MNQ_PT)))
            net = tr.points * MNQ_PT * n - 2 * COMM * n
            rows.append({"date": d, "dir": tr.direction, "entry_ts": tr.entry_ts,
                         "exit_ts": tr.exit_ts, "entry": tr.entry_price,
                         "exit": tr.exit_price, "points": round(tr.points, 2),
                         "risk_pts": round(risk, 2), "mnq": n,
                         "net_usd": round(net, 2)})
        if i % 50 == 0:
            print(f"{i}/{len(dates)}", flush=True)

    tr = pd.DataFrame(rows)
    tr.to_csv(OUT, index=False)
    eq = tr["net_usd"].cumsum()
    dd = (eq.cummax() - eq).max()
    print(f"\n=== IVB (minRisk 60, TP 3R), fixní risk $500 na MNQ ===")
    print(f"Obchodů: {len(tr)} | WR: {(tr['net_usd'] > 0).mean():.1%} | "
          f"mikra min/med/max: {tr['mnq'].min()}/{int(tr['mnq'].median())}/{tr['mnq'].max()}")
    print(f"Net: ${tr['net_usd'].sum():,.0f} | avg ${tr['net_usd'].mean():,.1f} | maxDD ${dd:,.0f}")
    print(f"Nejhorší obchod: ${tr['net_usd'].min():,.0f} | nejlepší: ${tr['net_usd'].max():,.0f}")
    m = tr.assign(month=tr["date"].astype(str).str[:6]).groupby("month")["net_usd"]
    for mo, s in m:
        print(f"{mo[:4]}-{mo[4:]}: {s.sum():>8,.0f} $  ({len(s)} obch., {(s > 0).sum()} win)")
    print(f"Detail: {OUT}")


if __name__ == "__main__":
    main()
