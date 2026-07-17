"""IVB tick backtest — bez targetu (exit jen stop / flat 15:00) + RRR 6 a 8.

Navazuje na RRR grid: WR od 2,5R konstantní -> vítěze uzavírá time-stop.
Otázka: kolik nechává 3R target na stole? Použití:
python scripts/backtest_ivb_notp.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from bot.data import DATA_DIR, load_day
from bot.engine import POINT_VALUE, Broker, run
from bot.strategy_ivb import IvbBreakout

OUT = Path(__file__).resolve().parent.parent / "outputs" / "ivb_notp_trades.csv"
RRRS = [6.0, 8.0, 1000.0]  # 1000 = fakticky bez targetu
RISK_USD = 500.0
MNQ_PT = 2.0
COMM_MNQ = 0.74


class IvbLogRisk(IvbBreakout):
    def __init__(self, rrr: float):
        super().__init__(rrr=rrr)
        self.risks: list[float] = []

    def _on_bar_close(self, b) -> None:
        before = self.traded_day
        super()._on_bar_close(b)
        if self.traded_day != before:
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
        for rrr in RRRS:
            broker = Broker()
            strat = IvbLogRisk(rrr)
            run(ticks, strat, broker)
            for tr, risk in zip(broker.trades, strat.risks):
                n = max(1, int(RISK_USD // (risk * MNQ_PT)))
                rows.append({
                    "rrr": rrr, "date": d, "points": tr.points, "risk_pts": risk,
                    "mnq": n,
                    "net_mnq500": tr.points * MNQ_PT * n - 2 * COMM_MNQ * n,
                    "net_nq": tr.points * POINT_VALUE - 2 * broker.commission,
                })
        if i % 50 == 0:
            print(f"{i}/{len(dates)}", flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(OUT, index=False)

    print(f"\n=== IVB bez targetu / extrémní RRR (minRisk 60), 7/2025–7/2026 ===")
    print(f"{'RRR':>6} {'obch':>5} {'WR':>6} | {'$500riskMNQ':>11} {'avg':>6} {'maxDD':>7} "
          f"{'H1':>7} {'H2':>7} | {'1xNQ net':>9} {'maxDD':>8}")
    for rrr in RRRS:
        g = df[df["rrr"] == rrr].sort_values("date")
        half = g["date"].iloc[len(g) // 2]
        eq = g["net_mnq500"].cumsum()
        dd = (eq.cummax() - eq).max()
        eqnq = g["net_nq"].cumsum()
        ddnq = (eqnq.cummax() - eqnq).max()
        lab = "noTP" if rrr >= 999 else f"{rrr:g}"
        print(f"{lab:>6} {len(g):>5} {(g['net_mnq500'] > 0).mean():>6.1%} | "
              f"{g['net_mnq500'].sum():>11,.0f} {g['net_mnq500'].mean():>6,.0f} {dd:>7,.0f} "
              f"{g[g['date'] < half]['net_mnq500'].sum():>7,.0f} "
              f"{g[g['date'] >= half]['net_mnq500'].sum():>7,.0f} | "
              f"{g['net_nq'].sum():>9,.0f} {ddnq:>8,.0f}")
    print(f"Detail: {OUT}")


if __name__ == "__main__":
    main()
