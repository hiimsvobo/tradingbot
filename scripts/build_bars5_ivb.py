"""5min bary s orderflow featurami pro IVB strategii (jeden průchod ticky).

Pro každý RTH den (9:30-15:00 NY) staví 5min bary s:
- OHLC, volume, delta, body_vol (objem mezi open a close)
- big_buy/big_sell: objem big sweepů (>= 50 ks, fily se stejným ts a stranou)
- big_buy_hi/big_sell_hi: big objem na cenách v horní čtvrtině range baru
- big_buy_lo/big_sell_lo: dtto dolní čtvrtina (wick zóny — absorpce/akceptace)

Výstup: data/bars_5min_ivb.parquet
Použití: python scripts/build_bars5_ivb.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from bot.data import DATA_DIR, load_day

BIG = 50
OUT = Path(__file__).resolve().parent.parent / "data" / "bars_5min_ivb.parquet"


def day_bars(ticks: pd.DataFrame) -> list[dict]:
    out = []
    cur = None  # aktuální bar
    sw_ts, sw_side, sw_size, sw_levels = None, "", 0, {}

    def flush_sweep():
        nonlocal sw_size, sw_levels
        if sw_size >= BIG and cur is not None and sw_side in ("B", "A"):
            key = "big_buy" if sw_side == "B" else "big_sell"
            cur[key] += sw_size
            for p, v in sw_levels.items():
                cur["big_levels"].setdefault(p, [0, 0])[0 if sw_side == "B" else 1] += v
        sw_size, sw_levels = 0, {}

    def close_bar():
        if cur is None:
            return
        rng = cur["high"] - cur["low"]
        q_hi = cur["high"] - 0.25 * rng
        q_lo = cur["low"] + 0.25 * rng
        bb_hi = bs_hi = bb_lo = bs_lo = 0
        for p, (bb, bs) in cur["big_levels"].items():
            if p >= q_hi:
                bb_hi += bb; bs_hi += bs
            if p <= q_lo:
                bb_lo += bb; bs_lo += bs
        lo, hi = sorted((cur["open"], cur["close"]))
        body = sum(v for p, v in cur["levels"].items() if lo <= p <= hi)
        out.append({k: cur[k] for k in
                    ("ts", "open", "high", "low", "close", "volume", "delta",
                     "big_buy", "big_sell")}
                   | {"body_vol": body, "big_buy_hi": bb_hi, "big_sell_hi": bs_hi,
                      "big_buy_lo": bb_lo, "big_sell_lo": bs_lo})

    for ts, price, size, side in zip(ticks.index, ticks["price"].to_numpy(),
                                     ticks["size"].to_numpy(), ticks["side"].to_numpy()):
        slot = ts.floor("5min")
        if cur is None or slot != cur["ts"]:
            flush_sweep()
            close_bar()
            cur = {"ts": slot, "open": price, "high": price, "low": price,
                   "close": price, "volume": 0, "delta": 0, "big_buy": 0,
                   "big_sell": 0, "levels": {}, "big_levels": {}}
        if ts != sw_ts or side != sw_side:
            flush_sweep()
            sw_ts, sw_side = ts, side
        sw_size += size
        sw_levels[price] = sw_levels.get(price, 0) + size

        cur["high"] = max(cur["high"], price)
        cur["low"] = min(cur["low"], price)
        cur["close"] = price
        cur["volume"] += size
        cur["delta"] += size if side == "B" else -size if side == "A" else 0
        cur["levels"][price] = cur["levels"].get(price, 0) + size

    flush_sweep()
    close_bar()
    return out


def main() -> None:
    dates = sorted(p.name.split("-")[2].split(".")[0] for p in DATA_DIR.glob("*.trades.csv"))
    rows = []
    for i, d in enumerate(dates, 1):
        try:
            ticks = load_day(d).tz_convert("America/New_York").between_time("09:30", "15:00")
        except Exception:
            continue
        if len(ticks) < 1000:
            continue
        rows.extend(day_bars(ticks))
        if i % 25 == 0:
            print(f"{i}/{len(dates)}", flush=True)

    df = pd.DataFrame(rows).set_index("ts")
    df.to_parquet(OUT)
    print(f"\n{len(df)} barů -> {OUT}")


if __name__ == "__main__":
    main()
