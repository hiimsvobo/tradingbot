"""Vykreslí ukázkové obchody absorpční strategie: range bary, absorpční
zóna, vstup, SL, TP, exit + panel delty s big trades.

Použití: python scripts/plot_absorption_trades.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib.pyplot as plt
import pandas as pd

from scripts.backtest_absorption import BARS, run_day

OUTDIR = Path(__file__).resolve().parent.parent / "outputs"
RRR = 1.5

INK = "#1f2430"; MUTED = "#6b7280"; GRID = "#e5e7eb"
UP = "#7db8a8"; DOWN = "#c98a8a"          # tlumené svíčky (pozadí příběhu)
ENTRY = "#3d5a80"; SLC = "#b3423a"; TPC = "#2e7d5b"
ZONE = "#e9c46a"; BIGC = "#8a6bb8"

plt.rcParams.update({"font.size": 10, "axes.edgecolor": GRID,
                     "text.color": INK, "axes.labelcolor": MUTED,
                     "xtick.color": MUTED, "ytick.color": MUTED})


def plot_trade(day: pd.DataFrame, tr: dict, path: Path) -> None:
    a, e, x = tr["abs_i"], tr["entry_i"], tr["exit_i"]
    lo = max(0, a - 15)
    hi = min(len(day), x + 8)
    w = day.iloc[lo:hi]
    ix = range(len(w))
    risk = abs(tr["entry"] - tr["stop"])
    target = tr["entry"] + tr["dir"] * risk * RRR

    fig, (ax, axd) = plt.subplots(2, 1, figsize=(12, 7), sharex=True,
                                  height_ratios=[3, 1],
                                  gridspec_kw={"hspace": 0.06})
    # svíčky
    for k, (_, b) in enumerate(w.iterrows()):
        color = UP if b["close"] >= b["open"] else DOWN
        ax.plot([k, k], [b["low"], b["high"]], color=color, lw=1, zorder=2)
        ax.add_patch(plt.Rectangle((k - 0.3, min(b["open"], b["close"])), 0.6,
                                   max(abs(b["close"] - b["open"]), 0.25),
                                   facecolor=color, edgecolor="none", zorder=3))
    # absorpční zóna
    ab = day.iloc[a]
    ax.axvspan(a - lo - 0.45, a - lo + 0.45, color=ZONE, alpha=0.35, zorder=1)
    ax.annotate("absorpce", (a - lo, ab["high"] + 3), ha="center", color=INK,
                fontsize=9, fontweight="bold")
    # úrovně: entry / SL / TP přes dobu trvání obchodu
    for level, color, lab in [(tr["entry"], ENTRY, f"vstup {tr['entry']:,.2f}"),
                              (tr["stop"], SLC, f"SL {tr['stop']:,.2f}"),
                              (target, TPC, f"TP {target:,.2f}")]:
        ax.hlines(level, e - lo, x - lo, color=color, lw=1.6, zorder=4)
        ax.annotate(lab, (x - lo + 0.4, level), va="center", color=color, fontsize=9)
    m = "^" if tr["dir"] == 1 else "v"
    ax.scatter([e - lo], [tr["entry"]], marker=m, s=110, color=ENTRY, zorder=5,
               edgecolor="white", linewidth=1)
    ax.scatter([x - lo], [tr["exit"]], marker="x", s=90, color=INK, zorder=5)
    side = "LONG" if tr["dir"] == 1 else "SHORT"
    res = f"{tr['net_usd']:+,.0f} USD ({tr['points']:+.2f} b)"
    ax.set_title(f"{tr['date']}  {side}  —  {res}", loc="left", fontweight="bold")
    ax.grid(axis="y", color=GRID, lw=0.6)
    ax.set_axisbelow(True)

    # delta panel, big trades proti směru zvýrazněné
    big_against = w["big_sell"] if tr["dir"] == 1 else w["big_buy"]
    axd.bar(ix, w["delta"], 0.6, color=[UP if v >= 0 else DOWN for v in w["delta"]])
    axd.scatter([k for k, v in zip(ix, big_against) if v > 0],
                [0] * int((big_against > 0).sum()), marker="D", s=28,
                color=BIGC, zorder=5, label="big trades proti směru (≥50 ks)")
    axd.axhline(0, color=MUTED, lw=0.8)
    axd.set_ylabel("delta (ks)")
    axd.grid(axis="y", color=GRID, lw=0.6)
    axd.set_axisbelow(True)
    axd.legend(loc="upper left", frameon=False, fontsize=8)

    step = max(1, len(w) // 8)
    axd.set_xticks(list(ix)[::step])
    axd.set_xticklabels([t.strftime("%H:%M") for t in w.index[::step]])
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
        axd.spines[s].set_visible(False)
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    bars = pd.read_parquet(BARS)
    bars["date"] = bars.index.date
    days = {d: g for d, g in bars.groupby("date") if len(g) > 50}

    trades = []
    for d, day in days.items():
        for t in run_day(day, RRR):
            t["_day"] = d
            trades.append(t)
    tr = pd.DataFrame(trades)
    wins = tr[tr["net_usd"] > 0].nlargest(2, "net_usd")
    losses = tr[tr["net_usd"] < 0].nsmallest(2, "net_usd")
    # + typický (mediánový) win a loss, ať to nejsou jen extrémy
    typical_w = tr[tr["net_usd"] > 0].sort_values("net_usd").iloc[[len(tr[tr["net_usd"] > 0]) // 2]]
    typical_l = tr[tr["net_usd"] < 0].sort_values("net_usd").iloc[[len(tr[tr["net_usd"] < 0]) // 2]]

    for label, group in [("win", pd.concat([wins, typical_w])),
                         ("loss", pd.concat([losses, typical_l]))]:
        for n, (_, t) in enumerate(group.iterrows(), 1):
            path = OUTDIR / f"trade_{label}{n}_{t['date']}.png"
            plot_trade(days[t["_day"]], t.to_dict(), path)
            print(path)


if __name__ == "__main__":
    main()
