"""IVB (Initial-balance Volume Breakout, Fabio Valentini) — bar screening.

Definice (primární, dle uživatele): IB = 9:30-10:00 NY high/low. Po 10:00
vstup na close 5min baru, který zavře nad IB high (long) / pod IB low
(short) a splní delta filtr. Stop = protější strana IB, target = násobek
šířky IB od vstupu. Max 1 obchod/den, flat 15:00 ET.

Bar aproximace — jen na screening (rozhodnutí až tick verze + walk-forward).
Konzervativně: stop i target v témže 1min baru = ztráta.

Použití: python scripts/backtest_ivb.py
"""
import sys
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

POINT_VALUE = 20.0
COMMISSION = 2.25   # za stranu
SLIP = 0.25         # 1 tick: vstup market + stop exit
OUT = Path(__file__).resolve().parent.parent / "outputs" / "ivb_screen.csv"

IB_WINDOWS = {"930-1000": ("09:30", "10:00"), "830-900": ("08:30", "09:00")}
DELTA_THRS = [0, 100, 200, 400]
TP_MULTS = [1.0, 1.5, 2.0]
DIRECTIONS = ["long", "both"]
FLAT = "15:00"


def run_day(day: pd.DataFrame, ib_a: str, ib_b: str, thr: int,
            tp_mult: float, direction: str) -> dict | None:
    ib = day.between_time(ib_a, ib_b, inclusive="left")
    if len(ib) < 25:
        return None
    ib_hi, ib_lo = ib["high"].max(), ib["low"].min()
    width = ib_hi - ib_lo
    if width <= 0:
        return None

    after = day.between_time(ib_b, FLAT, inclusive="left")
    b5 = after.resample("5min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last",
         "delta": "sum"}).dropna()

    for ts, r in b5.iterrows():
        if r["close"] > ib_hi and (thr == 0 or r["delta"] >= thr):
            d = 1
        elif direction == "both" and r["close"] < ib_lo and (thr == 0 or r["delta"] <= -thr):
            d = -1
        else:
            continue
        entry = r["close"] + d * SLIP
        stop = ib_lo if d == 1 else ib_hi
        target = entry + d * tp_mult * width
        mgmt = after[after.index > ts + pd.Timedelta(minutes=4)]
        exit_price = mgmt["close"].iloc[-1] if len(mgmt) else r["close"]  # flat 15:00
        for _, m in mgmt.iterrows():
            hit_stop = m["low"] <= stop if d == 1 else m["high"] >= stop
            hit_tgt = m["high"] >= target if d == 1 else m["low"] <= target
            if hit_stop:                      # konzervativně: stop má přednost
                exit_price = stop - d * SLIP
                break
            if hit_tgt:
                exit_price = target
                break
        pts = (exit_price - entry) * d
        return {"dir": d, "entry_ts": ts, "points": pts,
                "net": pts * POINT_VALUE - 2 * COMMISSION}
    return None


def main() -> None:
    bars = pd.read_parquet(Path(__file__).resolve().parent.parent / "data" / "bars_1min.parquet")
    days = {d: g for d, g in bars.groupby(bars.index.date)}

    rows = []
    for ib_name, (a, b) in IB_WINDOWS.items():
        for thr, tp, dr in product(DELTA_THRS, TP_MULTS, DIRECTIONS):
            for d, g in days.items():
                res = run_day(g, a, b, thr, tp, dr)
                if res:
                    rows.append({"ib": ib_name, "thr": thr, "tp": tp, "dirmode": dr,
                                 "date": str(d), **res})
    df = pd.DataFrame(rows)
    df.to_csv(OUT, index=False)

    print("ib        thr  tp   směry |  n   net$    avg$   WR    maxDD$")
    for (ib, thr, tp, dr), g in df.groupby(["ib", "thr", "tp", "dirmode"]):
        eq = g["net"].cumsum()
        dd = (eq.cummax() - eq).max()
        print(f"{ib:9s} {thr:4d} {tp:.1f} {dr:5s} | {len(g):3d} {g['net'].sum():7,.0f} "
              f"{g['net'].mean():7,.1f} {(g['net'] > 0).mean():.1%} {dd:8,.0f}")
    print(f"\nDetail: {OUT}")


if __name__ == "__main__":
    main()
