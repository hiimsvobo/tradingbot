"""Dealing range (ICT) — screening na 5min strukturách, 1min řízení, MNQ.

Range = poslední potvrzený swing high x swing low (fraktál K barů z každé
strany na 5min, potvrzení kauzálně až K barů po extrému). Setup "sweep &
reclaim": knot 5min svíčky propíchne extrém range, close zpět uvnitř ->
vstup na close k equilibriu (50 %) nebo protější straně; stop za sweep
extrém + buffer. RTH 9:30-15:00, flat 15:00, max 2 obchody/den.
Sizing: fixní risk $500 na MNQ (komise $0.85/strana, skluz 2 ticky).

Použití: python scripts/backtest_dealing_range.py
"""
import math
import sys
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

PV, COMM, SLIP = 2.0, 0.85, 0.5
RISK_USD, MAX_CON = 500, 30
MIN_RANGE = 40.0          # min šířka range v bodech
KS = [3, 5]
BUFFERS = [5.0, 10.0]
TARGETS = ["eq", "opposite"]
MAX_TRADES_DAY = 2

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "dealing_range_screen.csv"


def swings(f: pd.DataFrame, k: int):
    """Kauzální fraktály: (index_potvrzení, typ, cena). Potvrzení k barů po extrému."""
    hi, lo = f["high"].to_numpy(), f["low"].to_numpy()
    out = []
    for i in range(k, len(f) - k):
        if hi[i] == max(hi[i - k:i + k + 1]):
            out.append((i + k, "H", hi[i]))
        if lo[i] == min(lo[i - k:i + k + 1]):
            out.append((i + k, "L", lo[i]))
    return sorted(out)


def main() -> None:
    f5 = pd.read_parquet(ROOT / "data" / "bars_5min_ivb.parquet")  # 5min bary 9:30-15:00
    m1 = pd.read_parquet(ROOT / "data" / "bars_1min.parquet")

    rows = []
    for k, buf, tgt in product(KS, BUFFERS, TARGETS):
        for day, f in f5.groupby(f5.index.date):
            if len(f) < 2 * k + 5:
                continue
            m1d = m1[m1.index.date == day].between_time("09:30", "15:00", inclusive="left")
            sw = swings(f, k)
            si = 0
            rng_hi = rng_lo = None
            trades_today = 0
            pos_until = -1
            for i in range(len(f)):
                while si < len(sw) and sw[si][0] <= i:
                    _, typ, price = sw[si]
                    if typ == "H":
                        rng_hi = price
                    else:
                        rng_lo = price
                    si += 1
                if trades_today >= MAX_TRADES_DAY or i <= pos_until:
                    continue
                if rng_hi is None or rng_lo is None or rng_hi - rng_lo < MIN_RANGE:
                    continue
                b = f.iloc[i]
                eq = (rng_hi + rng_lo) / 2
                d = 0
                if b["low"] < rng_lo and b["close"] > rng_lo and b["close"] < eq:
                    d, sweep_ext = 1, b["low"]
                elif b["high"] > rng_hi and b["close"] < rng_hi and b["close"] > eq:
                    d, sweep_ext = -1, b["high"]
                if d == 0:
                    continue
                entry = b["close"] + d * SLIP
                stop = sweep_ext - d * buf
                risk = (entry - stop) * d
                if risk <= 0:
                    continue
                ncon = min(MAX_CON, math.floor(RISK_USD / (risk * PV)))
                if ncon < 1:
                    continue
                target = eq if tgt == "eq" else (rng_hi if d == 1 else rng_lo)
                if (target - entry) * d <= 0:
                    continue
                # řízení na 1min barech od dalšího 5min baru
                t_entry = f.index[i]
                mgmt = m1d[m1d.index > t_entry + pd.Timedelta(minutes=4)]
                exit_p = mgmt["close"].iloc[-1] - d * SLIP if len(mgmt) else entry
                exit_i = len(f) - 1
                for mts, m in mgmt.iterrows():
                    if (m["low"] <= stop if d == 1 else m["high"] >= stop):
                        exit_p = stop - d * SLIP
                        exit_i = f.index.searchsorted(mts)
                        break
                    if (m["high"] >= target if d == 1 else m["low"] <= target):
                        exit_p = target
                        exit_i = f.index.searchsorted(mts)
                        break
                trades_today += 1
                pos_until = exit_i
                rows.append({"k": k, "buf": buf, "tgt": tgt, "date": str(day), "dir": d,
                             "risk": risk, "ncon": ncon,
                             "net": ((exit_p - entry) * d) * PV * ncon - 2 * COMM * ncon})

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df.to_csv(OUT, index=False)
    split = df["date"].sort_values().iloc[len(df) // 2]
    print(f"split: {split.date()} | MNQ, fixní risk $500")
    print("k buf tgt      |   n   net$    avg$   WR    maxDD$    h1$     h2$")
    stats = {}
    for key, g in df.groupby(["k", "buf", "tgt"]):
        s = g["net"]
        eq_ = s.cumsum()
        dd = (eq_.cummax() - eq_).max()
        h1 = g[g["date"] < split]["net"].sum()
        h2 = g[g["date"] >= split]["net"].sum()
        stats[key] = (h1, h2)
        print(f"{key[0]} {key[1]:3.0f} {key[2]:8s} | {len(g):3d} {s.sum():8,.0f} {s.mean():7,.1f} "
              f"{(s > 0).mean():.1%} {dd:8,.0f} {h1:7,.0f} {h2:7,.0f}")
    best = max(stats, key=lambda x: stats[x][0])
    print(f"\nWF: IS vybírá {best} (h1 ${stats[best][0]:,.0f}) -> OOS h2 ${stats[best][1]:,.0f}")
    print(f"OOS ziskových: {sum(1 for v in stats.values() if v[1] > 0)}/{len(stats)}")


if __name__ == "__main__":
    main()
