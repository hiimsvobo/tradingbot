"""IVB v2 — screening tří vstupních modelů (A akceptace, B re-breakout po
absorpci, C rejection/reverz) na 5min orderflow barech.

Signály z data/bars_5min_ivb.parquet (big sweepy ve wick zónách), řízení
pozice na 1min barech (konzervativně: stop v baru má přednost). IB =
9:30-10:00, signály od 10:00, max 1 obchod/den, flat 15:00.

Použití: python scripts/backtest_ivb_models.py
"""
import sys
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

POINT_VALUE, COMMISSION, SLIP, TICK = 20.0, 2.25, 0.25, 0.25
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "ivb_models_screen.csv"

ABSORB_THRS = [100, 200]       # big objem ve wicku (proti/za)
MAX_RISKS = [10, 20, 1000]     # cap risku v bodech (1000 = bez capu)
TPS = ["rrr2", "width1"]       # 2R ze skutečného risku / 1x šířka IB
SLS_A = ["bar", "zone"]        # extrém signální svíčky / hrana zóny


def manage(m1: pd.DataFrame, entry_ts, d: int, entry: float, stop: float,
           target: float) -> float:
    mgmt = m1[m1.index > entry_ts]
    exit_price = mgmt["close"].iloc[-1] if len(mgmt) else entry
    for _, m in mgmt.iterrows():
        if (m["low"] <= stop if d == 1 else m["high"] >= stop):
            return stop - d * SLIP
        if (m["high"] >= target if d == 1 else m["low"] <= target):
            return target
    return exit_price


def signals_A(f: pd.DataFrame, ib_hi, ib_lo, thr):
    """Akceptace: close za zónou, objem, delta ve směru, malý wick, bez absorpce."""
    vol_avg = f["volume"].rolling(6).mean().shift(1)
    for i in range(6, len(f)):
        b, va = f.iloc[i], vol_avg.iloc[i]
        rng = b["high"] - b["low"]
        if rng <= 0 or pd.isna(va):
            continue
        if (b["close"] > ib_hi and b["delta"] > 0 and b["volume"] >= 1.2 * va
                and (b["high"] - b["close"]) <= 0.25 * rng
                and b["big_sell_hi"] < thr):
            yield f.index[i], 1, b
        if (b["close"] < ib_lo and b["delta"] < 0 and b["volume"] >= 1.2 * va
                and (b["close"] - b["low"]) <= 0.25 * rng
                and b["big_buy_lo"] < thr):
            yield f.index[i], -1, b


def signals_B(f: pd.DataFrame, ib_hi, ib_lo, thr):
    """Zaplutí zpět do zóny -> absorpce (big ve wicku, delta proti) -> agrese
    -> vstup na close baru, který znovu zavře za zónou. SL za absorpční bar."""
    for d, edge in ((1, ib_hi), (-1, ib_lo)):
        phase, absorb = 0, None   # 0 čeká breakout, 1 čeká zaplutí, 2 čeká absorpci, 3 čeká agresi+re-break
        for i in range(6, len(f)):
            b = f.iloc[i]
            beyond = b["close"] > edge if d == 1 else b["close"] < edge
            if phase == 0 and beyond:
                phase = 1
            elif phase == 1 and not beyond:
                phase = 2
            elif phase == 2:
                big_w = b["big_sell_lo"] if d == 1 else b["big_buy_hi"]
                if big_w >= thr and b["delta"] * d <= 0:
                    absorb, phase = b, 3
            elif phase == 3:
                aggr = (b["delta"] * d >= 0.05 * max(b["volume"], 1)
                        and (b["close"] - b["open"]) * d > 0
                        and b["body_vol"] > 0.5 * max(b["volume"], 1))
                if beyond and aggr:
                    yield f.index[i], d, b, absorb
                    break
                broken = absorb["low"] if d == 1 else absorb["high"]
                if (b["low"] < broken if d == 1 else b["high"] > broken):
                    phase, absorb = 2, None   # absorpční zóna proražena


def signals_C(f: pd.DataFrame, ib_hi, ib_lo, thr):
    """Rejection: propích za zónu, close zpátky uvnitř, big sweepy proti
    breakoutu ve wicku, delta proti -> reverz k protější straně zóny."""
    for i in range(6, len(f)):
        b = f.iloc[i]
        if (b["high"] > ib_hi and b["close"] < ib_hi
                and b["big_sell_hi"] >= thr and b["delta"] < 0):
            yield f.index[i], -1, b
        if (b["low"] < ib_lo and b["close"] > ib_lo
                and b["big_buy_lo"] >= thr and b["delta"] > 0):
            yield f.index[i], 1, b


def main() -> None:
    f5 = pd.read_parquet(ROOT / "data" / "bars_5min_ivb.parquet")
    m1 = pd.read_parquet(ROOT / "data" / "bars_1min.parquet")
    rows = []
    for day, f in f5.groupby(f5.index.date):
        ib = f.between_time("09:30", "10:00", inclusive="left")
        if len(ib) < 6:
            continue
        ib_hi, ib_lo = ib["high"].max(), ib["low"].min()
        width = ib_hi - ib_lo
        if width <= 0:
            continue
        sig = f.between_time("10:00", "15:00", inclusive="left")
        day_m1 = m1[m1.index.date == day].between_time("10:00", "15:00", inclusive="left")

        for thr, mr, tp in product(ABSORB_THRS, MAX_RISKS, TPS):
            # model A (2 SL varianty)
            for sl in SLS_A:
                for ts, d, b in signals_A(sig, ib_hi, ib_lo, thr):
                    entry = b["close"] + d * SLIP
                    stop = ((b["low"] if d == 1 else b["high"]) - d * TICK if sl == "bar"
                            else (ib_hi - 2 * TICK if d == 1 else ib_lo + 2 * TICK))
                    risk = (entry - stop) * d
                    if not 0 < risk <= mr:
                        continue
                    target = entry + d * (2 * risk if tp == "rrr2" else width)
                    pts = (manage(day_m1, ts, d, entry, stop, target) - entry) * d
                    rows.append({"model": f"A_{sl}", "thr": thr, "maxr": mr, "tp": tp,
                                 "date": str(day), "dir": d,
                                 "net": pts * POINT_VALUE - 2 * COMMISSION})
                    break
            # model B (SL za absorpčním barem)
            for ts, d, b, ab in signals_B(sig, ib_hi, ib_lo, thr):
                entry = b["close"] + d * SLIP
                stop = (ab["low"] if d == 1 else ab["high"]) - d * TICK
                risk = (entry - stop) * d
                if not 0 < risk <= mr:
                    continue
                target = entry + d * (2 * risk if tp == "rrr2" else width)
                pts = (manage(day_m1, ts, d, entry, stop, target) - entry) * d
                rows.append({"model": "B", "thr": thr, "maxr": mr, "tp": tp,
                             "date": str(day), "dir": d,
                             "net": pts * POINT_VALUE - 2 * COMMISSION})
                break
            # model C (SL za extrémem rejection svíčky, TP protější strana zóny)
            for ts, d, b in signals_C(sig, ib_hi, ib_lo, thr):
                entry = b["close"] + d * SLIP
                stop = (b["high"] if d == -1 else b["low"]) + (TICK if d == -1 else -TICK)
                risk = (entry - stop) * d
                if not 0 < risk <= mr:
                    continue
                target = (ib_lo if d == -1 else ib_hi) if tp == "width1" \
                    else entry + d * 2 * risk
                pts = (manage(day_m1, ts, d, entry, stop, target) - entry) * d
                rows.append({"model": "C", "thr": thr, "maxr": mr, "tp": tp,
                             "date": str(day), "dir": d,
                             "net": pts * POINT_VALUE - 2 * COMMISSION})
                break

    df = pd.DataFrame(rows)
    df.to_csv(OUT, index=False)
    df["date"] = pd.to_datetime(df["date"])
    split = df["date"].sort_values().iloc[len(df) // 2]
    print(f"split poloviny: {split.date()}\n")
    print("model   thr maxr tp     |   n   net$    avg$   WR    maxDD$    h1$     h2$")
    for k, g in df.groupby(["model", "thr", "maxr", "tp"]):
        eq = g["net"].cumsum()
        dd = (eq.cummax() - eq).max()
        h1 = g[g["date"] < split]["net"].sum()
        h2 = g[g["date"] >= split]["net"].sum()
        print(f"{k[0]:7s} {k[1]:3d} {k[2]:4d} {k[3]:6s} | {len(g):3d} {g['net'].sum():7,.0f} "
              f"{g['net'].mean():7,.1f} {(g['net'] > 0).mean():.1%} {dd:8,.0f} {h1:7,.0f} {h2:7,.0f}")
    print(f"\nDetail: {OUT}")


if __name__ == "__main__":
    main()
