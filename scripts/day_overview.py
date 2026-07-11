"""Přehled jednoho dne: orderflow metriky + graf.

Použití: python scripts/day_overview.py 2025-07-07
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from bot.data import load_day
from bot.orderflow import delta_bars, large_trades, poc, volume_profile

INK = "#333"
PRICE_C = "#3b6ea5"
DELTA_POS = "#2e7d5b"
DELTA_NEG = "#b0413e"


def main(date: str) -> None:
    df = load_day(date)
    symbol = df["symbol"].iloc[0]
    bars = delta_bars(df, "1min")
    prof = volume_profile(df)
    big = large_trades(df, 20)

    day_delta = int(bars["delta"].sum())
    print(f"=== {symbol} {date} ===")
    print(f"Ticků: {len(df):,} | Objem: {int(df['size'].sum()):,} kontraktů")
    print(f"Rozsah: {df['price'].min():.2f} – {df['price'].max():.2f} | Close: {df['price'].iloc[-1]:.2f}")
    print(f"Denní delta: {day_delta:+,} | POC: {poc(prof):.2f}")
    print(f"Velké obchody (>=20 ks): {len(big):,} (objem {int(big['size'].sum()):,})")

    fig, (ax1, ax2, ax3) = plt.subplots(
        3, 1, figsize=(12, 9), sharex=True,
        gridspec_kw={"height_ratios": [3, 1.2, 1.2]},
    )
    fig.suptitle(f"NQ ({symbol}) — {date}, 1min bary", color=INK)

    ax1.plot(bars.index, bars["close"], color=PRICE_C, lw=1.2)
    ax1.axhline(poc(prof), color=INK, lw=0.8, ls="--", alpha=0.5)
    ax1.annotate(f"POC {poc(prof):.2f}", xy=(bars.index[0], poc(prof)),
                 fontsize=8, color=INK, va="bottom")
    ax1.set_ylabel("Cena")

    ax2.plot(bars.index, bars["cum_delta"], color=INK, lw=1.2)
    ax2.axhline(0, color=INK, lw=0.6, alpha=0.4)
    ax2.set_ylabel("Kum. delta")

    colors = [DELTA_POS if d >= 0 else DELTA_NEG for d in bars["delta"]]
    ax3.bar(bars.index, bars["delta"], width=1 / 1440, color=colors)
    ax3.set_ylabel("Delta / 1min")

    for ax in (ax1, ax2, ax3):
        ax.grid(alpha=0.2)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)

    out = Path(__file__).resolve().parent.parent / "outputs"
    out.mkdir(exist_ok=True)
    out_file = out / f"day_{date.replace('-', '')}.png"
    fig.savefig(out_file, dpi=120, bbox_inches="tight")
    print(f"Graf: {out_file}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2025-07-07")
