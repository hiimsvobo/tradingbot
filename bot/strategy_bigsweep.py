"""Big-sweep counter-flow continuation, tick-přesná verze.

Signál (long, short zrcadlově): >= K big sweepů STEJNÉ strany (agresivní
prodeje "A") v pásmu W bodů během T minut, zatímco 15min trend je NAHORU
(counter-flow, který trh vstřebává) -> vstup po směru trendu.

Vstup market po dokončení kumulace, stop-market za pásmem kumulace
s odstupem OFF bodů, exit časem po HOLD minutách. Okno signálů 9:45-12:00
NY, max 1 obchod/den, cooldown 10 min mezi kumulacemi.

Sizing: fixní risk RISK_USD přes počet kontraktů (MNQ: point_value 2 USD).
"""
from collections import deque
from datetime import time
from math import floor

import pandas as pd

from bot.engine import Strategy, Tick

BIG = 50
K = 3
T = pd.Timedelta("5min")
W = 5.0
OFF = 20.0
HOLD = pd.Timedelta("30min")
COOL = pd.Timedelta("10min")
TREND = pd.Timedelta("15min")
WIN_A, WIN_B = time(9, 45), time(12, 0)
RISK_USD, MAX_CON, POINT_VALUE = 500.0, 30, 2.0  # MNQ


class BigSweepFlow(Strategy):
    def __init__(self, k: int = K, w: float = W, off: float = OFF,
                 hold: pd.Timedelta = HOLD, risk_usd: float = RISK_USD,
                 point_value: float = POINT_VALUE):
        super().__init__()
        self.k, self.w, self.off = k, w, off
        self.hold, self.risk_usd, self.pv = hold, risk_usd, point_value
        self.sweeps: deque = deque()      # (ts, side, price) dokončené big sweepy
        self.prices: deque = deque()      # (ts, price) pro 15min trend
        self._sw_ts = None
        self._sw_side = ""
        self._sw_size = 0
        self._sw_price = 0.0
        self._last_fire = None
        self._entry_ts = None
        self._traded_today = None

    def _flush_sweep(self) -> None:
        if self._sw_size >= BIG and self._sw_side in ("B", "A"):
            self.sweeps.append((self._sw_ts, self._sw_side, self._sw_price))
        self._sw_size = 0

    def on_tick(self, tick: Tick) -> None:
        ts, t = tick.ts, tick.ts.time()

        # trend okno
        self.prices.append((ts, tick.price))
        while self.prices and ts - self.prices[0][0] > TREND:
            self.prices.popleft()

        # time-exit pozice
        if self.broker.position != 0 and self._entry_ts is not None \
                and ts - self._entry_ts >= self.hold:
            self.broker.set_position(0)
            self._entry_ts = None

        # sweep hranice
        if ts != self._sw_ts or tick.side != self._sw_side:
            self._flush_sweep()
            self._sw_ts, self._sw_side, self._sw_price = ts, tick.side, tick.price
        self._sw_size += tick.size
        self._sw_price = tick.price   # cena posledního filu sweepu

        while self.sweeps and ts - self.sweeps[0][0] > T:
            self.sweeps.popleft()

        if not (WIN_A <= t < WIN_B) or self.broker.position != 0:
            return
        if self._traded_today == ts.date():
            return
        if self._last_fire is not None and ts - self._last_fire < COOL:
            return
        if self._sw_size >= BIG:      # kumulaci vyhodnocuj vč. právě běžícího sweepu
            cand = list(self.sweeps) + [(ts, self._sw_side, self._sw_price)]
        else:
            cand = list(self.sweeps)
        if not cand:
            return
        ts0, side0, p0 = cand[-1]
        if ts0 != ts:
            return                    # vyhodnocení jen v okamžiku nového sweepu
        band = [p for (tt, ss, p) in cand if ss == side0 and abs(p - p0) <= self.w]
        if len(band) < self.k or len(self.prices) < 2:
            return
        trend = self.prices[-1][1] - self.prices[0][1]
        d = 1 if (side0 == "A" and trend > 0) else -1 if (side0 == "B" and trend < 0) else 0
        if d == 0:
            return
        self._last_fire = ts
        stop = (min(band) - self.off) if d == 1 else (max(band) + self.off)
        risk = (tick.price - stop) * d
        if risk <= 0:
            return
        ncon = min(MAX_CON, floor(self.risk_usd / (risk * self.pv)))
        if ncon < 1:
            return
        self._traded_today = ts.date()
        self._entry_ts = ts
        self.broker.set_position(d * ncon)
        self.broker.set_bracket(stop, None)
