"""Scalp strategie absorpce -> agrese na 40-range barech, tick-přesná.

Bary si strategie staví průběžně z ticků (žádný lookahead):
- 40-range bar se uzavře, jakmile high-low dosáhne RANGE_PTS; uzavírací
  tick patří do baru, další tick otevírá nový.
- big trade = sweep (souvislé fily se stejným ts a stranou) >= BIG ks;
  objem sweepu se do baru přičítá po dokončení sweepu.
- body_vol = objem na cenách mezi open a close baru (včetně).

Setup LONG (short zrcadlově), vyhodnocuje se na close baru:
1. Absorpce: lokální low (nejnižší low posledních LOOKBACK barů), big
   objem proti směru >= MIN_BIG a (delta divergence NEBO absorpční knot).
2. Agrese do MAX_WAIT barů: delta ve směru >= AGGR_DELTA podílu objemu,
   close ve směru, body_vol > BODY_FRAC objemu.
3. Vstup market na close agrese, jen když risk (|close - stop|) <= MAX_RISK.
   Stop 1 tick za extrémem absorpčního baru, target = entry + risk * RRR.
   Řízení pozice tick po ticku, time-stop 15:55 NY, max 1 pozice.
"""
from dataclasses import dataclass, field
from datetime import time

import pandas as pd

from bot.engine import Strategy, Tick

TICK_SIZE = 0.25
RANGE_PTS = 40 * TICK_SIZE
BIG = 50            # min. kontraktů ve sweepu
MIN_BIG = 100       # min. big objem proti směru v absorpčním baru
LOOKBACK = 10
WICK_FRAC = 0.5
MAX_WAIT = 6
AGGR_DELTA = 0.05
BODY_FRAC = 0.5
MAX_RISK = 15.0
RRR = 2.0
FLAT_TIME = time(15, 55)


@dataclass
class Bar:
    ts_open: pd.Timestamp
    open: float
    high: float
    low: float
    close: float = 0.0
    volume: int = 0
    delta: int = 0
    big_buy: int = 0
    big_sell: int = 0
    levels: dict = field(default_factory=dict)

    @property
    def body_vol(self) -> int:
        lo, hi = min(self.open, self.close), max(self.open, self.close)
        return sum(v for p, v in self.levels.items() if lo <= p <= hi)


@dataclass
class Setup:
    direction: int      # +1 long, -1 short
    stop: float         # za extrémem absorpčního baru
    bars_left: int      # kolik barů zbývá na agresi


class AbsorptionScalp(Strategy):
    def __init__(self, rrr: float = RRR, max_risk: float = MAX_RISK,
                 aggr_delta: float = AGGR_DELTA, body_frac: float = BODY_FRAC,
                 min_big: float = MIN_BIG, max_wait: int = MAX_WAIT,
                 limit_target: bool = True, contracts: int = 2,
                 trail_pts: float | None = None, be_at_r: float | None = None,
                 use_target: bool = True, flat_time: time | None = FLAT_TIME,
                 resume_time: time | None = None):
        super().__init__()
        self.flat_time = flat_time        # zavřít pozici a stop vstupů (None = bez time-stopu)
        self.resume_time = resume_time    # od kdy zase vstupovat (None = do konce dne ne)
        self.rrr = rrr
        self.max_risk = max_risk
        self.aggr_delta = aggr_delta
        self.body_frac = body_frac
        self.min_big = min_big
        self.max_wait = max_wait
        self.limit_target = limit_target  # False = exit na targetu marketem
        self.contracts = contracts        # 2x NQ = max risk $600 při maxR 15 b
        self.trail_pts = trail_pts        # trailing stop v bodech (None = vypnut)
        self.be_at_r = be_at_r            # posun stopu na vstup po X násobcích risku
        self.use_target = use_target      # False = exit jen stopem/trailem
        self._entry_plan = 0.0            # plánovaný vstup (close agrese)
        self._risk = 0.0
        self._best = 0.0                  # nejlepší cena od vstupu (pro trail)
        self._mkt_target: float | None = None
        self.bars: list[Bar] = []
        self.cur: Bar | None = None
        self.setups: list[Setup] = []
        self.stop = self.target = 0.0
        # rozpracovaný sweep
        self._sw_ts = None
        self._sw_side = ""
        self._sw_size = 0

    def _in_flat_window(self, t: time) -> bool:
        """Ve flat okně se zavírá pozice a nevstupuje (time-stop před close)."""
        if self.flat_time is None:
            return False
        if self.resume_time is None:
            return t >= self.flat_time
        return self.flat_time <= t < self.resume_time

    # --- stavba barů ---
    def _flush_sweep(self) -> None:
        if self._sw_size >= BIG and self.cur is not None:
            if self._sw_side == "B":
                self.cur.big_buy += self._sw_size
            elif self._sw_side == "A":
                self.cur.big_sell += self._sw_size
        self._sw_size = 0

    def on_tick(self, tick: Tick) -> None:
        t = tick.ts.time()

        # stop i target hlídá broker (bracket); strategie time-stop
        # (a market target, pokud limit_target=False)
        pos = self.broker.position
        if pos != 0:
            d = 1 if pos > 0 else -1
            # breakeven / trailing: stop se smí jen zpřísnit, nikdy uvolnit
            candidates = []
            if self.be_at_r and (tick.price - self._entry_plan) * d >= self.be_at_r * self._risk:
                candidates.append(self._entry_plan)
            if self.trail_pts is not None:
                if (tick.price - self._best) * d > 0:
                    self._best = tick.price
                candidates.append(self._best - d * self.trail_pts)
            if candidates:
                new_stop = max(candidates, key=lambda s: s * d)
                cur = self.broker._stop
                if cur is None or (new_stop - cur) * d > 0:
                    self.broker.set_bracket(new_stop, self.broker._target)
            hit_mkt_target = (self._mkt_target is not None
                              and (tick.price >= self._mkt_target if pos > 0
                                   else tick.price <= self._mkt_target))
            if self._in_flat_window(t) or hit_mkt_target:
                self.broker.set_position(0)
                self._mkt_target = None

        # sweep hranice: nový timestamp nebo strana -> uzavřít předchozí
        if tick.ts != self._sw_ts or tick.side != self._sw_side:
            self._flush_sweep()
            self._sw_ts, self._sw_side = tick.ts, tick.side
        self._sw_size += tick.size

        if self.cur is None:
            self.cur = Bar(tick.ts, tick.price, tick.price, tick.price)
        b = self.cur
        b.high = max(b.high, tick.price)
        b.low = min(b.low, tick.price)
        b.close = tick.price
        b.volume += tick.size
        if tick.side == "B":
            b.delta += tick.size
        elif tick.side == "A":
            b.delta -= tick.size
        b.levels[tick.price] = b.levels.get(tick.price, 0) + tick.size

        if b.high - b.low >= RANGE_PTS:
            self._flush_sweep()
            self._on_bar_close(b, t)
            self.bars.append(b)
            self.cur = None

    # --- logika na uzavřeném baru ---
    def _on_bar_close(self, b: Bar, t: time) -> None:
        rng = b.high - b.low
        # 1) agrese proti čekajícím setupům (vstup jen flat a před time-stopem)
        if self.broker.position == 0 and rng > 0 and not self._in_flat_window(t):
            for s in self.setups:
                d = s.direction
                aggr = (b.delta * d >= self.aggr_delta * max(b.volume, 1)
                        and (b.close - b.open) * d > 0
                        and b.body_vol > self.body_frac * max(b.volume, 1))
                risk = (b.close - s.stop) * d  # kladné jen se stopem na správné straně
                intact = b.low > s.stop if d == 1 else b.high < s.stop
                if aggr and intact and 0 < risk <= self.max_risk:
                    self.broker.set_position(d * self.contracts)
                    self._entry_plan, self._risk, self._best = b.close, risk, b.close
                    target = (b.close + d * risk * self.rrr) if self.use_target else None
                    if self.limit_target or target is None:
                        self.broker.set_bracket(s.stop, target)
                    else:
                        self.broker.set_bracket(s.stop, None)
                        self._mkt_target = target
                    self.setups.clear()
                    break

        # 2) odpočet čekajících setupů; zrušit setupy s proraženou zónou
        for s in self.setups:
            s.bars_left -= 1
        self.setups = [s for s in self.setups
                       if s.bars_left > 0
                       and (b.low > s.stop if s.direction == 1 else b.high < s.stop)]

        # 3) nový absorpční setup?
        if len(self.bars) < LOOKBACK or rng <= 0:
            return
        window = self.bars[-LOOKBACK:]
        for d in (1, -1):
            extreme = (b.low <= min(w.low for w in window) if d == 1
                       else b.high >= max(w.high for w in window))
            if not extreme:
                continue
            big_against = b.big_sell if d == 1 else b.big_buy
            if big_against < self.min_big:
                continue
            delta_against = b.delta * d < 0
            closed_with = (b.close - b.open) * d > 0
            if d == 1:
                wick = min(b.open, b.close) - b.low
                close_beyond = b.close >= b.low + wick
            else:
                wick = b.high - max(b.open, b.close)
                close_beyond = b.close <= b.high - wick
            divergence = closed_with and delta_against
            wick_absorb = (wick >= WICK_FRAC * rng and delta_against and close_beyond)
            if divergence or wick_absorb:
                stop = b.low - TICK_SIZE if d == 1 else b.high + TICK_SIZE
                self.setups.append(Setup(d, stop, self.max_wait))
