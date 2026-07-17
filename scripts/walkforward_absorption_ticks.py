"""Walk-forward absorpční strategie na tick-přesném enginu.

Mřížka 16 kombinací (delta x tělo x maxR x RRR), každý den se ticky
načtou jednou a přehrají všem kombinacím. Výběr na 1. polovině,
vyhodnocení na 2. polovině.

Použití: python scripts/walkforward_absorption_ticks.py
"""
import sys
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from bot.data import DATA_DIR, load_day
from bot.engine import POINT_VALUE, Broker, run
from bot.strategy_absorption import AbsorptionScalp

OUT = Path(__file__).resolve().parent.parent / "outputs" / "absorption_ticks_walkforward.csv"

AGGR_DELTA = 0.05        # 10 % konzistentně horší ve všech screenech
BODY_FRACS = [0.4, 0.5]
MAX_RISKS = [12, 15]
RRRS = [1.5, 2.0]
MAX_WAITS = [3, 4, 6]    # barů na agresi po absorpci


def stats(s: pd.Series) -> str:
    eq = s.cumsum()
    dd = (eq.cummax() - eq).max() if len(s) else 0
    wr = (s > 0).mean() if len(s) else 0
    return f"obchodů {len(s)}, net ${s.sum():,.0f}, avg ${s.mean():,.1f}, WR {wr:.1%}, maxDD ${dd:,.0f}"


def main() -> None:
    dates = sorted(p.name.split("-")[2].split(".")[0] for p in DATA_DIR.glob("*.trades.csv"))
    combos = list(product(BODY_FRACS, MAX_RISKS, RRRS, MAX_WAITS))

    rows = []
    for i, d in enumerate(dates, 1):
        try:
            ticks = load_day(d).tz_convert("America/New_York").between_time("09:30", "16:00")
        except Exception:
            continue
        if len(ticks) < 1000:
            continue
        for bf, mr, rrr, mw in combos:
            broker = Broker()
            run(ticks, AbsorptionScalp(rrr=rrr, max_risk=mr, aggr_delta=AGGR_DELTA,
                                       body_frac=bf, max_wait=mw), broker)
            for t in broker.trades:
                rows.append({"date": d, "body": bf, "max_risk": mr,
                             "rrr": rrr, "max_wait": mw,
                             "net": t.points * POINT_VALUE - 2 * broker.commission})
        if i % 10 == 0:
            print(f"{i}/{len(dates)}", flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(OUT, index=False)

    dates_t = sorted(df["date"].unique())
    split = dates_t[len(dates_t) // 2]
    ins, oos = df[df["date"] < split], df[df["date"] >= split]
    print(f"\nSplit: in-sample do {split}, out-of-sample od {split}")

    keys = ["body", "max_risk", "rrr", "max_wait"]
    rank = ins.groupby(keys)["net"].sum().sort_values(ascending=False)
    best = rank.index[0]
    print(f"Nejlepší na 1. pololetí: tělo {best[0]:.0%}, maxR {best[1]}, "
          f"RRR 1:{best[2]}, wait {best[3]} (IS net ${rank.iloc[0]:,.0f})")
    sel = dict(zip(keys, best))
    m_is = (ins[keys] == pd.Series(sel)).all(axis=1)
    m_oos = (oos[keys] == pd.Series(sel)).all(axis=1)
    print(f"In-sample    : {stats(ins[m_is]['net'])}")
    print(f"Out-of-sample: {stats(oos[m_oos]['net'])}")

    oos_all = oos.groupby(keys)["net"].sum()
    print(f"\nOOS ziskových kombinací: {(oos_all > 0).sum()}/{len(oos_all)}")
    print("\nVšechny kombinace IS -> OOS:")
    for combo in rank.index:
        print(f"  {combo}: IS ${rank[combo]:>7,.0f} -> OOS ${oos_all.get(combo, 0):>7,.0f}")


if __name__ == "__main__":
    main()
