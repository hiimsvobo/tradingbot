"""Celodenní (24h) tick-přesný backtest absorpční scalp strategie.

Na rozdíl od backtest_absorption_ticks.py se ticky nefiltrují na RTH:
strategie běží kontinuálně přes celé dny (asijská, evropská i US session),
stav (bary, setupy, pozice) se drží přes hranice denních souborů.
Flat okno 15:55–18:00 NY zůstává (time-stop před close, vstupy zase od reopen).
Reset stavu jen při změně front kontraktu (roll) — cenová mezera by
vyrobila falešný range bar; případná otevřená pozice se zavře.

Použití: python scripts/backtest_absorption_fullday.py
"""
import sys
from datetime import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from bot.data import DATA_DIR, load_day
from bot.engine import POINT_VALUE, Broker, Tick
from bot.strategy_absorption import AbsorptionScalp

OUT = Path(__file__).resolve().parent.parent / "outputs" / "absorption_fullday_trades.csv"

SESSIONS = [  # (název, od, do) v NY čase; asie se přes půlnoc řeší zvlášť
    ("asia", "18:00", "03:00"),
    ("europe", "03:00", "09:30"),
    ("ny_rth", "09:30", "16:00"),
    ("ny_close", "16:00", "17:00"),
]


def session_of(ts: pd.Timestamp) -> str:
    t = ts.time()
    hm = t.hour * 60 + t.minute
    if hm >= 18 * 60 or hm < 3 * 60:
        return "asia"
    if hm < 9 * 60 + 30:
        return "europe"
    if hm < 16 * 60:
        return "ny_rth"
    return "ny_close"


def main() -> None:
    dates = sorted(p.name.split("-")[2].split(".")[0] for p in DATA_DIR.glob("*.trades.csv"))
    def new_strat() -> AbsorptionScalp:
        s = AbsorptionScalp(contracts=1, resume_time=time(18, 0))
        s.broker = broker
        return s

    broker = Broker()
    strat = new_strat()
    prev_symbol = None
    last_tick = None
    trades_done = 0
    rows = []

    def collect() -> None:
        nonlocal trades_done
        for tr in broker.trades[trades_done:]:
            net = tr.points * POINT_VALUE - 2 * broker.commission
            ny = tr.entry_ts.tz_convert("America/New_York")
            rows.append({"date": ny.date().isoformat(), "session": session_of(ny),
                         "dir": tr.direction, "entry_ts": tr.entry_ts,
                         "exit_ts": tr.exit_ts, "entry": tr.entry_price,
                         "exit": tr.exit_price, "points": round(tr.points, 2),
                         "net_usd": round(net, 2)})
        trades_done = len(broker.trades)

    for i, d in enumerate(dates, 1):
        try:
            ticks = load_day(d).tz_convert("America/New_York")
        except Exception:
            continue
        if len(ticks) < 1000:
            continue
        symbol = str(ticks["symbol"].iloc[0])
        if prev_symbol is not None and symbol != prev_symbol:
            if last_tick is not None:
                broker.finish(last_tick)  # zavřít pozici před rollem
            strat = new_strat()
        prev_symbol = symbol
        for ts, price, size, side in zip(ticks.index, ticks["price"].to_numpy(),
                                         ticks["size"].to_numpy(), ticks["side"].to_numpy()):
            last_tick = Tick(ts, float(price), int(size), str(side))
            broker.process_tick(last_tick)
            strat.on_tick(last_tick)
        collect()
        if i % 25 == 0:
            print(f"{i}/{len(dates)}", flush=True)

    if last_tick is not None:
        broker.finish(last_tick)
    collect()

    tr = pd.DataFrame(rows)
    tr.to_csv(OUT, index=False)
    eq = tr["net_usd"].cumsum()
    dd = (eq.cummax() - eq).max()
    half = tr["date"].iloc[len(tr) // 2]
    print(f"\n=== Absorpce->agrese 24h, tick-přesně, 1 kontrakt (RRR 1:2, maxR 15) ===")
    print(f"Obchodů: {len(tr)} | WR: {(tr['net_usd'] > 0).mean():.1%}")
    print(f"Net: ${tr['net_usd'].sum():,.0f} | avg ${tr['net_usd'].mean():,.1f} | maxDD ${dd:,.0f}")
    print(f"1. půlka (do {half}): ${tr[tr['date'] < half]['net_usd'].sum():,.0f} | "
          f"2. půlka: ${tr[tr['date'] >= half]['net_usd'].sum():,.0f}")
    print("\n--- Po sessionech (NY čas vstupu) ---")
    for name, a, b in SESSIONS:
        s = tr[tr["session"] == name]
        if s.empty:
            print(f"{name:9s} ({a}-{b}): 0 obchodů")
            continue
        print(f"{name:9s} ({a}-{b}): {len(s):4d} obchodů | net ${s['net_usd'].sum():>8,.0f} | "
              f"avg ${s['net_usd'].mean():>6,.1f} | WR {(s['net_usd'] > 0).mean():.1%}")
    print(f"\nDetail: {OUT}")


if __name__ == "__main__":
    main()
