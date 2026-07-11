"""Předzpracování: všechny denní tick CSV -> jeden parquet s 1min bary.

Pro každou minutu (NY čas): OHLCV, delta, big-trade delta (>=20 ks),
počet obchodů, sum(price*size) pro VWAP. Jen hlavní kontrakt daného dne.

Použití: python scripts/build_bars.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from bot.data import DATA_DIR, load_day

OUT = Path(__file__).resolve().parent.parent / "data" / "bars_1min.parquet"
BIG = 20  # kontraktů


def day_bars(date: str) -> pd.DataFrame:
    df = load_day(date)
    df = df.tz_convert("America/New_York")
    signed = df["size"] * np.where(df["side"] == "B", 1, np.where(df["side"] == "A", -1, 0))
    big_mask = df["size"] >= BIG
    pv = df["price"] * df["size"]

    g = df["price"].resample("1min")
    bars = pd.DataFrame({
        "open": g.first(), "high": g.max(), "low": g.min(), "close": g.last(),
        "volume": df["size"].resample("1min").sum(),
        "delta": signed.resample("1min").sum(),
        "big_delta": signed[big_mask].resample("1min").sum(),
        "big_volume": df.loc[big_mask, "size"].resample("1min").sum(),
        "trades": g.count(),
        "pv": pv.resample("1min").sum(),
    }).dropna(subset=["open"])
    bars[["big_delta", "big_volume"]] = bars[["big_delta", "big_volume"]].fillna(0)
    bars["symbol"] = df["symbol"].iloc[0]
    return bars


def main() -> None:
    dates = sorted(p.name.split("-")[2].split(".")[0] for p in DATA_DIR.glob("*.trades.csv"))
    out, failed = [], []
    for i, d in enumerate(dates, 1):
        try:
            out.append(day_bars(d))
        except Exception as e:  # dny s minimem dat (svátky) apod.
            failed.append((d, str(e)))
        if i % 25 == 0:
            print(f"{i}/{len(dates)}", flush=True)
    bars = pd.concat(out).sort_index()
    bars.to_parquet(OUT)
    print(f"Hotovo: {len(bars):,} minutových barů, {len(out)} dní -> {OUT}")
    if failed:
        print(f"Přeskočeno {len(failed)} dní: {[f[0] for f in failed][:10]}")


if __name__ == "__main__":
    main()
