"""Strategie VA re-entry.

Setup: den otevře mimo včerejší value area. Pokud se cena do 10:00 (NY)
vrátí dovnitř VA, vstupujeme směrem k včerejšímu POC (long při návratu
zespodu přes VAL, short při návratu shora přes VAH).

Target: včerejší POC. Stop: extrém dneška v době vstupu (low dne pro long).
Time-stop: exit v 15:55, obchoduje se max 1 setup denně.
"""
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
                 min_target_points: float = 0.0):
        super().__init__()
        self.lv = levels
        self.stop_points = stop_points      # None = extrém dne v době vstupu
        self.min_target = min_target_points  # nevstupovat, když je POC blíž
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
            stop = tick.price - self.stop_points if self.stop_points else self.day_low
            self._enter(tick, 1, stop=stop, target=self.lv.poc)
        elif self.side == -1 and tick.price <= self.lv.vah:
            if tick.price - self.lv.poc < self.min_target:
                self.done = True
                return
            stop = tick.price + self.stop_points if self.stop_points else self.day_high
            self._enter(tick, -1, stop=stop, target=self.lv.poc)

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
