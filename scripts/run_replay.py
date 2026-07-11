"""Demo běh replay enginu na reálném dni.

Strategie je jen ukázková (sleduje kumulativní deltu za posledních N minut),
slouží k ověření enginu, ne k obchodování.

Použití: python scripts/run_replay.py 2025-07-07
"""
import sys
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from bot.data import load_day
from bot.engine import Strategy, Tick, run


class CumDeltaDemo(Strategy):
    """Long když klouzavá delta > +threshold, short když < -threshold, jinak flat."""

    def __init__(self, window_min: int = 15, threshold: int = 800):
        super().__init__()
        self.window = pd.Timedelta(minutes=window_min)
        self.threshold = threshold
        self.buf: deque[tuple[pd.Timestamp, int]] = deque()
        self.delta = 0

    def on_tick(self, tick: Tick) -> None:
        signed = tick.size if tick.side == "B" else -tick.size if tick.side == "A" else 0
        self.buf.append((tick.ts, signed))
        self.delta += signed
        while self.buf and tick.ts - self.buf[0][0] > self.window:
            self.delta -= self.buf.popleft()[1]

        if self.delta > self.threshold:
            self.broker.set_position(1)
        elif self.delta < -self.threshold:
            self.broker.set_position(-1)
        else:
            self.broker.set_position(0)


def main(date: str) -> None:
    df = load_day(date)
    t0 = time.perf_counter()
    res = run(df, CumDeltaDemo())
    dt = time.perf_counter() - t0
    print(f"=== Replay {date} ({df['symbol'].iloc[0]}), {len(df):,} ticků za {dt:.1f}s ===")
    for k, v in res.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2025-07-07")
