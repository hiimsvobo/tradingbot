"""Walk-forward test absorpční scalp strategie na 40-range barech.

Mřížka: delta agrese x podmínka těla x max risk (vzdálenost od zóny) x RRR.
Výběr nejlepší kombinace podle net na 1. polovině roku, vyhodnocení
na neviděné 2. polovině. Navíc: kolik kombinací je OOS ziskových a
percentil zvolené kombinace.

Použití: python scripts/walkforward_absorption.py
"""
import sys
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.backtest_absorption import BARS, run_day

OUT = Path(__file__).resolve().parent.parent / "outputs" / "absorption_walkforward.csv"

AGGR_DELTAS = [0.05, 0.10]
BODY_FRACS = [0.0, 0.4, 0.5]
MAX_RISKS = [10, 12, 15]
RRRS = [1.0, 1.5, 2.0]


def stats(s: pd.Series) -> str:
    eq = s.cumsum()
    dd = (eq.cummax() - eq).max() if len(s) else 0
    wr = (s > 0).mean() if len(s) else 0
    return f"obchodů {len(s)}, net ${s.sum():,.0f}, avg ${s.mean():,.1f}, WR {wr:.1%}, maxDD ${dd:,.0f}"


def main() -> None:
    bars = pd.read_parquet(BARS)
    bars["date"] = bars.index.date
    days = [g for _, g in bars.groupby("date") if len(g) > 50]
    combos = list(product(AGGR_DELTAS, BODY_FRACS, MAX_RISKS, RRRS))

    rows = []
    for n, day in enumerate(days, 1):
        for ad, bf, mr, rrr in combos:
            for t in run_day(day, rrr, max_risk=mr, aggr_delta=ad, body_frac=bf):
                rows.append({"date": t["date"], "aggr_delta": ad, "body": bf,
                             "max_risk": mr, "rrr": rrr, "net": t["net_usd"]})
        if n % 25 == 0:
            print(f"{n}/{len(days)}", flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(OUT, index=False)

    dates = sorted(df["date"].unique())
    split = dates[len(dates) // 2]
    ins = df[df["date"] < split]
    oos = df[df["date"] >= split]
    print(f"\nSplit: in-sample do {split}, out-of-sample od {split}")

    keys = ["aggr_delta", "body", "max_risk", "rrr"]
    rank = ins.groupby(keys)["net"].sum().sort_values(ascending=False)
    best = rank.index[0]
    print(f"Nejlepší na 1. pololetí: delta {best[0]:.0%}, tělo {best[1]:.0%}, "
          f"maxR {best[2]}, RRR 1:{best[3]} (IS net ${rank.iloc[0]:,.0f})")

    sel = dict(zip(keys, best))
    m_is = (ins[keys] == pd.Series(sel)).all(axis=1)
    m_oos = (oos[keys] == pd.Series(sel)).all(axis=1)
    print(f"In-sample    : {stats(ins[m_is]['net'])}")
    print(f"Out-of-sample: {stats(oos[m_oos]['net'])}")

    oos_all = oos.groupby(keys)["net"].sum()
    print(f"\nOOS ziskových kombinací: {(oos_all > 0).sum()}/{len(oos_all)}")
    print(f"OOS percentil zvolené kombinace: {(oos_all < oos_all[best]).mean():.0%}")

    print("\nTop 5 IS kombinací a jejich OOS:")
    for combo in rank.index[:5]:
        print(f"  {combo}: IS ${rank[combo]:,.0f} -> OOS ${oos_all.get(combo, 0):,.0f}")


if __name__ == "__main__":
    main()
