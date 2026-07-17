"""Předzpracování: tick CSV -> jeden parquet se 40-range bary (RTH, NY čas).

Range bar se uzavře, jakmile high-low dosáhne 40 ticků (10 bodů NQ);
další tick otevírá nový bar. Pro každý bar: OHLC, časy otevření/zavření,
objem, buy/sell objem, delta, big-trade buy/sell, počet obchodů
a body_vol = objem zobchodovaný v těle svíčky (mezi open a close včetně).

Big trade = sweep (souvislý blok plnění se stejným ts_event a stranou,
tj. jeden velký market order rozpadlý na dílčí fily) o >= BIG kontraktech.
Samostatná plnění >= 50 ks jsou vzácná (~8/den), sweepy >= 50 ks ~100/den —
to odpovídá tomu, co zobrazují footprint platformy.

Použití: python scripts/build_range_bars.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from bot.data import DATA_DIR, load_day

OUT = Path(__file__).resolve().parent.parent / "data" / "bars_40range.parquet"
RANGE_PTS = 40 * 0.25  # 40 ticků = 10 bodů
BIG = 50  # kontraktů v jednom sweepu


def day_range_bars(date: str) -> pd.DataFrame:
    df = load_day(date).tz_convert("America/New_York").between_time("09:30", "16:00")
    if df.empty:
        return pd.DataFrame()
    ts = df.index.to_numpy()
    price = df["price"].to_numpy()
    size = df["size"].to_numpy()
    is_buy = (df["side"] == "B").to_numpy()
    is_sell = (df["side"] == "A").to_numpy()
    # sweep = souvislý blok filů se stejným ts_event a stranou; fil je "big",
    # patří-li do sweepu o >= BIG kontraktech
    grp = pd.Series(
        (df.index.to_series().ne(df.index.to_series().shift())
         | df["side"].ne(df["side"].shift())).cumsum().to_numpy()
    )
    sweep_size = pd.Series(size).groupby(grp).transform("sum").to_numpy()
    big = sweep_size >= BIG

    rows = []
    o = h = l = price[0]
    t_open = ts[0]
    buy = sell = big_buy = big_sell = vol = n = 0
    levels: dict[float, int] = {}

    def close_bar(i: int) -> None:
        cl = price[i]
        lo, hi = min(o, cl), max(o, cl)
        body_vol = sum(v for p, v in levels.items() if lo <= p <= hi)
        rows.append((t_open, ts[i], o, h, l, cl,
                     vol, buy, sell, big_buy, big_sell, n, body_vol))

    for i in range(len(price)):
        p = price[i]
        h = max(h, p)
        l = min(l, p)
        vol += size[i]
        levels[p] = levels.get(p, 0) + size[i]
        n += 1
        if is_buy[i]:
            buy += size[i]
            if big[i]:
                big_buy += size[i]
        elif is_sell[i]:
            sell += size[i]
            if big[i]:
                big_sell += size[i]
        if h - l >= RANGE_PTS:
            close_bar(i)
            if i + 1 < len(price):
                o = h = l = price[i + 1]
                t_open = ts[i + 1]
                buy = sell = big_buy = big_sell = vol = n = 0
                levels = {}
    if n:
        close_bar(len(price) - 1)

    bars = pd.DataFrame(rows, columns=["ts_open", "ts_close", "open", "high", "low",
                                       "close", "volume", "buy", "sell",
                                       "big_buy", "big_sell", "trades", "body_vol"])
    bars["delta"] = bars["buy"] - bars["sell"]
    return bars.set_index("ts_close")


def main() -> None:
    dates = sorted(p.name.split("-")[2].split(".")[0] for p in DATA_DIR.glob("*.trades.csv"))
    out, failed = [], []
    for i, d in enumerate(dates, 1):
        try:
            b = day_range_bars(d)
            if len(b):
                out.append(b)
        except Exception as e:
            failed.append((d, str(e)))
        if i % 25 == 0:
            print(f"{i}/{len(dates)}", flush=True)
    bars = pd.concat(out).sort_index()
    bars.to_parquet(OUT)
    print(f"Hotovo: {len(bars):,} range barů, {len(out)} dní -> {OUT}")
    if failed:
        print(f"Přeskočeno {len(failed)} dní: {[f[0] for f in failed][:10]}")


if __name__ == "__main__":
    main()
