"""IVB model A s filtrem velikosti svíčky — tick-přesná verze.

IB = high/low 9:30-9:45 NY (z ticků). Od 9:45 se staví 5min bary; na close
baru vstup (long, short zrcadlově), pokud:
- close > IB high, delta baru > 0, volume >= VOL_MULT x průměr předchozích 6 barů
- wick proti směru <= WICK_MAX x range, big sweepy proti směru v krajní
  čtvrtině baru < ABSORB_MAX (žádná absorpce)
- risk = |close - (extrém baru -+ tick)| >= MIN_RISK (jen "přesvědčivé" svíčky)
Stop za extrémem breakoutové svíčky, target 3R limitkou, flat 15:00,
max 1 obchod/den.
"""
from dataclasses import dataclass, field
from datetime import time

import pandas as pd

from bot.engine import Strategy, Tick

TICK_SIZE = 0.25
BIG = 50
IB_START, IB_END = time(9, 30), time(9, 45)
FLAT = time(15, 0)
VOL_MULT = 1.2
WICK_MAX = 0.25
ABSORB_MAX = 100
MIN_RISK = 60.0
RRR = 3.0


@dataclass
class Bar5:
    slot: pd.Timestamp
    open: float
    high: float
    low: float
    close: float = 0.0
    volume: int = 0
    delta: int = 0
    big_levels: dict = field(default_factory=dict)  # price -> [big_buy, big_sell]


class IvbBreakout(Strategy):
    def __init__(self, min_risk: float = MIN_RISK, rrr: float = RRR,
                 contracts: int = 1):
        super().__init__()
        self.min_risk, self.rrr, self.contracts = min_risk, rrr, contracts
        self.ib_hi = self.ib_lo = None
        self.bars: list[Bar5] = []
        self.cur: Bar5 | None = None
        self.traded_day = None
        # rozpracovaný sweep
        self._sw_ts = None
        self._sw_side = ""
        self._sw_size = 0
        self._sw_levels: dict = {}

    def _flush_sweep(self) -> None:
        if self._sw_size >= BIG and self.cur is not None and self._sw_side in ("B", "A"):
            k = 0 if self._sw_side == "B" else 1
            for p, v in self._sw_levels.items():
                self.cur.big_levels.setdefault(p, [0, 0])[k] += v
        self._sw_size, self._sw_levels = 0, {}

    def on_tick(self, tick: Tick) -> None:
        ts, t = tick.ts, tick.ts.time()

        if t >= FLAT and self.broker.position != 0:
            self.broker.set_position(0)

        # IB fáze
        if IB_START <= t < IB_END:
            if self.ib_hi is None or tick.price > self.ib_hi:
                self.ib_hi = tick.price
            if self.ib_lo is None or tick.price < self.ib_lo:
                self.ib_lo = tick.price
            return
        if t < IB_START:
            self.ib_hi = self.ib_lo = None   # nový den
            self.bars.clear()
            self.cur = None
            return
        if self.ib_hi is None or t >= FLAT:
            return

        # sweep hranice
        if ts != self._sw_ts or tick.side != self._sw_side:
            self._flush_sweep()
            self._sw_ts, self._sw_side = ts, tick.side
        self._sw_size += tick.size
        self._sw_levels[tick.price] = self._sw_levels.get(tick.price, 0) + tick.size

        slot = ts.floor("5min")
        if self.cur is None or slot != self.cur.slot:
            self._flush_sweep()
            if self.cur is not None:
                self._on_bar_close(self.cur)
                self.bars.append(self.cur)
                if len(self.bars) > 50:
                    self.bars.pop(0)
            self.cur = Bar5(slot, tick.price, tick.price, tick.price)
        b = self.cur
        b.high = max(b.high, tick.price)
        b.low = min(b.low, tick.price)
        b.close = tick.price
        b.volume += tick.size
        if tick.side == "B":
            b.delta += tick.size
        elif tick.side == "A":
            b.delta -= tick.size

    def _on_bar_close(self, b: Bar5) -> None:
        if (self.broker.position != 0 or self.traded_day == b.slot.date()
                or len(self.bars) < 6):
            return
        vol_avg = sum(x.volume for x in self.bars[-6:]) / 6
        rng = b.high - b.low
        if rng <= 0 or b.volume < VOL_MULT * vol_avg:
            return
        for d, edge in ((1, self.ib_hi), (-1, self.ib_lo)):
            if (b.close - edge) * d <= 0 or b.delta * d <= 0:
                continue
            wick = (b.high - b.close) if d == 1 else (b.close - b.low)
            if wick > WICK_MAX * rng:
                continue
            q = b.high - 0.25 * rng if d == 1 else b.low + 0.25 * rng
            absorb = sum(v[1 if d == 1 else 0] for p, v in b.big_levels.items()
                         if (p >= q if d == 1 else p <= q))
            if absorb >= ABSORB_MAX:
                continue
            stop = (b.low - TICK_SIZE) if d == 1 else (b.high + TICK_SIZE)
            risk = (b.close - stop) * d
            if risk < self.min_risk:
                continue
            self.traded_day = b.slot.date()
            self.broker.set_position(d * self.contracts)
            self.broker.set_bracket(stop, b.close + d * risk * self.rrr)
            return
