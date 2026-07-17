"""IVB tick backtest — mřížka triggeru posunu SL na BE (target 3R fixní).

Po dosažení entry + trigger*R se stop posune na entry + BE_TICKS ticků.
Triggery 0.5–2.5R po 0.5; baseline (bez BE) = 3R grid net $11 605.
Použití: python scripts/backtest_ivb_be_grid.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from bot.data import DATA_DIR, load_day
from bot.engine import POINT_VALUE, Broker, run
from bot.strategy_ivb import IvbBreakout

OUT = Path(__file__).resolve().parent.parent / "outputs" / "ivb_be_grid.csv"
TRIGGERS = [0.5, 1.0, 1.5, 2.0, 2.5]
RISK_USD = 500.0
MNQ_PT = 2.0
COMM_MNQ = 0.74
BE_TICKS = 4  # BE + 1 bod (kryje komise + skluz stopu)


class IvbBreakeven(IvbBreakout):
    def __init__(self, trigger_r: float):
        super().__init__()
        self.trigger_r = trigger_r
        self.risks: list[float] = []
        self._dir = 0
        self._entry = 0.0
        self._risk = 0.0
        self._target = 0.0
        self._moved = False

    def _on_bar_close(self, b) -> None:
        before = self.traded_day
        super()._on_bar_close(b)
        if self.traded_day != before:
            risk = abs(b.close - self.broker._stop)
            self.risks.append(risk)
            self._dir = 1 if b.close > self.ib_hi else -1
            self._entry = b.close  # engine plní na dalším ticku, aproximace triggeru
            self._risk = risk
            self._target = self.broker._target
            self._moved = False

    def on_tick(self, tick) -> None:
        super().on_tick(tick)
        if (not self._moved and self.broker.position != 0 and self._dir != 0
                and (tick.price - self._entry) * self._dir >= self.trigger_r * self._risk):
            be = self._entry + self._dir * BE_TICKS * 0.25
            self.broker.set_bracket(be, self._target)
            self._moved = True
        if self.broker.position == 0 and self._dir != 0 and not self.broker._has_pending:
            self._dir = 0


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
        for trg in TRIGGERS:
            broker = Broker()
            strat = IvbBreakeven(trg)
            run(ticks, strat, broker)
            for tr, risk in zip(broker.trades, strat.risks):
                n = max(1, int(RISK_USD // (risk * MNQ_PT)))
                rows.append({
                    "trigger": trg, "date": d, "points": tr.points,
                    "risk_pts": risk, "mnq": n,
                    "net_mnq500": tr.points * MNQ_PT * n - 2 * COMM_MNQ * n,
                    "net_nq": tr.points * POINT_VALUE - 2 * broker.commission,
                })
        if i % 50 == 0:
            print(f"{i}/{len(dates)}", flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(OUT, index=False)

    print(f"\n=== IVB 3R + BE({BE_TICKS} ticků) — mřížka triggeru, 7/2025–7/2026 ===")
    print("(baseline bez BE: net $11 605, maxDD $1 986, WR 57,8 %)")
    print(f"{'trigR':>5} {'obch':>5} {'WR':>6} | {'$500riskMNQ':>11} {'avg':>6} {'maxDD':>7} "
          f"{'H1':>7} {'H2':>7} | {'1xNQ net':>9} {'maxDD':>8}")
    for trg in TRIGGERS:
        g = df[df["trigger"] == trg].sort_values("date")
        half = g["date"].iloc[len(g) // 2]
        eq = g["net_mnq500"].cumsum()
        dd = (eq.cummax() - eq).max()
        eqnq = g["net_nq"].cumsum()
        ddnq = (eqnq.cummax() - eqnq).max()
        print(f"{trg:>5} {len(g):>5} {(g['net_mnq500'] > 0).mean():>6.1%} | "
              f"{g['net_mnq500'].sum():>11,.0f} {g['net_mnq500'].mean():>6,.0f} {dd:>7,.0f} "
              f"{g[g['date'] < half]['net_mnq500'].sum():>7,.0f} "
              f"{g[g['date'] >= half]['net_mnq500'].sum():>7,.0f} | "
              f"{g['net_nq'].sum():>9,.0f} {ddnq:>8,.0f}")
    print(f"Detail: {OUT}")


if __name__ == "__main__":
    main()
