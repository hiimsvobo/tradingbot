"""Big-sweep counter-flow continuation — mřížka + walk-forward na MNQ.

Signál: >=K big sweepů stejné strany v pásmu W bodů během 5 min (cooldown
10 min), PROTI směru 15min trendu -> vstup po směru trendu na close 1min
baru. Stop za pásmem kumulace s odstupem OFF bodů, exit time-stop HOLD minut.
Exekuce MNQ: fixní risk $500/obchod (sizing), komise $0.85/strana/kontrakt,
skluz 2 ticky na vstup a stop-exit.

Walk-forward: výběr kombinace na 1. půlce roku, verdikt na 2. půlce.
Použití: python scripts/backtest_bigsweep.py
"""
import math
import sys
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

PV, COMM, SLIP = 2.0, 0.85, 0.5      # MNQ
RISK_USD, MAX_CON = 500, 30
T = pd.Timedelta("5min")
COOL = pd.Timedelta("10min")
KS = [3, 4]
WS = [5.0, 10.0]
HOLDS = [15, 30]
OFFS = [15.0, 20.0, 30.0]

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "bigsweep_wf.csv"


def collect_entries(sw: pd.DataFrame, m1: pd.DataFrame, k: int, w: float) -> list:
    entries = []
    for day, g in sw.groupby(sw.index.date):
        bars = m1[m1.index.date == day]
        if len(bars) < 100:
            continue
        c = bars["close"]
        for side, arr, d in [("A", 1, 1), ("B", -1, -1)]:
            s = g[g["side"] == side]
            last = None
            ts_arr, p_arr = s.index, s["price"].to_numpy()
            for i in range(len(s)):
                t0, p0 = ts_arr[i], p_arr[i]
                if last is not None and t0 - last < COOL:
                    continue
                m = (ts_arr >= t0 - T) & (ts_arr <= t0) & (np.abs(p_arr - p0) <= w)
                if m.sum() < k:
                    continue
                j = c.index.searchsorted(t0)
                jp = c.index.searchsorted(t0 - pd.Timedelta("15min"))
                if j >= len(c) or jp >= len(c):
                    continue
                if np.sign(c.iloc[j] - c.iloc[jp]) != arr:
                    continue
                last = t0
                entries.append((day, d, j, p_arr[m].min(), p_arr[m].max()))
    return entries


def main() -> None:
    sw = (pd.read_parquet(ROOT / "data" / "big_sweeps.parquet")
          .set_index("ts").sort_index().between_time("09:30", "15:00"))
    m1 = pd.read_parquet(ROOT / "data" / "bars_1min.parquet")

    rows = []
    for k, w in product(KS, WS):
        entries = collect_entries(sw, m1, k, w)
        for hold, off in product(HOLDS, OFFS):
            for day, d, j, band_lo, band_hi in entries:
                bars = m1[m1.index.date == day]
                c = bars["close"]
                entry = c.iloc[j] + d * SLIP
                stop = (band_lo - off) if d == 1 else (band_hi + off)
                risk = (entry - stop) * d
                if risk <= 0:
                    continue
                ncon = min(MAX_CON, math.floor(RISK_USD / (risk * PV)))
                if ncon < 1:
                    continue
                exit_p = None
                for jj in range(j + 1, min(j + hold + 1, len(bars))):
                    b = bars.iloc[jj]
                    if (b["low"] <= stop if d == 1 else b["high"] >= stop):
                        exit_p = stop - d * SLIP
                        break
                if exit_p is None:
                    exit_p = c.iloc[min(j + hold, len(c) - 1)] - d * SLIP
                rows.append({"k": k, "w": w, "hold": hold, "off": off,
                             "date": str(day), "dir": d,
                             "net": ((exit_p - entry) * d) * PV * ncon - 2 * COMM * ncon})
        print(f"mřížka K={k} W={w} hotová", flush=True)

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df.to_csv(OUT, index=False)
    split = df["date"].sort_values().iloc[len(df) // 2]
    keys = ["k", "w", "hold", "off"]
    print(f"\nsplit: {split.date()} | MNQ, fixní risk $500/obchod")
    print("K  W  hold off |   n   net$    avg$   WR    maxDD$    h1$      h2$")
    stats = {}
    for key, g in df.groupby(keys):
        s = g["net"]
        eq = s.cumsum()
        dd = (eq.cummax() - eq).max()
        h1 = g[g["date"] < split]["net"].sum()
        h2 = g[g["date"] >= split]["net"].sum()
        stats[key] = (h1, h2)
        print(f"{key[0]} {key[1]:4.0f} {key[2]:3d} {key[3]:4.0f} | {len(g):3d} {s.sum():8,.0f} "
              f"{s.mean():7,.1f} {(s > 0).mean():.1%} {dd:8,.0f} {h1:8,.0f} {h2:8,.0f}")

    best = max(stats, key=lambda x: stats[x][0])
    npos = sum(1 for v in stats.values() if v[1] > 0)
    print(f"\nWF: IS vybírá {dict(zip(keys, best))} (h1 ${stats[best][0]:,.0f})"
          f" -> OOS h2 ${stats[best][1]:,.0f}")
    print(f"OOS ziskových kombinací: {npos}/{len(stats)}")


if __name__ == "__main__":
    main()
