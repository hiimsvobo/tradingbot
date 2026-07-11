"""Hledání opakujících se orderflow paternů na ročních 1min barech.

Testované hypotézy (RTH = 9:30-16:00 NY):
H1  Value area rule: open mimo včerejší value area, návrat dovnitř -> dotažení na včerejší POC
H2  Opening drive: delta prvních 30 minut -> směr zbytku dne
H3  Big-trade delta: extrémní 15min big delta -> pokračování v dalších 30 minutách
H4  VWAP magnet: cena daleko od VWAP -> návrat k VWAP do konce dne
H5  Delta divergence: nové denní minimum s kladnou deltou (absorpce) -> odraz

Použití: python scripts/analyze_patterns.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

BARS = Path(__file__).resolve().parent.parent / "data" / "bars_1min.parquet"
RTH_START, RTH_END = "09:30", "16:00"


def rth(day: pd.DataFrame) -> pd.DataFrame:
    return day.between_time(RTH_START, RTH_END)


def value_area(day_rth: pd.DataFrame) -> tuple[float, float, float]:
    """POC/VAH/VAL z minutových barů (objem přiřazen close ceně, hladiny 1 bod)."""
    lvl = day_rth["close"].round()
    prof = day_rth.groupby(lvl)["volume"].sum().sort_index()
    poc = prof.idxmax()
    total, acc = prof.sum(), prof[poc]
    lo = hi = list(prof.index).index(poc)
    idx = list(prof.index)
    while acc < 0.7 * total and (lo > 0 or hi < len(idx) - 1):
        up = prof.iloc[hi + 1] if hi < len(idx) - 1 else -1
        dn = prof.iloc[lo - 1] if lo > 0 else -1
        if up >= dn:
            hi += 1; acc += up
        else:
            lo -= 1; acc += dn
    return float(poc), float(idx[hi]), float(idx[lo])


def fmt(p, n):
    return f"{p:5.1%} (n={n})"


def main() -> None:
    bars = pd.read_parquet(BARS)
    bars["date"] = bars.index.date
    days = {d: g for d, g in bars.groupby("date") if len(rth(g)) > 300}
    dates = sorted(days)
    print(f"Dní s plnou RTH seancí: {len(dates)}\n")

    # --- H1: value area rule ---
    hits = []
    for prev, cur in zip(dates, dates[1:]):
        prev_rth, cur_rth = rth(days[prev]), rth(days[cur])
        poc, vah, val = value_area(prev_rth)
        o = cur_rth["open"].iloc[0]
        if o > vah or o < val:  # open mimo včerejší VA
            first30 = cur_rth.between_time("09:30", "10:00")
            back_in = ((first30["close"] <= vah) & (first30["close"] >= val)).any()
            if back_in:
                rest = cur_rth.between_time("10:00", RTH_END)
                touched = ((rest["low"] <= poc) & (rest["high"] >= poc)).any()
                hits.append(touched)
    print(f"H1 Value area rule: open mimo VA + návrat do 10:00 -> dotek včerejšího POC: {fmt(np.mean(hits), len(hits))}")

    # --- H2: opening drive ---
    agree = []
    for d in dates:
        r = rth(days[d])
        d30 = r.between_time("09:30", "10:00")["delta"].sum()
        move = r["close"].iloc[-1] - r.between_time("10:00", "10:01")["open"].iloc[0]
        if abs(d30) > 2000:  # jen výrazný drive
            agree.append(np.sign(d30) == np.sign(move))
    print(f"H2 Opening drive: silná delta 9:30-10:00 (|d|>2000) -> stejný směr close: {fmt(np.mean(agree), len(agree))}")

    # --- H3: big-trade delta extrém -> pokračování ---
    cont = []
    for d in dates:
        r = rth(days[d])
        bd = r["big_delta"].rolling(15).sum()
        thr = bd.abs().quantile(0.95)
        sig = bd[(bd.abs() > thr) & (thr > 0)]
        sig = sig[~sig.index.duplicated()][::30]  # max 1 signál za 30 min
        for ts, v in sig.items():
            fut = r.loc[ts:]["close"]
            if len(fut) > 30:
                cont.append(np.sign(v) == np.sign(fut.iloc[30] - fut.iloc[0]))
    print(f"H3 Big-trade delta extrém (95. pct) -> stejný směr dalších 30 min: {fmt(np.mean(cont), len(cont))}")

    # --- H4: VWAP magnet ---
    reverts, dists = [], (10, 20, 30)
    res = {}
    for dist in dists:
        rv = []
        for d in dates:
            r = rth(days[d]).copy()
            vwap = r["pv"].cumsum() / r["volume"].cumsum()
            dev = r["close"] - vwap
            far = dev[abs(dev) > dist]
            if far.empty:
                continue
            ts = far.index[0]
            after = (r["close"] - vwap).loc[ts:]
            rv.append((np.sign(after) != np.sign(far.iloc[0])).any() or (after.abs() < 1).any())
        res[dist] = (np.mean(rv), len(rv))
    print("H4 VWAP magnet: po vzdálení >X bodů návrat k VWAP do konce dne:")
    for dist, (p, n) in res.items():
        print(f"     X={dist}: {fmt(p, n)}")

    # --- H5: absorpce na denním minimu ---
    bounce = []
    for d in dates:
        r = rth(days[d])
        run_min = r["low"].cummin()
        for i in range(30, len(r) - 30):
            row = r.iloc[i]
            if row["low"] <= run_min.iloc[i - 1] and row["delta"] > 0 and row["volume"] > r["volume"].quantile(0.8):
                fut = r["close"].iloc[i + 1:i + 31]
                bounce.append(fut.iloc[-1] > row["close"])
                break  # max 1 událost denně
    print(f"H5 Absorpce: nové denní low + kladná delta + vysoký objem -> výš za 30 min: {fmt(np.mean(bounce), len(bounce))}")


if __name__ == "__main__":
    main()
