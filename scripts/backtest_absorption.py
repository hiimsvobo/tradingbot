"""Backtest scalp strategie: absorpce -> agrese na 40-range barech (NQ).

Setup LONG (short zrcadlově):
1. Absorpční bar: lokální low (nejnižší low posledních LOOKBACK barů),
   kumulace big trades proti směru (big sweepy >= 50 ks na prodejní straně
   o objemu >= MIN_BIG kontraktů — velcí prodejci, které trh absorboval)
   a současně aspoň jedna známka absorpce prodávajících:
   - delta divergence: bar zavře bullish (close > open), ale delta je
     záporná — agresivní prodejci absorbováni, cena přesto nahoru; nebo
   - absorpční knot: spodní knot >= WICK_FRAC rozpětí baru, delta záporná
     a close nad knotem (v horní části baru).
2. Agrese: do MAX_WAIT barů po absorpci přijde bar, kde
   - delta ve směru >= AGGR_DELTA podílu objemu baru (default 10 %),
   - close ve směru (bullish pro long),
   - většina objemu zobchodována v těle svíčky (body_vol > 1/2 objemu).
3. Vstup: market na close agresivního baru. Stop: low absorpčního baru - 1 tick.
   Target: RRR x risk. Time-stop 15:55 NY. Max 1 pozice najednou.

Náklady: komise $2,25/strana, skluz 1 tick/strana.

Použití: python scripts/backtest_absorption.py
"""
import sys
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

BARS = Path(__file__).resolve().parent.parent / "data" / "bars_40range.parquet"
OUT = Path(__file__).resolve().parent.parent / "outputs" / "absorption_trades.csv"

POINT_VALUE = 20.0
TICK = 0.25
COMMISSION = 2.25   # USD/strana
SLIPPAGE = TICK     # 1 tick/strana
COST_USD = 2 * COMMISSION + 2 * SLIPPAGE * POINT_VALUE  # celkem/obchod

LOOKBACK = 10       # barů pro lokální extrém
WICK_FRAC = 0.5     # min. podíl knotu na rozpětí baru
MIN_BIG = 100       # min. objem big sweepů proti směru v absorpčním baru
MAX_WAIT = 6        # barů na agresi
AGGR_DELTA = 0.10   # min. delta/objem agresivního baru ve směru
BODY_FRAC = 0.5     # min. podíl objemu v těle agresivní svíčky
RRRS = [1.0, 1.5, 2.0]
FLAT = pd.Timestamp("15:55").time()


def day_signals(day: pd.DataFrame, aggr_delta: float = AGGR_DELTA,
                min_absorb: float = 0.0, last_entry: str | None = None,
                body_frac: float = BODY_FRAC, min_big: float = MIN_BIG,
                aggr_mode: str = "delta") -> list[dict]:
    """Vrátí kandidátní vstupy (bez řízení pozice) pro jeden den.

    min_absorb: min. |delta|/objem absorpčního baru (síla absorpce).
    last_entry: poslední čas vstupu, např. "12:00" (NY), None = bez omezení.
    """
    o = day["open"].to_numpy(); h = day["high"].to_numpy()
    l = day["low"].to_numpy(); c = day["close"].to_numpy()
    buy = day["buy"].to_numpy().astype(float)
    sell = day["sell"].to_numpy().astype(float)
    delta = day["delta"].to_numpy().astype(float)
    vol = day["volume"].to_numpy().astype(float)
    body = day["body_vol"].to_numpy().astype(float)
    big_buy = day["big_buy"].to_numpy().astype(float)
    big_sell = day["big_sell"].to_numpy().astype(float)
    ts = day.index
    deadline = pd.Timestamp(last_entry).time() if last_entry else None

    sigs = []
    for i in range(LOOKBACK, len(day)):
        if deadline and ts[i].time() >= deadline:
            break
        w_l, w_h = l[i - LOOKBACK:i], h[i - LOOKBACK:i]
        rng = h[i] - l[i]
        for d in (1, -1):
            extreme = l[i] <= w_l.min() if d == 1 else h[i] >= w_h.max()
            if not extreme or rng <= 0:
                continue
            # kumulace big trades proti směru = velcí hráči k absorbování
            big_against = big_sell[i] if d == 1 else big_buy[i]
            if big_against < min_big:
                continue
            # delta proti směru obchodu = agresoři, které trh absorboval
            delta_against = (delta[i] * d < 0
                             and abs(delta[i]) >= min_absorb * max(vol[i], 1))
            closed_with = (c[i] - o[i]) * d > 0  # close ve směru obchodu
            if d == 1:
                wick = min(o[i], c[i]) - l[i]
                close_beyond_wick = c[i] >= l[i] + wick
            else:
                wick = h[i] - max(o[i], c[i])
                close_beyond_wick = c[i] <= h[i] - wick
            divergence = closed_with and delta_against
            wick_absorb = (wick >= WICK_FRAC * rng and delta_against
                           and close_beyond_wick)
            if not (divergence or wick_absorb):
                continue
            # hledej agresi do MAX_WAIT barů; proražení zóny setup ruší
            stop_lvl = l[i] - TICK if d == 1 else h[i] + TICK
            for j in range(i + 1, min(i + 1 + MAX_WAIT, len(day))):
                if (l[j] <= stop_lvl) if d == 1 else (h[j] >= stop_lvl):
                    break  # zóna proražena
                if aggr_mode == "ratio":  # v1: poměr buy/sell, bez body podmínky
                    ratio = (buy[j] / max(sell[j], 1)) if d == 1 else (sell[j] / max(buy[j], 1))
                    aggr = ratio >= 1.10 and (c[j] - o[j]) * d > 0
                else:
                    aggr = (delta[j] * d >= aggr_delta * max(vol[j], 1)
                            and (c[j] - o[j]) * d > 0
                            and body[j] > body_frac * max(vol[j], 1))
                if aggr:
                    # risk kladný jen se stopem na správné straně vstupu
                    sigs.append({"dir": d, "abs_i": i, "entry_i": j, "entry_ts": ts[j],
                                 "entry": c[j], "stop": stop_lvl,
                                 "risk": (c[j] - stop_lvl) * d})
                    break
    return sigs


def run_day(day: pd.DataFrame, rrr: float, max_risk: float = float("inf"),
            **sig_kw) -> list[dict]:
    """Sekvenční exekuce: max 1 pozice, další signál až po exitu.

    max_risk: max. vzdálenost vstupu od stopu v bodech (= vstup jen blízko
    zóny; dál od zóny se signál zahazuje).
    """
    h = day["high"].to_numpy(); l = day["low"].to_numpy(); c = day["close"].to_numpy()
    ts = day.index
    trades = []
    busy_until = -1
    for s in day_signals(day, **sig_kw):
        i = s["entry_i"]
        if i <= busy_until or ts[i].time() >= FLAT or s["risk"] <= 0:
            continue
        if s["risk"] > max_risk:
            continue
        d, entry, stop = s["dir"], s["entry"], s["stop"]
        target = entry + d * s["risk"] * rrr
        exit_p, exit_i = None, None
        for j in range(i + 1, len(day)):
            if ts[j].time() >= FLAT:
                exit_p, exit_i = c[j], j
                break
            hit_stop = l[j] <= stop if d == 1 else h[j] >= stop
            hit_tgt = h[j] >= target if d == 1 else l[j] <= target
            if hit_stop:  # konzervativně: při zásahu obou v jednom baru bereme stop
                exit_p, exit_i = stop, j
                break
            if hit_tgt:
                exit_p, exit_i = target, j
                break
        if exit_p is None:
            exit_p, exit_i = c[-1], len(day) - 1
        busy_until = exit_i
        pts = (exit_p - entry) * d
        trades.append({"date": ts[i].date(), "dir": d, "abs_i": s["abs_i"],
                       "entry_i": i, "exit_i": exit_i,
                       "stop": s["stop"], "entry_ts": ts[i],
                       "exit_ts": ts[exit_i], "entry": entry, "exit": exit_p,
                       "risk_pts": round(s["risk"], 2), "points": round(pts, 2),
                       "net_usd": round(pts * POINT_VALUE - COST_USD, 2)})
    return trades


def report(tr: pd.DataFrame, label: str) -> None:
    if tr.empty:
        print(f"{label}: žádné obchody")
        return
    eq = tr["net_usd"].cumsum()
    dd = (eq.cummax() - eq).max()
    wr = (tr["net_usd"] > 0).mean()
    print(f"{label}: obchodů {len(tr)}, net ${tr['net_usd'].sum():,.0f}, "
          f"avg ${tr['net_usd'].mean():,.1f}, WR {wr:.1%}, maxDD ${dd:,.0f}, "
          f"L/S {len(tr[tr['dir'] == 1])}/{len(tr[tr['dir'] == -1])}")


def main() -> None:
    bars = pd.read_parquet(BARS)
    bars["date"] = bars.index.date
    days = [g for _, g in bars.groupby("date") if len(g) > 50]

    all_out = []
    for rrr in RRRS:
        rows = [t for day in days for t in run_day(day, rrr)]
        tr = pd.DataFrame(rows)
        tr["rrr"] = rrr
        all_out.append(tr)
        report(tr, f"RRR 1:{rrr}")
        if not tr.empty:
            half = tr["date"].iloc[len(tr) // 2]
            report(tr[tr["date"] < half], f"  1. půlka (do {half})")
            report(tr[tr["date"] >= half], f"  2. půlka")

    pd.concat(all_out).to_csv(OUT, index=False)
    print(f"\nDetail: {OUT}")


if __name__ == "__main__":
    main()
