"""IVB tick backtest — 3R target + posun SL na BE po dosažení 1R.

Po vstupu: jakmile cena poprvé dosáhne entry + 1R, stop se posune na
entry + BE_TICKS ticků (krytí nákladů). Target 3R beze změny.
Použití: python scripts/backtest_ivb_be.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from bot.data import DATA_DIR, load_day
from bot.engine import POINT_VALUE, Broker, run
from bot.strategy_ivb import IvbBreakout

OUT = Path(__file__).resolve().parent.parent / "outputs" / "ivb_be_trades.csv"
RISK_USD = 500.0
MNQ_PT = 2.0
COMM_MNQ = 0.74
TRIGGER_R = 1.0
BE_TICKS = 4  # BE + 1 bod (kryje komise + skluz stopu)


class IvbBreakeven(IvbBreakout):
    def __init__(self):
        super().__init__()
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
                and (tick.price - self._entry) * self._dir >= TRIGGER_R * self._risk):
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
        broker = Broker()
        strat = IvbBreakeven()
        run(ticks, strat, broker)
        for tr, risk in zip(broker.trades, strat.risks):
            n = max(1, int(RISK_USD // (risk * MNQ_PT)))
            rows.append({"date": d, "dir": tr.direction, "entry": tr.entry_price,
                         "exit": tr.exit_price, "points": round(tr.points, 2),
                         "risk_pts": round(risk, 2), "mnq": n,
                         "net_mnq500": round(tr.points * MNQ_PT * n - 2 * COMM_MNQ * n, 2),
                         "net_nq": round(tr.points * POINT_VALUE - 2 * broker.commission, 2)})
        if i % 50 == 0:
            print(f"{i}/{len(dates)}", flush=True)

    tr = pd.DataFrame(rows)
    tr.to_csv(OUT, index=False)
    p = tr["net_mnq500"]
    eq = p.cumsum()
    dd = (eq.cummax() - eq).max()
    eqnq = tr["net_nq"].cumsum()
    ddnq = (eqnq.cummax() - eqnq).max()
    half = tr["date"].iloc[len(tr) // 2]
    print(f"\n=== IVB 3R + BE({BE_TICKS} ticků) po {TRIGGER_R}R, 7/2025–7/2026 ===")
    print(f"Obchodů: {len(tr)} | WR: {(p > 0).mean():.1%}")
    print(f"$500riskMNQ: net ${p.sum():,.0f} | avg ${p.mean():,.1f} | maxDD ${dd:,.0f}")
    print(f"  H1: ${tr[tr['date'] < half]['net_mnq500'].sum():,.0f} | "
          f"H2: ${tr[tr['date'] >= half]['net_mnq500'].sum():,.0f} | "
          f"nejhorší ${p.min():,.0f} | nejlepší ${p.max():,.0f}")
    print(f"1xNQ: net ${tr['net_nq'].sum():,.0f} | maxDD ${ddnq:,.0f}")
    m = tr.assign(month=tr["date"].astype(str).str[:6]).groupby("month")["net_mnq500"]
    for mo, s in m:
        print(f"{mo[:4]}-{mo[4:]}: {s.sum():>8,.0f} $  ({len(s)} obch., {(s > 0).sum()} win)")
    print(f"Detail: {OUT}")


if __name__ == "__main__":
    main()
