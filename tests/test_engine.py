"""Testy replay enginu na syntetických ticích — ruční kontrola PnL."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from bot.engine import Broker, Strategy, Tick, run


def make_ticks(prices):
    idx = pd.date_range("2025-01-01 09:00", periods=len(prices), freq="s")
    return pd.DataFrame({"price": prices, "size": 1, "side": "B"}, index=idx)


class BuyAtSecondTick(Strategy):
    def __init__(self):
        super().__init__()
        self.n = 0

    def on_tick(self, tick: Tick):
        self.n += 1
        if self.n == 2:
            self.broker.set_position(1)
        elif self.n == 4:
            self.broker.set_position(0)


def test_long_pnl_with_slippage():
    # Příkaz z ticku 2 se plní na ticku 3 (cena 101 + 0.25 skluz),
    # výstup z ticku 4 se plní na ticku 5 (cena 103 - 0.25).
    ticks = make_ticks([100.0, 100.5, 101.0, 102.0, 103.0])
    res = run(ticks, BuyAtSecondTick(), Broker(slippage_ticks=1, commission_usd=0))
    assert res["trades"] == 1
    expected_points = (103.0 - 0.25) - (101.0 + 0.25)  # 1.5 bodu
    assert res["net_usd"] == expected_points * 20


def test_open_position_closed_at_end():
    ticks = make_ticks([100.0, 100.0, 100.0, 110.0])

    class BuyAndHold(Strategy):
        def __init__(self):
            super().__init__()
            self.done = False

        def on_tick(self, tick):
            if not self.done:
                self.broker.set_position(1)
                self.done = True

    res = run(ticks, BuyAndHold(), Broker(slippage_ticks=0, commission_usd=0))
    assert res["trades"] == 1  # pozice zavřená na konci dat
    assert res["net_usd"] == (110.0 - 100.0) * 20


def test_no_lookahead_fill():
    """Příkaz zadaný na ticku t se NIKDY neplní za cenu ticku t."""
    ticks = make_ticks([100.0, 200.0, 300.0])

    class BuyImmediately(Strategy):
        def __init__(self):
            super().__init__()
            self.done = False

        def on_tick(self, tick):
            if not self.done:
                self.broker.set_position(1)
                self.done = True

    broker = Broker(slippage_ticks=0, commission_usd=0)
    run(ticks, BuyImmediately(), broker)
    # zadáno na ticku 1 (cena 100), plněno na ticku 2 (cena 200)
    assert broker.trades[0].entry_price == 200.0
