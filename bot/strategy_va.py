"""Strategie VA re-entry.

Setup: den otevře mimo včerejší value area. Pokud se cena do 10:00 (NY)
vrátí dovnitř VA, vstupujeme směrem k včerejšímu POC (long při návratu
zespodu přes VAL, short při návratu shora přes VAH).

Target: včerejší POC. Stop: extrém dneška v době vstupu (low dne pro long).
Time-stop: exit v 15:55, obchoduje se max 1 setup denně.
"""
from collections import deque
from dataclasses import dataclass
from datetime import time

import pandas as pd

from bot.engine import Strategy, Tick


@dataclass(frozen=True)
class Levels:
    poc: float
    vah: float
    val: float


ENTRY_DEADLINE = time(10, 0)
FLAT_TIME = time(15, 55)


class VAReentry(Strategy):
    def __init__(self, levels: Levels, stop_points: float | None = None,
                 min_target_points: float = 0.0,
                 of_mode: str | None = None, of_window_s: float = 120.0,
                 of_min_delta: float = 0.0, of_big_size: int = 20):
        super().__init__()
        self.lv = levels
        self.stop_points = stop_points      # None = extrém dne v době vstupu
        self.min_target = min_target_points  # nevstupovat, když je POC blíž
        # orderflow potvrzení vstupu: None = vypnuto, "delta" = delta všech
        # obchodů v okně, "big" = delta jen obchodů >= of_big_size kontraktů.
        # Vstup jen když delta ve směru obchodu >= of_min_delta; jinak se
        # čeká na další tick (až do deadline).
        self.of_mode = of_mode
        self.of_window_s = of_window_s
        self.of_min_delta = of_min_delta
        self.of_big_size = of_big_size
        self._of_win: deque[tuple[pd.Timestamp, int]] = deque()
        self._of_sum = 0
        self.open_price: float | None = None
        self.side = 0            # +1 čekáme long setup, -1 short, 0 žádný
        self.entered = False
        self.done = False
        self.day_high = -float("inf")
        self.day_low = float("inf")
        self.stop = self.target = 0.0

    def on_tick(self, tick: Tick) -> None:
        t = tick.ts.time()
        self.day_high = max(self.day_high, tick.price)
        self.day_low = min(self.day_low, tick.price)
        if self.of_mode:
            self._of_update(tick)

        if self.open_price is None:
            self.open_price = tick.price
            if tick.price < self.lv.val:
                self.side = 1
            elif tick.price > self.lv.vah:
                self.side = -1
            else:
                self.done = True  # open uvnitř VA -> žádný setup
            return

        if self.done:
            if self.entered and self.broker.position != 0:
                self._manage(tick, t)
            return

        # čekání na re-entry do deadline
        if t >= ENTRY_DEADLINE:
            self.done = True
            return
        if self.side == 1 and tick.price >= self.lv.val:
            if self.lv.poc - tick.price < self.min_target:
                self.done = True
                return
            if not self._of_confirms(1):
                return  # čekáme na potvrzení orderflow
            stop = tick.price - self.stop_points if self.stop_points else self.day_low
            self._enter(tick, 1, stop=stop, target=self.lv.poc)
        elif self.side == -1 and tick.price <= self.lv.vah:
            if tick.price - self.lv.poc < self.min_target:
                self.done = True
                return
            if not self._of_confirms(-1):
                return
            stop = tick.price + self.stop_points if self.stop_points else self.day_high
            self._enter(tick, -1, stop=stop, target=self.lv.poc)

    def _of_update(self, tick: Tick) -> None:
        if self.of_mode == "big" and tick.size < self.of_big_size:
            signed = 0
        else:
            signed = tick.size if tick.side == "B" else -tick.size if tick.side == "A" else 0
        if signed:
            self._of_win.append((tick.ts, signed))
            self._of_sum += signed
        cutoff = tick.ts - pd.Timedelta(seconds=self.of_window_s)
        while self._of_win and self._of_win[0][0] < cutoff:
            self._of_sum -= self._of_win.popleft()[1]

    def _of_confirms(self, direction: int) -> bool:
        if not self.of_mode:
            return True
        return self._of_sum * direction >= self.of_min_delta

    def _enter(self, tick: Tick, direction: int, stop: float, target: float) -> None:
        self.broker.set_position(direction)
        self.stop, self.target = stop, target
        self.entered = True
        self.done = True

    def _manage(self, tick: Tick, t: time) -> None:
        p, pos = tick.price, self.broker.position
        hit_target = p >= self.target if pos > 0 else p <= self.target
        hit_stop = p <= self.stop if pos > 0 else p >= self.stop
        if hit_target or hit_stop or t >= FLAT_TIME:
            self.broker.set_position(0)
