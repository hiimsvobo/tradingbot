"""Event-driven replay engine: přehrává ticky sekvenčně, strategie vidí jen minulost.

Stejné rozhraní později dostane živý feed — vymění se jen zdroj ticků.
"""
from dataclasses import dataclass, field

import pandas as pd

POINT_VALUE = 20.0  # USD za 1 bod NQ (e-mini)


@dataclass(frozen=True)
class Tick:
    ts: pd.Timestamp
    price: float
    size: int
    side: str  # 'B' agresivní nákup, 'A' agresivní prodej, 'N' neurčeno


@dataclass
class Trade:
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp
    direction: int  # +1 long, -1 short
    entry_price: float
    exit_price: float
    size: int = 1   # počet kontraktů

    @property
    def points(self) -> float:
        """Body na 1 kontrakt (bez velikosti pozice)."""
        return (self.exit_price - self.entry_price) * self.direction


class Broker:
    """Simulátor exekuce: market příkaz se plní za cenu NÁSLEDUJÍCÍHO ticku
    (žádné plnění za cenu, na kterou strategie teprve reaguje) + skluz.
    """

    def __init__(self, slippage_ticks: float = 1.0, commission_usd: float = 2.25):
        self.slippage = slippage_ticks * 0.25
        self.commission = commission_usd  # za kontrakt a stranu
        self.position = 0
        self.entry_price = 0.0
        self.entry_ts = None
        self._pending = 0  # požadovaná pozice, čeká na další tick
        self._has_pending = False
        self._stop: float | None = None    # stop-market exit
        self._target: float | None = None  # limit exit
        self.trades: list[Trade] = []
        self.last_price = float("nan")

    # --- API pro strategii ---
    def set_position(self, target: int) -> None:
        """Cílová pozice (-1/0/+1…), provede se na dalším ticku."""
        self._pending = target
        self._has_pending = True

    def set_bracket(self, stop: float | None, target: float | None) -> None:
        """Exitní příkazy k aktuální/vstupující pozici: stop-market na stop,
        limitka na target. Target se plní NA ceně targetu, jakmile se na ní
        zobchoduje (bez skluzu; reálně nese riziko fronty v orderbooku).
        Stop se plní za cenu ticku + skluz. Při zásahu obou v jednom ticku
        má přednost stop. Bracket se ruší s uzavřením pozice.
        """
        self._stop = stop
        self._target = target

    # --- volá engine ---
    def process_tick(self, tick: Tick) -> None:
        if self.position != 0 and not self._has_pending:
            p, pos = tick.price, self.position
            hit_stop = (self._stop is not None
                        and (p <= self._stop if pos > 0 else p >= self._stop))
            hit_target = (self._target is not None
                          and (p >= self._target if pos > 0 else p <= self._target))
            if hit_stop:
                self._fill(tick, 0)
            elif hit_target:
                self._fill(tick, 0, price=self._target)
        if self._has_pending and self._pending != self.position:
            self._fill(tick, self._pending)
        self._has_pending = False
        self.last_price = tick.price

    def _fill(self, tick: Tick, target: int, price: float | None = None) -> None:
        delta = target - self.position
        fill_price = price if price is not None else (
            tick.price + self.slippage * (1 if delta > 0 else -1))
        if self.position != 0:  # zavření (i otočka) staré pozice
            self.trades.append(Trade(self.entry_ts, tick.ts, 1 if self.position > 0 else -1,
                                     self.entry_price, fill_price, abs(self.position)))
        if target != 0:
            self.entry_price = fill_price
            self.entry_ts = tick.ts
        else:
            self._stop = self._target = None
        self.position = target

    def finish(self, tick: Tick) -> None:
        """Na konci dat zavře otevřenou pozici za poslední cenu."""
        if self.position != 0:
            self._fill(tick, 0)

    # --- výsledky ---
    def results(self) -> dict:
        gross = sum(t.points * t.size for t in self.trades) * POINT_VALUE
        fees = sum(2 * self.commission * t.size for t in self.trades)
        pnl_per_trade = [t.points * t.size * POINT_VALUE - 2 * self.commission * t.size
                         for t in self.trades]
        equity = pd.Series(pnl_per_trade).cumsum()
        max_dd = float((equity.cummax() - equity).max()) if len(equity) else 0.0
        wins = sum(1 for p in pnl_per_trade if p > 0)
        return {
            "trades": len(self.trades),
            "gross_usd": round(gross, 2),
            "fees_usd": round(fees, 2),
            "net_usd": round(gross - fees, 2),
            "win_rate": round(wins / len(self.trades), 3) if self.trades else None,
            "max_drawdown_usd": round(max_dd, 2),
        }


class Strategy:
    """Základ strategie: dostává ticky, přes self.broker řídí pozici."""

    def __init__(self):
        self.broker: Broker | None = None

    def on_tick(self, tick: Tick) -> None:
        raise NotImplementedError

    def on_finish(self) -> None:
        pass


def run(ticks: pd.DataFrame, strategy: Strategy, broker: Broker | None = None) -> dict:
    """Přehraje DataFrame ticků (index ts_event, sloupce price/size/side) strategii."""
    broker = broker or Broker()
    strategy.broker = broker
    tick = None
    for ts, price, size, side in zip(ticks.index, ticks["price"].to_numpy(),
                                     ticks["size"].to_numpy(), ticks["side"].to_numpy()):
        tick = Tick(ts, float(price), int(size), str(side))
        broker.process_tick(tick)  # nejdřív plnění čekajících příkazů
        strategy.on_tick(tick)     # pak reakce strategie (projeví se dalším tickem)
    if tick is not None:
        broker.finish(tick)
    strategy.on_finish()
    return broker.results()
